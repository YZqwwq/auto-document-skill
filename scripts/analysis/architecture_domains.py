#!/usr/bin/env python3
"""
基于真实目录结构收集功能责任候选信号。

当前版本不再把少数固定路径名直接翻译成既定功能桶，
而是优先输出“来自真实路径的候选功能域 + 证据”。
"""

from __future__ import annotations

from pathlib import Path

from core.path_intelligence import (
    CODE_SUFFIXES,
    DEFAULT_OMIT_DIR_NAMES,
    build_path_evidence,
    collect_readme_summary,
    collect_sample_entries,
    count_meaningful_children,
    infer_title_from_path,
    is_root_context_signal_path,
    normalize_relpath,
    score_root_entry,
    summarize_path,
)


SECOND_LEVEL_OMIT_NAMES = {
    "test",
    "tests",
    "__tests__",
    "mock",
    "mocks",
    "fixture",
    "fixtures",
    "example",
    "examples",
}


def slugify(value: str) -> str:
    return normalize_relpath(value).replace("/", "__").replace(":", "").replace(".", "_")


def visible_entries(path: Path) -> list[Path]:
    return [
        child
        for child in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        if not child.name.startswith(".") and child.name.lower() not in DEFAULT_OMIT_DIR_NAMES
    ]


def topic_score(path: Path) -> int:
    if path.is_file():
        return score_root_entry(path)
    dir_count, file_count = count_meaningful_children(path, max_scan=160)
    score = 10 + min(20, dir_count * 2) + min(20, file_count)
    if collect_readme_summary(path):
        score += 8
    if len(collect_sample_entries(path, limit=6)) >= 3:
        score += 5
    return score


def is_meaningful_topic_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    lower_name = path.name.lower()
    if lower_name in DEFAULT_OMIT_DIR_NAMES or lower_name in SECOND_LEVEL_OMIT_NAMES:
        return False
    dir_count, file_count = count_meaningful_children(path, max_scan=120)
    return bool(dir_count or file_count or collect_readme_summary(path))


def collapse_single_container(path: Path, *, max_steps: int = 2) -> Path:
    current = path
    for _ in range(max_steps):
        if not current.is_dir():
            break
        children = [child for child in visible_entries(current) if child.is_dir()]
        dir_count, file_count = count_meaningful_children(current, max_scan=80)
        meaningful_children = [child for child in children if is_meaningful_topic_dir(child)]
        if file_count > 3 or len(meaningful_children) != 1:
            break
        current = meaningful_children[0]
    return current


def discover_level_one_paths(project_root: Path, max_items: int = 8) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for entry in visible_entries(project_root):
        if entry.name.lower() in DEFAULT_OMIT_DIR_NAMES:
            continue
        if entry.is_file() and is_root_context_signal_path(entry.name):
            continue
        if entry.is_file() and entry.suffix.lower() not in CODE_SUFFIXES:
            continue
        candidate = collapse_single_container(entry) if entry.is_dir() else entry
        rel_path = candidate.relative_to(project_root).as_posix()
        if rel_path in seen:
            continue
        seen.add(rel_path)
        score = score_root_entry(entry) + topic_score(candidate)
        candidates.append((score, rel_path))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in candidates[:max_items]]


def discover_child_topic_paths(project_root: Path, parent_domain: dict, max_children: int = 6) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for rel in parent_domain.get("paths", []):
        target = (project_root / rel).resolve()
        if not target.exists() or not target.is_dir():
            continue
        roots = [collapse_single_container(target)]
        for root in roots:
            for child in visible_entries(root):
                if not is_meaningful_topic_dir(child):
                    continue
                candidate = collapse_single_container(child)
                rel_path = candidate.relative_to(project_root).as_posix()
                if rel_path in seen:
                    continue
                seen.add(rel_path)
                candidates.append((topic_score(candidate), rel_path))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in candidates[:max_children]]


def build_domain(project_root: Path, relative_path: str, *, level: int, parent_id: str | None) -> dict:
    clean = normalize_relpath(relative_path)
    target = (project_root / clean).resolve()
    evidence = build_path_evidence(clean, target)
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
            f"`{clean}` 是否已经构成稳定功能边界，而不只是目录组织",
            f"`{clean}` 与它的上层和同层路径之间是什么协作关系",
        ],
        "signal_type": "path_evidence",
        "signal_strength": "high" if len(evidence) >= 4 else "medium",
        "signal_basis": evidence,
        "judgment_prompt": (
            f"请基于这些路径证据判断 `{clean}` 是否应该被视为一个稳定的功能域，"
            f"以及它在当前项目里更像顶层能力、下级专题，还是只是暂时的目录组织。"
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
