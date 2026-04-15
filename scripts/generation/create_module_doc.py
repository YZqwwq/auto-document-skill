#!/usr/bin/env python3
"""
生成功能域文档，并将其登记到 index.json。

当前版本的重点不是“给一个路径生成说明”，而是：

- 优先按功能域生成文档
- 在文档中解释功能层级、代码落点和阅读入口
- 将路径输入仅作为解析到功能域的兼容方式
"""

from __future__ import annotations

import argparse
import json
import posixpath
from pathlib import Path

from analysis.architecture_domains import domains_by_parent
from core.git_tracking import capture_git_snapshot, merge_git_state
from core.path_intelligence import (
    CODE_SUFFIXES,
    DEFAULT_OMIT_DIR_NAMES,
    MARKDOWN_SUFFIXES,
    STRUCTURED_TEXT_SUFFIXES,
    build_path_evidence,
    collect_readme_summary,
    collect_sample_entries,
    infer_title_from_path,
    is_low_semantic_risk_path,
    normalize_relpath,
    safe_read_text,
    summarize_path,
)
from core.workflow_state import (
    ensure_workflow_state,
    mark_modules_aligned,
    mark_modules_drafted,
    structure_gate_message,
    structure_is_aligned,
    summary_gate_message,
    summary_is_confirmed,
)


DEFAULT_DOC_DIR = "project-docs"
SKILL_NAME = "auto-document"
SKILL_VERSION = "0.4.0"
DOC_SCHEMA_VERSION = "2.0.0"
README_CANDIDATES = ("README.md", "README.mdx", "readme.md")
IGNORED_ENTRY_NAMES = {"__pycache__", ".ds_store"} | DEFAULT_OMIT_DIR_NAMES
REPRESENTATIVE_SCAN_SUFFIXES = CODE_SUFFIXES | MARKDOWN_SUFFIXES | STRUCTURED_TEXT_SUFFIXES


def format_bullets(items: list[str]) -> str:
    return "\n".join([f"- {item}" for item in items]) if items else "- 无"


def normalize_doc_root(project_root: Path, doc_root: str | None) -> Path:
    if doc_root:
        candidate = Path(doc_root)
        return candidate if candidate.is_absolute() else (project_root / candidate)
    return project_root / DEFAULT_DOC_DIR


def slugify(relative_path: str) -> str:
    value = relative_path.replace("\\", "/").strip("/")
    return value.replace("/", "__").replace(":", "").replace(".", "_")


def load_index(doc_root: Path) -> tuple[Path, dict]:
    index_path = doc_root / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"在 {index_path} 未找到 index.json。请先初始化文档。")
    return index_path, json.loads(index_path.read_text(encoding="utf-8"))


def collect_sample_entries(target_path: Path, limit: int = 12) -> list[str]:
    if target_path.is_file():
        return [target_path.name]
    entries = sorted(target_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    sample = []
    for entry in entries:
        if entry.name.lower() in IGNORED_ENTRY_NAMES:
            continue
        sample.append(entry.name + ("/" if entry.is_dir() else ""))
        if len(sample) >= limit:
            break
    return sample


def collect_child_names(target_path: Path, limit: int = 12) -> tuple[list[str], list[str]]:
    if target_path.is_file():
        return [], []
    directories = []
    files = []
    for entry in sorted(target_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if entry.name.lower() in IGNORED_ENTRY_NAMES:
            continue
        if entry.is_dir():
            directories.append(entry.name)
        else:
            files.append(entry.name)
    return directories[:limit], files[:limit]


def safe_read_text(path: Path, max_chars: int = 6000) -> str | None:
    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except (OSError, UnicodeDecodeError):
        return None


def find_local_readme(target_path: Path) -> Path | None:
    search_dir = target_path if target_path.is_dir() else target_path.parent
    for name in README_CANDIDATES:
        candidate = search_dir / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def extract_markdown_summary(text: str) -> str | None:
    lines = []
    in_code_block = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not line:
            if lines:
                break
            continue
        if line.startswith("#"):
            continue
        if line.startswith(("-", "*", ">")):
            continue
        lines.append(line)
        if len(" ".join(lines)) >= 160:
            break
    if not lines:
        return None
    summary = " ".join(lines).strip()
    if len(summary) > 180:
        summary = summary[:177].rstrip() + "..."
    return summary or None


def detect_project_traits(project_root: Path | None) -> list[str]:
    if project_root is None:
        return []
    traits = []
    if (project_root / "package.json").exists():
        traits.append("package.json / Node.js 工具链信号")
    if (project_root / "pyproject.toml").exists():
        traits.append("pyproject.toml / Python 工具链信号")
    if (project_root / "Cargo.toml").exists():
        traits.append("Cargo.toml / Rust 工具链信号")
    if (project_root / "go.mod").exists():
        traits.append("go.mod / Go 工具链信号")
    if (project_root / "pom.xml").exists():
        traits.append("pom.xml / Java Maven 工具链信号")
    return traits


def path_display_name(path_text: str, is_dir: bool | None = None) -> str:
    clean = normalize_relpath(path_text)
    if not clean:
        return "/"
    name = clean.split("/")[-1]
    if is_dir is True and not name.endswith("/"):
        return name + "/"
    return name


def natural_join(items: list[str]) -> str:
    cleaned = [item for item in items if item]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} 和 {cleaned[1]}"
    return f"{'、'.join(cleaned[:-1])} 以及 {cleaned[-1]}"


def sibling_modules(project_root: Path | None, target_path: Path) -> list[str]:
    if project_root is None:
        return []
    top_level = []
    for entry in sorted(project_root.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if entry.name.startswith(".") or entry.name.lower() in DEFAULT_OMIT_DIR_NAMES:
            continue
        if entry.resolve() == target_path.resolve():
            continue
        top_level.append(entry.name + ("/" if entry.is_dir() else ""))
    return top_level[:8]


def collect_stack_hints(project_root: Path | None, target_path: Path, project_traits: list[str]) -> list[str]:
    hints = []
    if project_traits:
        hints.append(f"从仓库根级配置看，当前至少暴露出 {natural_join(project_traits)}。")
    if target_path.is_dir():
        local_configs = []
        for child in sorted(target_path.iterdir(), key=lambda item: item.name.lower()):
            if child.is_file() and child.suffix.lower() in STRUCTURED_TEXT_SUFFIXES:
                local_configs.append(child.name)
            if len(local_configs) >= 4:
                break
        if local_configs:
            hints.append(f"这一层可见结构化配置文件：{natural_join([f'`{name}`' for name in local_configs])}。")
    return hints


def generic_path_kind(target_path: Path, readme_summary: str | None, child_dirs: list[str], child_files: list[str]) -> str:
    if target_path.is_file():
        suffix = target_path.suffix.lower()
        if suffix in CODE_SUFFIXES:
            return "code_evidence"
        if suffix in MARKDOWN_SUFFIXES:
            return "doc_evidence"
        if suffix in STRUCTURED_TEXT_SUFFIXES:
            return "config_evidence"
        return "file_evidence"
    if readme_summary and child_files:
        return "topic_directory"
    if child_dirs and child_files:
        return "mixed_directory"
    if child_dirs:
        return "container_directory"
    if child_files:
        return "implementation_directory"
    return "generic_directory"


def collect_context_observations(
    relative_path: str,
    target_path: Path,
    child_dirs: list[str],
    child_files: list[str],
    readme_summary: str | None,
) -> list[str]:
    observations = build_path_evidence(relative_path, target_path)
    if readme_summary:
        observations.append(f"本地 README 摘要：{readme_summary}")
    if child_dirs:
        observations.append(f"当前直接可见的子目录包括 {natural_join([f'`{name}`' for name in child_dirs[:5]])}。")
    if child_files:
        observations.append(f"当前直接可见的文件包括 {natural_join([f'`{name}`' for name in child_files[:5]])}。")
    return observations


def describe_reading_candidate(path: Path, rel_path: str, *, is_root_readme: bool = False) -> tuple[str, list[str], int]:
    score = 0
    reasons = []
    if is_root_readme:
        score += 10
        reasons.append("这里有同层 README，可以先用来建立局部语境。")
    if path.is_dir():
        score += 5
        reasons.append("这是一个子目录，适合作为继续下钻的候选入口。")
    else:
        suffix = path.suffix.lower()
        if suffix in CODE_SUFFIXES:
            score += 6
            reasons.append("这是一个代码文件，可以继续确认真实实现。")
        elif suffix in MARKDOWN_SUFFIXES:
            score += 5
            reasons.append("这是一个说明文档，可以先建立上下文。")
        elif suffix in STRUCTURED_TEXT_SUFFIXES:
            score += 4
            reasons.append("这是一个结构化配置文件，可以帮助确认边界与参数。")
        else:
            score += 2
            reasons.append("这是一个可见文件，仍值得继续核对。")
    if is_low_semantic_risk_path(rel_path):
        score -= 4
        reasons.append("这条路径更像测试或样例材料，优先级应低于主链证据。")
    return ("继续阅读候选", reasons, score)


def collect_entry_candidates(relative_path: str, target_path: Path, readme_path: Path | None) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()

    def add_candidate(path: Path, rel_path: str, *, is_root_readme: bool = False) -> None:
        clean_rel = normalize_relpath(rel_path)
        if not clean_rel or clean_rel in seen:
            return
        seen.add(clean_rel)
        label, reasons, score = describe_reading_candidate(path, clean_rel, is_root_readme=is_root_readme)
        candidates.append(
            {
                "path": clean_rel,
                "name": path.name,
                "label": label,
                "basis": reasons,
                "score": score,
                "is_dir": path.is_dir(),
            }
        )

    if target_path.is_file():
        add_candidate(target_path, relative_path)
    else:
        if readme_path:
            readme_rel = (Path(relative_path) / readme_path.name).as_posix() if relative_path else readme_path.name
            add_candidate(readme_path, readme_rel, is_root_readme=True)
        for child in sorted(target_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            if child.name.lower() in IGNORED_ENTRY_NAMES or child.name.startswith("."):
                continue
            rel_path = (Path(relative_path) / child.name).as_posix() if relative_path else child.name
            add_candidate(child, rel_path)
            if len(candidates) >= 12:
                break

    candidates.sort(key=lambda item: (-item["score"], item["path"]))
    return candidates[:8]


def infer_open_questions(relative_path: str, target_path: Path, readme_summary: str | None) -> list[str]:
    questions = [
        f"`{relative_path}` 在当前 summary 语义里到底代表稳定职责边界，还是暂时的实现组织?",
    ]
    if target_path.is_dir():
        questions.append("这里真正的阅读起点应该是同层 README、局部入口文件，还是某个更深层的专题子目录?")
    else:
        questions.append("这个文件是关键入口、支撑实现，还是只是一条辅助证据?")
    if readme_summary:
        questions.append("本地 README 的表述是否已经落后于当前代码，或者只代表短期实现状态?")
    questions.append("这一层和它的上层功能域之间，边界是稳定的还是仍可能继续拆分?")
    return questions[:5]


def build_context(relative_path: str, target_path: Path, project_root: Path | None = None) -> dict:
    child_dirs, child_files = collect_child_names(target_path)
    readme_path = find_local_readme(target_path)
    readme_summary = collect_readme_summary(target_path)
    project_traits = detect_project_traits(project_root)
    observations = collect_context_observations(relative_path, target_path, child_dirs, child_files, readme_summary)
    entry_candidates = collect_entry_candidates(relative_path, target_path, readme_path)
    path_summary = summarize_path(relative_path, target_path)
    return {
        "relative_path": relative_path,
        "target_path": target_path,
        "path_type": "文件" if target_path.is_file() else "目录",
        "sample_entries": collect_sample_entries(target_path),
        "child_dirs": child_dirs,
        "child_files": child_files,
        "readme_path": readme_path,
        "readme_summary": readme_summary,
        "project_traits": project_traits,
        "kind": generic_path_kind(target_path, readme_summary, child_dirs, child_files),
        "siblings": sibling_modules(project_root, target_path),
        "path_facts": observations,
        "path_summary": path_summary,
        "stack_hints": collect_stack_hints(project_root, target_path, project_traits),
        "entry_candidates": entry_candidates,
        "judgment_prompt": (
            f"请基于 `{relative_path}` 的路径证据、本地 README、子目录/子文件分布、"
            "以及它在上层功能树中的位置，判断它在当前项目里承担什么职责、边界是否稳定、"
            "以及应该从哪里开始阅读。"
        ),
    }


def render_entry_candidate(entry: dict) -> str:
    basis = "；".join(entry.get("basis", []))
    display = f"`{entry['path']}`"
    return f"{display}：{entry['label']}。{basis}"


def context_positioning(context: dict) -> str:
    relative_path = context["relative_path"]
    summary = context.get("path_summary") or summarize_path(relative_path, context["target_path"])
    return (
        f"`{relative_path}`：{summary} "
        "这是一条用于帮助 AI 和维护者继续判断的证据落点，而不是已经被系统锁定的最终职责结论。"
    )


def format_domain_path_entry(context: dict) -> str:
    relative_path = context["relative_path"]
    statement = context_positioning(context)
    prefix = f"`{relative_path}` "
    if statement.startswith(prefix):
        statement = statement[len(prefix):]
    return f"`{relative_path}`：{statement}"


def shared_prefix_parts(paths: list[str]) -> list[str]:
    cleaned = [path.replace("\\", "/").strip("/").split("/") for path in paths if path.replace("\\", "/").strip("/")]
    if not cleaned:
        return []
    if len(cleaned) == 1:
        parts = cleaned[0]
        return parts[:-1]
    prefix: list[str] = []
    for items in zip(*cleaned):
        if len(set(items)) != 1:
            break
        prefix.append(items[0])
    return prefix


def compact_context_entries(contexts: list[dict]) -> tuple[str | None, list[tuple[str, str]]]:
    if not contexts:
        return None, []
    prefix_parts = shared_prefix_parts([context["relative_path"] for context in contexts])
    prefix_text = "/".join(prefix_parts) if prefix_parts else None
    entries = []
    for context in contexts:
        parts = context["relative_path"].replace("\\", "/").strip("/").split("/")
        suffix_parts = parts[len(prefix_parts):] if prefix_parts else parts
        suffix_text = "/".join(suffix_parts) if suffix_parts else parts[-1]
        label = path_display_name(suffix_text, context["target_path"].is_dir())
        entries.append((label, context_positioning(context).replace(f"`{context['relative_path']}` ", "", 1).strip()))
    return prefix_text, entries


def render_compact_context_section(contexts: list[dict]) -> str:
    prefix_text, entries = compact_context_entries(contexts)
    lines: list[str] = []
    if prefix_text:
        lines.extend([f"路径前缀：`{prefix_text}/`", ""])
    lines.extend([f"- `{label}`：{summary}" for label, summary in entries])
    return "\n".join(lines) if lines else "- 暂无路径"


def relative_doc_link(from_doc_rel: str, to_doc_rel: str) -> str:
    from_dir = posixpath.dirname(from_doc_rel)
    return posixpath.relpath(to_doc_rel, start=from_dir or ".")


def relative_source_link(from_doc_rel: str, source_rel: str) -> str:
    from_dir = posixpath.dirname(from_doc_rel)
    clean = source_rel.replace("\\", "/").strip("/")
    return posixpath.relpath(clean, start=from_dir or ".")


def domain_ref_for_doc(target_domain: dict, current_doc_rel: str) -> str:
    target_doc_rel = target_domain.get("doc_path", "")
    if not target_doc_rel or target_doc_rel == current_doc_rel:
        return f"`{target_domain['title']}`"
    return f"[`{target_domain['title']}`](./{relative_doc_link(current_doc_rel, target_doc_rel)})"


def describe_domain_file_role(path: Path) -> str:
    lower_name = path.name.lower()
    suffix = path.suffix.lower()
    if path.is_dir():
        return "继续下钻候选目录"
    if "readme" in lower_name:
        return "说明入口候选"
    if suffix in STRUCTURED_TEXT_SUFFIXES:
        return "配置锚点候选"
    if suffix in MARKDOWN_SUFFIXES:
        return "文档补充候选"
    if is_low_semantic_risk_path(path.as_posix()):
        return "测试或样例候选"
    if suffix in CODE_SUFFIXES:
        return "继续核对的实现文件"
    return "继续核对的关键文件"


def describe_domain_source_label(source_rel: str, domain_id: str) -> str:
    del domain_id
    path = Path(source_rel)
    label = describe_domain_file_role(path)
    if label == "继续核对的关键文件":
        return path_display_name(source_rel, path.suffix == "")
    return label


def source_ref(source_rel: str, current_doc_rel: str, domain_id: str) -> str:
    label = describe_domain_source_label(source_rel, domain_id)
    target = relative_source_link(current_doc_rel, source_rel)
    return f"[`{label}`](./{target})"


def labeled_source_ref(current_doc_rel: str, source_rel: str, label: str) -> str:
    target = relative_source_link(current_doc_rel, source_rel)
    return f"[`{label}`](./{target})"


def render_local_domain_hierarchy(domain: dict, all_domains: list[dict]) -> str:
    current_doc_rel = domain.get("doc_path", "")
    domain_lookup = {item["id"]: item for item in all_domains}
    children_map = domains_by_parent(all_domains)
    parent = domain_lookup.get(domain.get("parent_id"))
    grandparent = domain_lookup.get(parent.get("parent_id")) if parent and parent.get("parent_id") else None
    current_children = children_map.get(domain["id"], [])

    def line(item: dict, *, current: bool = False) -> str:
        suffix = "（当前文档）" if current else ""
        return f"{domain_ref_for_doc(item, current_doc_rel)}：{item['summary']}{suffix}"

    if grandparent and parent:
        lines = [f"- {line(grandparent)}"]
        grandparent_children = children_map.get(grandparent["id"], [])
        for parent_index, parent_sibling in enumerate(grandparent_children):
            parent_is_last = parent_index == len(grandparent_children) - 1
            parent_branch = "└─" if parent_is_last else "├─"
            lines.append(f"  {parent_branch} {line(parent_sibling)}")
            if parent_sibling["id"] != parent["id"]:
                continue
            nested_prefix = "   " if parent_is_last else "│  "
            sibling_domains = children_map.get(parent["id"], [])
            for sibling_index, sibling in enumerate(sibling_domains):
                sibling_is_last = sibling_index == len(sibling_domains) - 1
                sibling_branch = "└─" if sibling_is_last else "├─"
                is_current = sibling["id"] == domain["id"]
                lines.append(f"  {nested_prefix}{sibling_branch} {line(sibling, current=is_current)}")
                if not is_current or not current_children:
                    continue
                child_prefix = "   " if sibling_is_last else "│  "
                for child_index, child in enumerate(current_children):
                    child_is_last = child_index == len(current_children) - 1
                    child_branch = "└─" if child_is_last else "├─"
                    lines.append(f"  {nested_prefix}{child_prefix}{child_branch} {line(child)}")
        return "\n".join(lines)

    if parent:
        lines = [f"- {line(parent)}"]
        sibling_domains = children_map.get(parent["id"], [])
        for sibling_index, sibling in enumerate(sibling_domains):
            sibling_is_last = sibling_index == len(sibling_domains) - 1
            sibling_branch = "└─" if sibling_is_last else "├─"
            is_current = sibling["id"] == domain["id"]
            lines.append(f"  {sibling_branch} {line(sibling, current=is_current)}")
            if not is_current or not current_children:
                continue
            child_prefix = "   " if sibling_is_last else "│  "
            for child_index, child in enumerate(current_children):
                child_is_last = child_index == len(current_children) - 1
                child_branch = "└─" if child_is_last else "├─"
                lines.append(f"  {child_prefix}{child_branch} {line(child)}")
        return "\n".join(lines)

    lines = [f"- {line(domain, current=True)}"]
    for child_index, child in enumerate(current_children):
        child_is_last = child_index == len(current_children) - 1
        child_branch = "└─" if child_is_last else "├─"
        lines.append(f"  {child_branch} {line(child)}")
    return "\n".join(lines)


def score_domain_file(path: Path, domain_id: str) -> int:
    del domain_id
    score = 1
    lower_name = path.name.lower()
    if "readme" in lower_name:
        score += 6
    if is_low_semantic_risk_path(path.as_posix()):
        score -= 5
    if path.suffix.lower() in CODE_SUFFIXES:
        score += 4
    elif path.suffix.lower() in MARKDOWN_SUFFIXES:
        score += 2
    elif path.suffix.lower() in STRUCTURED_TEXT_SUFFIXES:
        score += 2
    score += max(0, 6 - len(path.parts))
    return score


def collect_representative_domain_files(domain: dict, project_root: Path, limit: int = 8) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for rel in domain.get("paths", []):
        target = (project_root / rel).resolve()
        if not target.exists():
            continue
        if target.is_file():
            score = score_domain_file(target, domain["id"])
            candidates.append((score, rel.replace("\\", "/")))
            continue
        for file_path in target.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in REPRESENTATIVE_SCAN_SUFFIXES:
                continue
            try:
                rel_path = file_path.relative_to(project_root).as_posix()
            except ValueError:
                continue
            if rel_path in seen:
                continue
            seen.add(rel_path)
            score = score_domain_file(file_path, domain["id"])
            if score <= 0:
                continue
            candidates.append((score, rel_path))
    ranked = sorted(candidates, key=lambda item: (-item[0], item[1]))
    return [path for _, path in ranked[:limit]]


def aggregate_context_observations(contexts: list[dict], limit: int = 8) -> list[str]:
    observations = []
    for context in contexts:
        observations.append(context_positioning(context))
        observations.extend(context.get("path_facts", [])[:2])
        if len(observations) >= limit:
            break
    deduped = []
    seen = set()
    for item in observations:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
        if len(deduped) >= limit:
            break
    return deduped


def collect_domain_open_questions(domain: dict, contexts: list[dict], child_domains: list[dict]) -> list[str]:
    questions = [
        f"`{domain['title']}` 这一层在用户确认后的 summary 中，究竟代表稳定功能域，还是只是当前实现阶段的临时分组?",
    ]
    if child_domains:
        questions.append("下级专题域的拆分是否真的按职责边界完成，还是只是沿着目录树继续切?")
    elif contexts:
        questions.append("这几个代码落点之间到底谁是主链，谁只是辅助或补充材料?")
    if any(context.get("readme_summary") for context in contexts):
        questions.append("README 里的说法是否只是当前状态描述，还是能代表项目最终希望形成的长期结构?")
    return questions[:5]


def collect_domain_reading_items(domain: dict, contexts: list[dict], child_domains: list[dict], current_doc_rel: str) -> list[str]:
    items = []
    if child_domains:
        for child in child_domains:
            items.append(f"如果问题已经缩小到“{child['summary']}”，继续进入 {domain_ref_for_doc(child, current_doc_rel)}。")
    else:
        for context in contexts[:3]:
            entries = context.get("entry_candidates", [])
            if entries:
                items.append(f"先从 `{entries[0]['path']}` 对应的代码入口开始核对，再沿着相邻目录或调用链继续向下读。")
            else:
                items.append(f"先从 `{context['relative_path']}` 这处代码落点开始，再确认实际入口文件。")
    if not items:
        items.append("当前还缺少稳定阅读顺序，建议先回到 summary 和 structure 重新确认这一层的定位。")
    return items[:6]


def analyze_domain(domain: dict, all_domains: list[dict], project_root: Path) -> dict:
    title = domain["title"]
    current_doc_rel = domain.get("doc_path", "")
    parent = next((item for item in all_domains if item["id"] == domain.get("parent_id")), None)
    child_domains = [item for item in all_domains if item.get("parent_id") == domain["id"]]
    contexts = [build_context(path, (project_root / path).resolve(), project_root) for path in domain.get("paths", []) if (project_root / path).exists()]
    hierarchy_map = render_local_domain_hierarchy(domain, all_domains)
    coverage_list = render_compact_context_section(contexts)
    evidence_items = aggregate_context_observations(contexts)
    analysis = {
        "id": domain["id"],
        "title": title,
        "summary": domain["summary"],
        "level": domain["level"],
        "doc_path": current_doc_rel,
        "parent_id": domain.get("parent_id"),
        "parent_title": parent["title"] if parent else None,
        "has_children": bool(child_domains),
        "hierarchy_map": hierarchy_map,
        "contexts": [
            {
                "path": context["relative_path"],
                "summary": context_positioning(context),
                "observations": context.get("path_facts", [])[:3],
            }
            for context in contexts
        ],
        "coverage_list": coverage_list,
        "evidence_items": evidence_items,
        "reading_items": collect_domain_reading_items(domain, contexts, child_domains, current_doc_rel),
        "open_questions": collect_domain_open_questions(domain, contexts, child_domains),
        "judgment_prompt": domain.get("judgment_prompt"),
        "context_prompts": [context.get("judgment_prompt") for context in contexts if context.get("judgment_prompt")],
    }
    if child_domains:
        analysis["doc_kind"] = "root"
        analysis["implementation_views"] = [
            f"`{path_display_name(context['relative_path'], context['target_path'].is_dir())}`：{context_positioning(context)}"
            for context in contexts
        ]
        analysis["split_views"] = [f"`{child['title']}`：{child['summary']}" for child in child_domains]
        return analysis

    representative_files = collect_representative_domain_files(domain, project_root)
    related_paths = [
        f"{source_ref(context['relative_path'], current_doc_rel, domain['id'])}：{context_positioning(context)}"
        for context in contexts
    ]
    analysis["doc_kind"] = "leaf"
    analysis["evidence_chain"] = [
        f"`{domain['title']}` 当前主要由 {natural_join([f'`{path_display_name(context['relative_path'], context['target_path'].is_dir())}`' for context in contexts[:3]])} 等路径提供证据。"
        if contexts
        else f"`{domain['title']}` 当前缺少稳定的覆盖路径，需要重新扫描或补充结构。"
    ]
    analysis["related_paths"] = related_paths
    analysis["representative_files"] = [
        {
            "path": path,
            "entry": f"{source_ref(path, current_doc_rel, domain['id'])}：{describe_domain_file_role((project_root / path).resolve())}",
        }
        for path in representative_files
    ]
    analysis["entry_candidates"] = [
        render_entry_candidate(item)
        for context in contexts
        for item in context.get("entry_candidates", [])[:3]
    ][:8]
    return analysis


def render_domain_doc_from_analysis(analysis: dict) -> str:
    title = analysis["title"]
    if analysis["doc_kind"] == "root":
        return f"""# 功能域：{title}

## 定位

{analysis['summary']}

## 当前功能层级

{analysis['hierarchy_map']}

## 这一层主要承载什么

{format_bullets(analysis.get('implementation_views', []))}

## 这一层内部怎么分

{format_bullets(analysis.get('split_views', []))}

## 相关实现路径

{analysis.get('coverage_list', '- 暂无路径')}

## 这一层的证据观察

{format_bullets(analysis.get('evidence_items', []))}

## 阅读建议

{format_bullets(analysis.get('reading_items', []))}

## 待确认问题

{format_bullets(analysis.get('open_questions', []))}
"""

    return f"""# 功能域：{title}

## 一句话定位

{analysis['summary']}

## 当前功能层级

{analysis['hierarchy_map']}

## 证据链概览

{format_bullets(analysis.get('evidence_chain', []))}

## 证据观察

{format_bullets(analysis.get('evidence_items', []))}

## 相关实现路径

{format_bullets(analysis.get('related_paths', [])) if analysis.get('related_paths') else '- 暂无路径'}

## 优先核对文件

{format_bullets([item['entry'] for item in analysis.get('representative_files', [])]) if analysis.get('representative_files') else '- 暂无代表性文件'}

## 继续核对的入口

{format_bullets(analysis.get('entry_candidates', [])) if analysis.get('entry_candidates') else '- 暂无可用入口'}

## 待确认问题

{format_bullets(analysis.get('open_questions', []))}
"""


def render_domain_doc(domain: dict, all_domains: list[dict], project_root: Path) -> str:
    return render_domain_doc_from_analysis(analyze_domain(domain, all_domains, project_root))


def render_domain_readme(domain: dict, all_domains: list[dict], project_root: Path) -> str:
    return render_domain_doc(domain, all_domains, project_root)


def doc_link_path(doc_rel: str, *, from_modules_root: bool = False) -> str:
    if not doc_rel:
        return ""
    normalized = Path(doc_rel)
    if from_modules_root:
        try:
            return normalized.relative_to("modules").as_posix()
        except ValueError:
            return normalized.as_posix()
    return normalized.as_posix()


def linked_domain_title(domain: dict, doc_rel: str, *, from_modules_root: bool = False) -> str:
    link_path = doc_link_path(doc_rel, from_modules_root=from_modules_root)
    if not link_path:
        return f"`{domain['title']}`"
    return f"[`{domain['title']}`](./{link_path})"


def render_domain_architecture_map(
    module_docs: dict,
    architecture_domains: list[dict] | None = None,
    *,
    from_modules_root: bool = False,
) -> list[str]:
    architecture_domains = architecture_domains or []
    grouped = domains_by_parent(architecture_domains) if architecture_domains else {}
    level_one_domains = grouped.get(None, [])
    if not level_one_domains:
        return ["- 当前还没有稳定的功能域，请先重新扫描并执行收敛。"]

    lines = []
    for domain in level_one_domains:
        doc_rel = module_docs.get(domain["id"], domain.get("doc_path", ""))
        lines.append(f"- {linked_domain_title(domain, doc_rel, from_modules_root=from_modules_root)}：{domain['summary']}")

        children = grouped.get(domain["id"], [])
        if children:
            for index, child in enumerate(children):
                child_doc_rel = module_docs.get(child["id"], child.get("doc_path", ""))
                branch = "└─" if index == len(children) - 1 else "├─"
                child_title = linked_domain_title(child, child_doc_rel, from_modules_root=from_modules_root)
                lines.append(f"  {branch} {child_title}：{child['summary']}")
        else:
            lines.append("  └─ 当前没有单独拆出的第二层专题域，直接进入这一层 README。")

        lines.append("")

    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def update_modules_readme(doc_root: Path, module_docs: dict, architecture_domains: list[dict] | None = None) -> None:
    architecture_domains = architecture_domains or []
    architecture_lines = render_domain_architecture_map(
        module_docs,
        architecture_domains,
        from_modules_root=True,
    )
    lines = [
        "# 模块文档",
        "",
        "这里按项目的功能树列出第一层功能域，以及已经单独拆出的下级功能域。",
        "",
        "## 当前功能架构",
        "",
    ]
    lines.extend(architecture_lines)
    (doc_root / "modules" / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_domain_target(target: str, architecture_domains: list[dict], project_root: Path) -> tuple[dict, str]:
    cleaned = target.replace("\\", "/").strip("/")
    domain_lookup = {domain["id"]: domain for domain in architecture_domains}
    if cleaned in domain_lookup:
        return domain_lookup[cleaned], "domain_id"

    matches: list[tuple[int, int, dict]] = []
    for domain in architecture_domains:
        for domain_path in domain.get("paths", []):
            normalized_path = domain_path.replace("\\", "/").strip("/")
            if not normalized_path:
                continue
            if cleaned == normalized_path or cleaned.startswith(normalized_path + "/"):
                matches.append((normalized_path.count("/"), int(domain.get("level", 1)), domain))
            elif normalized_path.startswith(cleaned + "/"):
                matches.append((normalized_path.count("/"), int(domain.get("level", 1)), domain))
    if matches:
        matches.sort(key=lambda item: (item[0], item[1], item[2]["id"]), reverse=True)
        return matches[0][2], "path_resolved"

    candidate_path = (project_root / cleaned).resolve()
    if candidate_path.exists():
        raise FileNotFoundError(
            f"目标 `{cleaned}` 当前存在，但还没有映射到稳定功能域。"
            "请先重新扫描功能树，或改为传入明确的功能域 ID。"
        )
    raise FileNotFoundError(f"未找到功能域或路径：{cleaned}")


def main() -> int:
    parser = argparse.ArgumentParser(description="为功能域创建模块文档。")
    parser.add_argument("--project-root", required=True, help="仓库根目录。")
    parser.add_argument("--doc-root", help="文档根目录。默认使用 <project-root>/project-docs。")
    parser.add_argument(
        "--target",
        action="append",
        required=True,
        help="需要生成文档的功能域 ID。兼容传入路径，但路径会先解析到最接近的功能域。",
    )
    parser.add_argument("--force", action="store_true", help="如果模块文档已存在，则强制重写。")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    doc_root = normalize_doc_root(project_root, args.doc_root).resolve()
    index_path, index_payload = load_index(doc_root)
    ensure_workflow_state(index_payload)

    if not summary_is_confirmed(index_payload):
        print(f"[阻止] {summary_gate_message(index_payload)}")
        print("[下一步] 请先让 `overview/project-summary.md` 成为可继续的项目基线。")
        return 0
    if not structure_is_aligned(index_payload):
        print(f"[阻止] {structure_gate_message(index_payload)}")
        print("[下一步] 请先建立并对齐功能树与代码树映射文档 `overview/project-structure.md`。")
        return 0

    index_payload["skill_name"] = SKILL_NAME
    index_payload["skill_version"] = SKILL_VERSION
    index_payload["doc_schema_version"] = DOC_SCHEMA_VERSION
    mark_modules_drafted(index_payload)
    module_docs = dict(index_payload.get("module_docs", {}))
    generated_docs = set(index_payload.get("generated_docs", []))
    architecture_domains = list(index_payload.get("architecture_domains", []))
    if not architecture_domains:
        raise RuntimeError("当前索引中还没有稳定功能域。请先运行 `scan_project_tree.py` 建立功能树与代码映射。")

    created = []
    resolved_messages = []
    selected_domains: dict[str, dict] = {}

    for target in args.target:
        domain, resolved_by = resolve_domain_target(target, architecture_domains, project_root)
        selected_domains[domain["id"]] = domain
        doc_rel = domain.get("doc_path") or f"modules/{slugify(domain['id'])}.md"
        doc_path = doc_root / doc_rel
        if not doc_path.exists() or args.force:
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(render_domain_doc(domain, architecture_domains, project_root), encoding="utf-8")
            created.append(doc_rel)
        module_docs[domain["id"]] = doc_rel
        generated_docs.add(doc_rel)
        if resolved_by != "domain_id":
            resolved_messages.append(f"`{target}` -> `{domain['title']}`")

    index_payload["module_docs"] = dict(sorted(module_docs.items()))
    index_payload["generated_docs"] = sorted(generated_docs)
    tracked_paths = set(index_payload.get("tracked_paths", []))
    for domain in selected_domains.values():
        tracked_paths.update(domain.get("paths", []))
    index_payload["tracked_paths"] = sorted(tracked_paths)
    git_snapshot = capture_git_snapshot(project_root)
    mark_modules_aligned(index_payload, git_snapshot)
    index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot, align_to_current=True)
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    update_modules_readme(doc_root, module_docs, architecture_domains)

    if created:
        print(f"[完成] 已创建模块文档：{', '.join(created)}")
    else:
        print("[跳过] 没有模块文档被重写。")
    if resolved_messages:
        print(f"[提示] 路径输入已解析到功能域：{'; '.join(resolved_messages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
