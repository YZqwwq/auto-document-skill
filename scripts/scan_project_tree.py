#!/usr/bin/env python3
"""
生成第一轮项目目录树快照，并更新 project-docs 元数据。
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from architecture_domains import infer_architecture_domains, recommended_domain_ids, tracked_top_level_paths


DEFAULT_DOC_DIR = "project-docs"
DEFAULT_EXCLUDES = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".next",
    ".cache",
    "tmp",
    "temp",
}
ROOT_TOOLING_FILES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "tsconfig.json",
    "tsconfig.node.json",
    "tsconfig.web.json",
    "vite.config.ts",
    "vite.config.js",
    "electron.vite.config.ts",
    "electron-builder.yml",
    "electron-builder.yaml",
    "eslint.config.mjs",
    "postcss.config.mjs",
    "tailwind.config.js",
    "tailwind.config.ts",
    "dev-app-update.yml",
}
ARCHITECTURE_PRIMARY_DIRS = {
    "src",
    "app",
    "server",
    "client",
    "backend",
    "frontend",
    "packages",
    "libs",
    "lib",
    "core",
    "runtime",
    "services",
    "developmentlog",
    "docs",
    "doc",
    "design",
    "specs",
}
ARCHITECTURE_SECONDARY_DIRS = {
    "test",
    "tests",
    "__tests__",
    "examples",
    "scripts",
}
ARCHITECTURE_OMIT_DIRS = {
    "out",
    "dist",
    "build",
    "coverage",
    ".next",
    "resources",
    "assets",
    "public",
    "static",
}


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
    try:
        rel = path.relative_to(project_root)
    except ValueError:
        return False
    return path.is_file() and len(rel.parts) == 1 and path.name in ROOT_TOOLING_FILES


def architecture_focus_score(entry: Path, project_root: Path) -> int:
    try:
        rel = entry.relative_to(project_root)
    except ValueError:
        return 0
    if len(rel.parts) != 1:
        return 0
    name = entry.name
    lower_name = name.lower()
    if entry.is_dir():
        if lower_name in ARCHITECTURE_PRIMARY_DIRS:
            return 100
        if lower_name in ARCHITECTURE_SECONDARY_DIRS:
            return 40
        if lower_name in ARCHITECTURE_OMIT_DIRS:
            return 0
        return 25
    if lower_name in {"architecture.md", "system.md", "design.md"}:
        return 50
    if lower_name == "readme.md":
        return 10
    return 0


def is_architecture_focus_entry(entry: Path, project_root: Path) -> bool:
    return architecture_focus_score(entry, project_root) >= 40


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
    return [item["path"] for item in ranked if item.get("focus_score", 0) >= 40][:6]


def write_structure_doc(
    doc_root: Path,
    project_root: Path,
    top_level: list[dict],
    tree_lines: list[str],
    targets: list[str],
    domains: list[dict],
    max_depth: int,
) -> None:
    type_labels = {
        "directory": "目录",
        "file": "文件",
    }
    important_paths = "\n".join(
        [
            f"- `{item['path']}`：{type_labels.get(item['type'], item['type'])}，{item['file_count']} 个文件，{item['dir_count']} 个子目录"
            for item in top_level
        ]
    )
    domain_lookup = {domain["id"]: domain for domain in domains}
    recommended = "\n".join(
        [
            f"- `{domain_lookup[target]['title']}`：覆盖 `{', '.join(domain_lookup[target]['paths'])}`"
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
            f"- `{domain['title']}`：覆盖 `{', '.join(domain['paths'])}`"
            for domain in first_layer_domains
        ]
    ) if first_layer_domains else "- 尚未推断出稳定的第一层功能域"
    second_layer_text = "\n".join(
        [
            f"- `{domain['title']}`：挂在 `{domain_lookup.get(domain.get('parent_id'), {}).get('title', domain.get('parent_id'))}` 之下，覆盖 `{', '.join(domain['paths'])}`"
            for domain in second_layer_domains
        ]
    ) if second_layer_domains else "- 当前没有继续下沉的第二层专题域"
    third_layer_text = "\n".join(
        [
            f"- `{domain['title']}`：挂在 `{domain_lookup.get(domain.get('parent_id'), {}).get('title', domain.get('parent_id'))}` 之下，覆盖 `{', '.join(domain['paths'])}`"
            for domain in third_layer_domains
        ]
    ) if third_layer_domains else "- 当前没有继续下沉的第三层专题域"
    content = f"""# 项目结构

## 文档定位

这是一份偏 AI 使用的结构快照，用来在短时间内扫过大量路径、目录层级和功能域映射。
正常人类阅读项目时，不应先从这份文档开始，而应优先读 `overview/project-summary.md` 和 `modules/README.md`。

## 这份文档适合什么时候看

- 需要快速确认当前仓库有哪些关键路径
- 需要把目录树和功能域做一次快速对照
- 需要让 AI 在短时间内建立大体路径地图

## 扫描元数据

- 项目根目录：`{project_root}`
- 生成时间：`{utc_now()}`
- 最大深度：`{max_depth}`

## 顶层目录树

```text
{chr(10).join(tree_lines)}
```

## 顶层路径说明

{important_paths if important_paths else "- 无"}

## 功能域快照

### 第一层功能域

{first_layer_text}

### 第二层专题域

{second_layer_text}

## 扫描边界

- 这里优先记录与项目理念、运行时实现、架构说明直接相关的路径
- `package.json`、`tsconfig*`、构建配置等工具性根级文件默认不进入当前文档主视野
- 技术栈只做轻量背景说明，不作为文档展开重点

## AI 建议入口顺序

{reading_order}

## 当前推荐继续下钻的专题

{recommended}
"""
    (doc_root / "overview" / "project-structure.md").write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描仓库并写入第一轮结构文档。")
    parser.add_argument("--project-root", required=True, help="需要扫描的仓库根目录。")
    parser.add_argument("--doc-root", help="文档根目录。默认使用 <project-root>/project-docs。")
    parser.add_argument("--max-depth", type=int, default=2, help="目录树渲染的最大深度。")
    parser.add_argument("--include-hidden", action="store_true", help="包含以点开头的文件和目录。")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    doc_root = normalize_doc_root(project_root, args.doc_root).resolve()
    index_path, index_payload = load_index(doc_root)

    tree_lines = build_tree(project_root, project_root, args.max_depth, args.include_hidden)
    top_level = summarize_top_level(project_root, args.include_hidden)
    domains = infer_architecture_domains(project_root)
    targets = recommended_domain_ids(domains)

    write_structure_doc(doc_root, project_root, top_level, tree_lines, targets, domains, args.max_depth)

    index_payload["last_scan_at"] = utc_now()
    index_payload["analysis_round"] = max(int(index_payload.get("analysis_round", 0)), 1)
    index_payload["tracked_paths"] = tracked_top_level_paths(domains) or [item["path"] for item in top_level]
    index_payload["architecture_domains"] = domains
    index_payload["round_two_targets"] = targets
    generated = set(index_payload.get("generated_docs", []))
    generated.add("overview/project-structure.md")
    index_payload["generated_docs"] = sorted(generated)
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[完成] 已写入结构文档：{doc_root / 'overview' / 'project-structure.md'}")
    print(f"[完成] 推荐的第二轮目标：{', '.join(targets) if targets else '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
