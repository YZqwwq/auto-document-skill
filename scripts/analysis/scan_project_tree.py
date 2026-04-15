#!/usr/bin/env python3
"""
建立功能树与代码树映射文档，并更新 project-docs 元数据。
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from analysis.architecture_domains import infer_architecture_domains, recommended_domain_ids, tracked_top_level_paths
from core.git_tracking import capture_git_snapshot, merge_git_state
from core.path_intelligence import DEFAULT_OMIT_DIR_NAMES, build_path_evidence, infer_title_from_path, is_root_context_signal_path, score_root_entry
from core.workflow_state import ensure_workflow_state, mark_structure_aligned, mark_structure_drafted, summary_gate_message, summary_is_confirmed
from generation.create_module_doc import detect_project_traits


DEFAULT_DOC_DIR = "project-docs"
DEFAULT_EXCLUDES = DEFAULT_OMIT_DIR_NAMES | {"tmp", "temp"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_doc_root(project_root: Path, doc_root: str | None) -> Path:
    if doc_root:
        candidate = Path(doc_root)
        return candidate if candidate.is_absolute() else (project_root / candidate)
    return project_root / DEFAULT_DOC_DIR


def load_index(doc_root: Path) -> tuple[Path, dict]:
    index_path = doc_root / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"在 {index_path} 未找到 index.json。请先初始化文档。")
    return index_path, json.loads(index_path.read_text(encoding="utf-8"))


def git_ignore_enabled(project_root: Path) -> bool:
    return (project_root / ".gitignore").exists()


@lru_cache(maxsize=32)
def declared_gitignore_entries(project_root_str: str) -> tuple[str, ...]:
    gitignore_path = Path(project_root_str) / ".gitignore"
    if not gitignore_path.exists():
        return ()
    entries = []
    for raw_line in gitignore_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        entries.append(line)
    return tuple(entries)


def matches_declared_gitignore(project_root: Path, relative_path: str) -> bool:
    clean = relative_path.replace("\\", "/").strip("/")
    if not clean:
        return False
    for pattern in declared_gitignore_entries(str(project_root)):
        normalized = pattern.replace("\\", "/").strip()
        if not normalized:
            continue
        if normalized.endswith("/"):
            normalized = normalized.rstrip("/")
        if any(token in normalized for token in ("*", "?", "[")):
            continue
        if normalized.startswith("/"):
            prefix = normalized.strip("/")
            if clean == prefix or clean.startswith(prefix + "/"):
                return True
            continue
        if "/" not in normalized:
            if clean == normalized or clean.startswith(normalized + "/"):
                return True
    return False


@lru_cache(maxsize=4096)
def is_git_ignored(project_root_str: str, relative_path: str) -> bool:
    if not relative_path:
        return False
    if matches_declared_gitignore(Path(project_root_str), relative_path):
        return True
    try:
        result = subprocess.run(
            ["git", "-C", project_root_str, "check-ignore", "-q", relative_path],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def is_tooling_root_file(path: Path, project_root: Path) -> bool:
    del project_root
    return False


def architecture_focus_score(entry: Path, project_root: Path) -> int:
    try:
        rel = entry.relative_to(project_root)
    except ValueError:
        return 0
    if len(rel.parts) != 1:
        return 0
    return score_root_entry(entry)


def is_architecture_focus_entry(entry: Path, project_root: Path) -> bool:
    return architecture_focus_score(entry, project_root) >= 18


def should_skip(path: Path, project_root: Path, include_hidden: bool) -> bool:
    name = path.name
    rel = path.relative_to(project_root)
    if rel.parts and rel.parts[0] == "project-docs":
        return True
    if name in DEFAULT_EXCLUDES:
        return True
    if not include_hidden and name.startswith("."):
        return True
    if is_tooling_root_file(path, project_root):
        return True
    if git_ignore_enabled(project_root) and is_git_ignored(str(project_root), rel.as_posix()):
        return True
    return False


def build_tree(path: Path, project_root: Path, max_depth: int, include_hidden: bool, depth: int = 0) -> list[str]:
    if depth == 0:
        lines = [f"{project_root.name}/"]
    else:
        lines = []

    if depth >= max_depth:
        return lines

    entries = sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    visible_entries = [entry for entry in entries if not should_skip(entry, project_root, include_hidden)]
    if depth == 0:
        visible_entries = [entry for entry in visible_entries if is_architecture_focus_entry(entry, project_root)]
    for index, entry in enumerate(visible_entries):
        connector = "└── " if index == len(visible_entries) - 1 else "├── "
        indent = "    " * depth
        display = entry.name + ("/" if entry.is_dir() else "")
        lines.append(f"{indent}{connector}{display}")
        if entry.is_dir():
            child_lines = build_tree(entry, project_root, max_depth, include_hidden, depth + 1)
            if child_lines:
                lines.extend(child_lines)
    return lines


def summarize_top_level(project_root: Path, include_hidden: bool) -> list[dict]:
    items = []
    for entry in sorted(project_root.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if should_skip(entry, project_root, include_hidden):
            continue
        if not is_architecture_focus_entry(entry, project_root):
            continue
        summary = {
            "path": entry.name,
            "type": "directory" if entry.is_dir() else "file",
            "file_count": 0,
            "dir_count": 0,
            "focus_score": architecture_focus_score(entry, project_root),
            "evidence": build_path_evidence(entry.name, entry.resolve())[:3],
        }
        if entry.is_dir():
            file_count = 0
            dir_count = 0
            for nested in entry.rglob("*"):
                if should_skip(nested, project_root, include_hidden):
                    continue
                if nested.is_dir():
                    dir_count += 1
                else:
                    file_count += 1
            summary["file_count"] = file_count
            summary["dir_count"] = dir_count
        items.append(summary)
    return items


def recommend_targets(top_level: list[dict]) -> list[str]:
    directories = [item for item in top_level if item["type"] == "directory"]
    ranked = sorted(
        directories,
        key=lambda item: (item.get("focus_score", 0), item["file_count"] + item["dir_count"] * 2, item["path"].lower()),
        reverse=True,
    )
    return [item["path"] for item in ranked if item.get("focus_score", 0) >= 18][:6]


def render_stack_section(project_root: Path) -> str:
    traits = detect_project_traits(project_root)
    lines = [f"- 当前从依赖中识别到的主要技术栈：{'、'.join(traits) if traits else '待补充'}"]
    if traits:
        lines.append("- 这些技术栈信号只能作为理解路径的背景，不应直接替代功能域判断。")
    if not traits:
        lines.append("- 当前无法仅凭依赖可靠识别技术栈，请在 summary 已确认的前提下手动补充。")
    return "\n".join(lines)


def write_structure_doc(
    doc_root: Path,
    project_root: Path,
    top_level: list[dict],
    tree_lines: list[str],
    targets: list[str],
    domains: list[dict],
    max_depth: int,
    summary_confirmed_at: str | None = None,
) -> None:
    type_labels = {
        "directory": "目录",
        "file": "文件",
    }
    important_paths = "\n".join(
        [
            (
                f"- `{item['path']}`：{type_labels.get(item['type'], item['type'])}，"
                f"{item['file_count']} 个文件，{item['dir_count']} 个子目录。"
                f" 证据：{' '.join(item.get('evidence', []))}"
            )
            for item in top_level
        ]
    )
    domain_lookup = {domain["id"]: domain for domain in domains}
    recommended = "\n".join(
        [
            (
                f"- `{domain_lookup[target]['title']}`：当前主要落在 `{', '.join(domain_lookup[target]['paths'])}`。"
                f" 候选依据：{'；'.join(domain_lookup[target].get('signal_basis', [])[:2])}"
            )
            for target in targets
            if target in domain_lookup
        ]
    ) if targets else "- 无"
    reading_order = "\n".join(
        [
            f"{index}. `{domain_lookup[target]['title']}`"
            for index, target in enumerate(targets, start=1)
            if target in domain_lookup
        ]
    ) if targets else "1. 暂无推荐目标"
    domain_lookup = {domain["id"]: domain for domain in domains}
    first_layer_domains = [domain for domain in domains if domain.get("level") == 1]
    second_layer_domains = [domain for domain in domains if domain.get("level") == 2]
    third_layer_domains = [domain for domain in domains if domain.get("level") == 3]
    first_layer_text = "\n".join(
        [
            (
                f"- `{domain['title']}`：{domain['summary']} 代码落点：`{', '.join(domain['paths'])}`。"
                f" 候选依据：{'；'.join(domain.get('signal_basis', [])[:2])}"
            )
            for domain in first_layer_domains
        ]
    ) if first_layer_domains else "- 尚未推断出稳定的第一层功能域"
    second_layer_text = "\n".join(
        [
            (
                f"- `{domain['title']}`：挂在 `{domain_lookup.get(domain.get('parent_id'), {}).get('title', domain.get('parent_id'))}` 之下。"
                f"{domain['summary']} 代码落点：`{', '.join(domain['paths'])}`。"
                f" 候选依据：{'；'.join(domain.get('signal_basis', [])[:2])}"
            )
            for domain in second_layer_domains
        ]
    ) if second_layer_domains else "- 当前没有继续下沉的第二层专题域"
    third_layer_text = "\n".join(
        [
            (
                f"- `{domain['title']}`：挂在 `{domain_lookup.get(domain.get('parent_id'), {}).get('title', domain.get('parent_id'))}` 之下。"
                f"{domain['summary']} 代码落点：`{', '.join(domain['paths'])}`。"
                f" 候选依据：{'；'.join(domain.get('signal_basis', [])[:2])}"
            )
            for domain in third_layer_domains
        ]
    ) if third_layer_domains else "- 当前没有继续下沉的第三层专题域"
    stack_section = render_stack_section(project_root)
    summary_anchor = summary_confirmed_at or "待确认"
    content = f"""# 项目结构

## 文档定位

这份文档不是普通目录树快照，而是一份“功能树到代码树”的映射说明。
它的重点不是展示有哪些目录，而是回答：

- 这个项目当前主要有哪些功能层级
- 每一层功能在代码中主要落在哪里
- 应该从哪个功能入口开始阅读代码

## 这份文档适合什么时候看

- 已有 summary 基线，需要进一步建立功能树与代码树映射
- 需要确认某一功能域在代码里主要落在哪些路径和文件
- 需要为 `modules/` 生成功能域文档提供结构中间层

## 扫描元数据

- 项目根目录：`{project_root}`
- 生成时间：`{utc_now()}`
- 最大深度：`{max_depth}`
- 当前基于的 summary 确认时间：`{summary_anchor}`

## 技术栈与默认目录语义

{stack_section}

## 第一层功能树

{first_layer_text}

## 下级功能树

### 第二层功能域

{second_layer_text}

### 第三层功能域

{third_layer_text}

## 代码树映射辅助视图

### 顶层目录树快照

```text
{chr(10).join(tree_lines)}
```

### 顶层路径概览与证据

{important_paths if important_paths else "- 无"}

## 映射边界

- 这里优先记录功能边界与代码落点关系，而不是穷举所有目录
- 根级文本和配置文件应视为“理解项目意图与边界的证据”，而不是直接等价于功能域
- 这份文档不直接替代 summary；它只负责把 summary 映射成功能层级和代码入口

## 推荐阅读顺序

{reading_order}

## 当前推荐继续下钻的功能域

{recommended}
"""
    (doc_root / "overview" / "project-structure.md").write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描仓库并建立功能树与代码树映射文档。")
    parser.add_argument("--project-root", required=True, help="需要扫描的仓库根目录。")
    parser.add_argument("--doc-root", help="文档根目录。默认使用 <project-root>/project-docs。")
    parser.add_argument("--max-depth", type=int, default=2, help="目录树渲染的最大深度。")
    parser.add_argument("--include-hidden", action="store_true", help="包含以点开头的文件和目录。")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    doc_root = normalize_doc_root(project_root, args.doc_root).resolve()
    index_path, index_payload = load_index(doc_root)
    ensure_workflow_state(index_payload)

    if not summary_is_confirmed(index_payload):
        print(f"[阻止] {summary_gate_message(index_payload)}")
        print("[下一步] 请先让 `overview/project-summary.md` 成为可继续的项目基线，再建立功能树映射。")
        return 0

    mark_structure_drafted(index_payload)
    tree_lines = build_tree(project_root, project_root, args.max_depth, args.include_hidden)
    top_level = summarize_top_level(project_root, args.include_hidden)
    domains = infer_architecture_domains(project_root)
    targets = recommended_domain_ids(domains)
    git_snapshot = capture_git_snapshot(project_root)

    write_structure_doc(
        doc_root,
        project_root,
        top_level,
        tree_lines,
        targets,
        domains,
        args.max_depth,
        summary_confirmed_at=index_payload.get("summary_state", {}).get("confirmed_at"),
    )

    index_payload["last_scan_at"] = utc_now()
    index_payload["tracked_paths"] = tracked_top_level_paths(domains) or [item["path"] for item in top_level]
    index_payload["architecture_domains"] = domains
    index_payload["round_two_targets"] = targets
    generated = set(index_payload.get("generated_docs", []))
    generated.add("overview/project-structure.md")
    index_payload["generated_docs"] = sorted(generated)
    mark_structure_aligned(index_payload, git_snapshot)
    index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot)
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[完成] 已写入功能树与代码树映射文档：{doc_root / 'overview' / 'project-structure.md'}")
    print(f"[完成] 推荐继续下钻的功能域：{', '.join(targets) if targets else '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
