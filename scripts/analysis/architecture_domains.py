#!/usr/bin/env python3
"""
基于真实目录结构收集功能责任候选信号。

当前版本不再把路径名直接翻译成固定功能桶，
也尽量避免靠少量硬编码词表直接排除候选；
这里更偏向：

- 收集真实路径事实
- 生成弱提示
- 为后续 AI 判断保留候选功能域与证据
"""

from __future__ import annotations

from pathlib import Path

from core.path_intelligence import (
    DEFAULT_OMIT_DIR_NAMES,
    build_path_evidence,
    build_weak_path_hints,
    collect_path_facts,
    infer_title_from_path,
    is_root_context_signal_path,
    normalize_relpath,
    score_root_entry,
    summarize_path,
)


def slugify(value: str) -> str:
    return normalize_relpath(value).replace("/", "__").replace(":", "").replace(".", "_")


def relative_to_project(project_root: Path, path: Path) -> str:
    root = project_root.resolve()
    target = path.resolve()
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return normalize_relpath(path.as_posix())


def visible_entries(path: Path) -> list[Path]:
    return [
        child
        for child in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        if not child.name.startswith(".") and child.name.lower() not in DEFAULT_OMIT_DIR_NAMES
    ]


def candidate_priority(project_root: Path, path: Path) -> int:
    rel_path = relative_to_project(project_root, path)
    facts = collect_path_facts(rel_path, path)
    priority = score_root_entry(path)
    if path.is_dir():
        priority += min(8, len(facts.get("sample_entries", [])))
    if facts.get("readme_summary"):
        priority += 6
    if facts.get("is_root_level") and facts.get("root_text_like"):
        priority -= 10
    if facts.get("is_root_level") and facts.get("root_structured_config_like"):
        priority -= 8
    if facts.get("low_signal_name_hint") or facts.get("low_signal_suffix_hint"):
        priority -= 3
    return max(priority, 0)


def path_can_anchor_domain(project_root: Path, path: Path) -> bool:
    rel_path = relative_to_project(project_root, path)
    facts = collect_path_facts(rel_path, path)
    if path.name.lower().startswith("readme"):
        return False
    if facts["path_type"] == "directory":
        return True
    if facts["is_root_level"] and (facts["root_text_like"] or facts["root_structured_config_like"]):
        return False
    if facts["looks_like_text"] and not facts["looks_like_code"]:
        return False
    return True


def collapse_single_container(path: Path, project_root: Path, *, max_steps: int = 2) -> Path:
    current = path
    for _ in range(max_steps):
        if not current.is_dir():
            break
        children = [child for child in visible_entries(current) if path_can_anchor_domain(project_root, child)]
        child_dirs = [child for child in children if child.is_dir()]
        if len(child_dirs) != 1:
            break
        rel_path = relative_to_project(project_root, current)
        facts = collect_path_facts(rel_path, current, max_scan=120)
        if facts["file_count"] > 1:
            break
        if len(children) > 2:
            break
        current = child_dirs[0]
    return current


def discover_level_one_paths(project_root: Path, max_items: int = 8) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for entry in visible_entries(project_root):
        if not path_can_anchor_domain(project_root, entry):
            continue
        if entry.is_file() and is_root_context_signal_path(entry.name):
            continue
        candidate = collapse_single_container(entry, project_root) if entry.is_dir() else entry
        rel_path = relative_to_project(project_root, candidate)
        if rel_path in seen:
            continue
        seen.add(rel_path)
        candidates.append((candidate_priority(project_root, candidate), rel_path))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in candidates[:max_items]]


def discover_child_topic_paths(project_root: Path, parent_domain: dict, max_children: int = 6) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for rel in parent_domain.get("paths", []):
        target = (project_root / rel).resolve()
        if not target.exists() or not target.is_dir():
            continue
        root = collapse_single_container(target, project_root)
        for child in visible_entries(root):
            if not path_can_anchor_domain(project_root, child):
                continue
            candidate = collapse_single_container(child, project_root) if child.is_dir() else child
            rel_path = relative_to_project(project_root, candidate)
            if rel_path in seen:
                continue
            seen.add(rel_path)
            candidates.append((candidate_priority(project_root, candidate), rel_path))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in candidates[:max_children]]


def build_domain(project_root: Path, relative_path: str, *, level: int, parent_id: str | None) -> dict:
    clean = normalize_relpath(relative_path)
    target = (project_root / clean).resolve()
    facts = collect_path_facts(clean, target)
    evidence = build_path_evidence(clean, target)
    weak_hints = build_weak_path_hints(clean, target, facts)
    title = infer_title_from_path(clean)
    return {
        "id": slugify(clean),
        "title": title,
        "level": level,
        "parent_id": parent_id,
        "always_directory": target.is_dir(),
        "summary": summarize_path(clean, target),
        "functional_role": "top_level_candidate" if level == 1 else "child_candidate",
        "question_hints": [
            f"`{clean}` 在当前项目里实际承担什么职责",
            f"`{clean}` 是否已经构成稳定功能边界，而不只是路径组织",
            f"`{clean}` 与它的上层和同层路径之间是什么协作关系",
        ],
        "signal_type": "path_evidence",
        "signal_strength": "high" if len(evidence) >= 4 else "medium",
        "signal_basis": evidence,
        "weak_hints": weak_hints,
        "path_facts": {
            "path_type": facts["path_type"],
            "path_depth": facts["path_depth"],
            "dir_count": facts["dir_count"],
            "file_count": facts["file_count"],
            "sample_entries": facts["sample_entries"][:6],
            "readme_summary": facts["readme_summary"],
            "low_signal_name_hint": facts["low_signal_name_hint"],
            "low_signal_suffix_hint": facts["low_signal_suffix_hint"],
        },
        "judgment_prompt": (
            f"请基于 `{clean}` 的真实路径事实、可见子项、同层 README、弱提示和上层层级关系，"
            f"判断它是否应该被视为一个稳定的功能域；如果是，它更像顶层能力、下级专题，"
            f"还是只是当前实现阶段的临时组织。"
        ),
        "candidate": True,
        "paths": [clean],
    }


def build_dynamic_domains(project_root: Path, parent_domain: dict, *, max_depth: int = 3) -> list[dict]:
    if parent_domain.get("level", 1) >= max_depth:
        return []
    level = int(parent_domain.get("level", 1)) + 1
    rel_paths = discover_child_topic_paths(project_root, parent_domain)
    return [build_domain(project_root, rel_path, level=level, parent_id=parent_domain["id"]) for rel_path in rel_paths]


def domain_chain(domain: dict, domain_lookup: dict[str, dict]) -> list[str]:
    chain = [slugify(domain["id"])]
    current = domain
    while current.get("parent_id"):
        parent = domain_lookup.get(current["parent_id"])
        if not parent:
            break
        chain.append(slugify(parent["id"]))
        current = parent
    chain.reverse()
    return chain


def assign_doc_paths(domains: list[dict]) -> list[dict]:
    domain_lookup = {domain["id"]: domain for domain in domains}
    children_map: dict[str, list[dict]] = {}
    for domain in domains:
        parent_id = domain.get("parent_id")
        if parent_id:
            children_map.setdefault(parent_id, []).append(domain)

    assigned = []
    for domain in domains:
        chain = domain_chain(domain, domain_lookup)
        has_children = bool(children_map.get(domain["id"]))
        if domain.get("level") == 1 or has_children or domain.get("always_directory"):
            doc_path = "/".join(["modules", *chain, "README.md"])
        else:
            parent_chain = chain[:-1]
            doc_path = "/".join(["modules", *parent_chain, f"{chain[-1]}.md"])
        updated = dict(domain)
        updated["doc_path"] = doc_path
        assigned.append(updated)
    return assigned


def infer_architecture_signals(project_root: Path) -> list[dict]:
    level_one_domains = [build_domain(project_root, rel_path, level=1, parent_id=None) for rel_path in discover_level_one_paths(project_root)]

    dynamic_domains = []
    frontier = list(level_one_domains)
    visited = set()
    while frontier:
        parent = frontier.pop(0)
        if parent["id"] in visited:
            continue
        visited.add(parent["id"])
        children = build_dynamic_domains(project_root, parent, max_depth=3)
        dynamic_domains.extend(children)
        frontier.extend(children)

    domains = assign_doc_paths(level_one_domains + dynamic_domains)
    domains.sort(key=lambda item: (item["level"], item["title"], item["id"]))
    return domains


def infer_architecture_domains(project_root: Path) -> list[dict]:
    return infer_architecture_signals(project_root)


def recommended_domain_ids(domains: list[dict]) -> list[str]:
    return [domain["id"] for domain in sorted(domains, key=lambda item: (item["level"], item["title"], item["id"]))]


def domains_by_parent(domains: list[dict]) -> dict[str | None, list[dict]]:
    grouped: dict[str | None, list[dict]] = {}
    for domain in domains:
        grouped.setdefault(domain.get("parent_id"), []).append(domain)
    for items in grouped.values():
        items.sort(key=lambda item: (item["level"], item["title"], item["id"]))
    return grouped


def tracked_top_level_paths(domains: list[dict]) -> list[str]:
    paths = []
    seen = set()
    for domain in domains:
        for rel in domain.get("paths", []):
            top = rel.split("/", 1)[0]
            if top not in seen:
                paths.append(top)
                seen.add(top)
    return paths
