#!/usr/bin/env python3
"""
全仓证据扫描与顶层功能域推断协议生成器。

这份文件不负责在脚本内部完成“真正的语义判断”，而是负责两件事：

- 扫描仓库里可见的顶层证据分区与支持性路径
- 生成一份供当前会话中的 Codex 使用的推断协议

也就是说，这里输出的是：

- repository evidence package
- top-level domain inference protocol
- protocol-based placeholder domains

而不是：

- 脚本自行完成的功能域树推断结果

如果最终需要得到稳定的功能域树，应由当前会话中的 Codex 按 summary、
全仓证据和约定 schema 完成语义归纳；这里的 placeholder 只是一层
为了维持现有文档链路而保留的占位结构。
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from scripts.shared.path_intelligence import (
    DEFAULT_OMIT_DIR_NAMES,
    build_path_evidence,
    build_weak_path_hints,
    collect_path_facts,
    infer_title_from_path,
    normalize_relpath,
)

TOP_LEVEL_DOMAIN_PROTOCOL_SCHEMA_VERSION = "1.0"


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


def natural_join(items: list[str]) -> str:
    cleaned = [item for item in items if item]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} 和 {cleaned[1]}"
    return f"{'、'.join(cleaned[:-1])} 以及 {cleaned[-1]}"


def collect_entry_evidence(project_root: Path, path: Path) -> dict:
    relative_path = relative_to_project(project_root, path)
    facts = collect_path_facts(relative_path, path)
    return {
        "relative_path": relative_path,
        "title": infer_title_from_path(relative_path),
        "path_type": facts["path_type"],
        "path_depth": facts["path_depth"],
        "always_directory": path.is_dir(),
        "signal_basis": build_path_evidence(relative_path, path)[:4],
        "weak_hints": build_weak_path_hints(relative_path, path, facts)[:3],
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
    }


def collect_supporting_evidence(
    project_root: Path,
    root_entry: Path,
    *,
    max_depth: int = 3,
    max_items: int = 40,
) -> list[dict]:
    if not root_entry.is_dir():
        return []

    items: list[dict] = []
    queue: deque[tuple[Path, int]] = deque((child, 1) for child in visible_entries(root_entry))
    seen: set[str] = set()
    while queue and len(items) < max_items:
        current, depth = queue.popleft()
        relative_path = relative_to_project(project_root, current)
        if relative_path in seen:
            continue
        seen.add(relative_path)
        items.append(collect_entry_evidence(project_root, current))
        if current.is_dir() and depth < max_depth:
            for child in visible_entries(current):
                queue.append((child, depth + 1))
    return items


def collect_repository_evidence(
    project_root: Path,
    *,
    max_depth: int = 3,
    max_items_per_root: int = 40,
) -> dict:
    top_level_entries = visible_entries(project_root)
    top_level: list[dict] = []
    path_lookup: dict[str, dict] = {}
    supporting_by_root: dict[str, list[dict]] = {}

    for entry in top_level_entries:
        evidence = collect_entry_evidence(project_root, entry)
        relative_path = evidence["relative_path"]
        top_level.append(evidence)
        path_lookup[relative_path] = evidence
        supporting = collect_supporting_evidence(
            project_root,
            entry,
            max_depth=max_depth,
            max_items=max_items_per_root,
        )
        supporting_by_root[relative_path] = supporting
        for item in supporting:
            path_lookup.setdefault(item["relative_path"], item)

    return {
        "top_level": top_level,
        "top_level_paths": [item["relative_path"] for item in top_level],
        "supporting_by_root": supporting_by_root,
        "path_lookup": path_lookup,
    }


def compact_inference_evidence(items: list[dict], *, limit: int = 8) -> list[dict]:
    compact = []
    for item in items[:limit]:
        compact.append(
            {
                "relative_path": item["relative_path"],
                "title": item["title"],
                "path_type": item["path_type"],
                "path_depth": item["path_depth"],
                "always_directory": item.get("always_directory", False),
                "signal_basis": item.get("signal_basis", [])[:2],
                "weak_hints": item.get("weak_hints", [])[:2],
                "path_facts": dict(item.get("path_facts", {})),
            }
        )
    return compact


def build_top_level_domain_protocol_output_schema() -> dict:
    return {
        "schema_version": TOP_LEVEL_DOMAIN_PROTOCOL_SCHEMA_VERSION,
        "scope": "top_level_domain_tree_draft",
        "description": "当前会话中的 Codex 基于已确认 summary 与全仓证据整理出的第一层功能域树草案。",
        "draft_status": "top_level_domain_tree_draft 的当前状态，如 pending_codex_judgment / codex_drafted / placeholder_only。",
        "top_level_domains": [
            {
                "id": "稳定的功能域 ID，建议由 title 归一化生成",
                "title": "功能域名称",
                "problem_statement": "这个功能域解决什么问题",
                "system_role": "它在整个系统中的职责是什么",
                "domain_value": "它在系统中的价值",
                "evidence_paths": ["支撑这个功能域判断的关键路径"],
                "source_seed_paths": ["内部映射字段：这个功能域主要来自哪些顶层证据分区"],
                "boundary_notes": "它与其他顶层功能域如何区分",
                "child_domain_hints": ["后续可继续下钻的下级功能方向"],
                "open_questions": ["当前仍待确认的问题"],
            }
        ],
        "cross_domain_notes": [
            "用于描述多个顶层功能域之间的协作关系、边界衔接或共享前提。"
        ],
        "global_open_questions": [
            "当前影响整棵顶层功能域树稳定性的全局待确认问题。"
        ],
    }


def build_top_level_domain_protocol_prompt(summary_text: str | None, top_level_groups: list[dict]) -> str:
    summary_reference = "已确认的 summary 正文" if summary_text else "后续补充的 summary 基线"
    seed_paths = natural_join([f"`{item['seed_path']}`" for item in top_level_groups[:6]])
    return (
        f"请当前会话中的 Codex 以 {summary_reference} 为主线，不要先按文件名或目录名直接分桶，"
        "也不要把顶层路径直接当成功能域答案。"
        f"请先通读 summary，再综合顶层证据入口 {seed_paths or '及其支持性路径'} 的实际内容、职责、调用关系、"
        "配置语义和模块协作关系，整理第一层功能域树草案。输出时必须遵循约定的 top_level_domain_tree_draft schema。"
    )


def build_top_level_domain_inference_protocol(
    project_root: Path,
    repository_evidence: dict,
    *,
    summary_text: str | None,
) -> dict:
    top_level_groups = []
    for seed_path in repository_evidence["top_level_paths"]:
        seed_evidence = repository_evidence["path_lookup"][seed_path]
        supporting_evidence = repository_evidence["supporting_by_root"].get(seed_path, [])
        top_level_groups.append(
            {
                "seed_path": seed_path,
                "seed_title": seed_evidence["title"],
                "seed_evidence": compact_inference_evidence([seed_evidence], limit=1)[0],
                "supporting_evidence": compact_inference_evidence(supporting_evidence, limit=12),
                "supporting_paths": [item["relative_path"] for item in supporting_evidence[:12]],
            }
        )
    output_schema = build_top_level_domain_protocol_output_schema()
    return {
        "scope": "top_level_domain_inference_protocol",
        "schema_version": TOP_LEVEL_DOMAIN_PROTOCOL_SCHEMA_VERSION,
        "project_root": str(project_root),
        "protocol_status": "ready_for_codex" if top_level_groups else "empty_repository_evidence",
        "summary_input_state": "provided" if summary_text else "missing",
        "summary_text": summary_text or "",
        "top_level_groups": top_level_groups,
        "requested_output_schema": output_schema,
        "codex_task_prompt": build_top_level_domain_protocol_prompt(summary_text, top_level_groups),
    }


def collect_group_evidence_paths(group: dict, *, limit: int = 8) -> list[str]:
    seed_path = group["seed_path"]
    supporting_paths = [item["relative_path"] for item in group.get("supporting_evidence", [])[: max(limit - 1, 0)]]
    return list(dict.fromkeys([seed_path, *supporting_paths]))


def build_placeholder_domain_value(seed_title: str, supporting_paths: list[str]) -> str:
    if supporting_paths:
        return f"先把 `{seed_title}` 相关的实现与说明材料收拢到同一层，方便当前会话中的 Codex 继续判断真实功能边界。"
    return f"先把 `{seed_title}` 作为顶层证据入口保留下来，等待当前会话中的 Codex 结合 summary 判断其真实职责。"


def build_placeholder_boundary_notes(seed_path: str, supporting_paths: list[str]) -> str:
    if supporting_paths:
        return (
            f"当前只把 `{seed_path}` 当作主要证据入口，并结合同分区下的支持性路径理解它的覆盖范围；"
            "这还不是最终功能边界，仍需由当前会话中的 Codex 结合内容确认。"
        )
    return f"当前主要依赖 `{seed_path}` 这一顶层证据入口，边界仍待当前会话中的 Codex 进一步确认。"


def build_top_level_domain_draft_from_protocol(protocol: dict) -> dict:
    top_level_domains = []
    for group in protocol.get("top_level_groups", []):
        seed_path = group["seed_path"]
        seed_title = group["seed_title"]
        supporting_paths = list(group.get("supporting_paths", []))
        evidence_paths = collect_group_evidence_paths(group, limit=8)
        top_level_domains.append(
            {
                "id": slugify(seed_path),
                "title": seed_title,
                "problem_statement": (
                    f"当前应结合 `{seed_path}` 及其支持性路径，判断 `{seed_title}` 这一层到底在解决什么问题。"
                ),
                "system_role": (
                    f"`{seed_title}` 当前只被视为顶层证据分区之一，后续应由当前会话中的 Codex 在已确认 summary 约束下归纳它在系统中的职责。"
                ),
                "domain_value": build_placeholder_domain_value(seed_title, supporting_paths),
                "evidence_paths": evidence_paths,
                "source_seed_paths": [seed_path],
                "boundary_notes": build_placeholder_boundary_notes(seed_path, supporting_paths),
                "child_domain_hints": [
                    "可以继续基于支持性路径里的子目录、入口文件和 README，交给当前会话中的 Codex 继续拆出下级功能。",
                ],
                "open_questions": [
                    "这组证据是否真的构成单一稳定功能域，而不是路径邻近形成的证据分区。",
                ],
            }
        )
    return {
        "schema_version": TOP_LEVEL_DOMAIN_PROTOCOL_SCHEMA_VERSION,
        "scope": "top_level_domain_tree_draft",
        "summary_input_state": protocol.get("summary_input_state", "missing"),
        "protocol_status": protocol.get("protocol_status", "ready_for_codex"),
        "draft_status": "placeholder_only",
        "top_level_domains": top_level_domains,
        "cross_domain_notes": [
            "当前顶层功能域树草案仍只是基于全仓证据分区整理出的占位结果，真正的跨域边界应由当前会话中的 Codex 继续校准。"
        ],
        "global_open_questions": [
            "顶层功能域之间是否已经按稳定职责划分，仍需结合 summary 与代码内容继续确认。"
        ],
    }


def build_domain_placeholder_summary(
    seed_evidence: dict,
    supporting_evidence: list[dict],
    *,
    summary_text: str | None,
) -> str:
    seed_path = seed_evidence["relative_path"]
    support_count = len(supporting_evidence)
    if summary_text:
        return (
            f"当前以 `{seed_path}` 为主要证据入口，并结合 {support_count} 条相关路径，"
            "作为一份待当前会话中的 Codex 结合已确认 summary 判断的顶层功能域占位草案。"
        )
    return (
        f"当前以 `{seed_path}` 为主要证据入口，并结合 {support_count} 条相关路径，"
        "作为一份待当前会话中的 Codex 继续判断的顶层功能域占位草案。"
    )


def build_domain_placeholder_prompt(
    seed_evidence: dict,
    supporting_evidence: list[dict],
    *,
    summary_text: str | None,
    output_schema: dict | None = None,
) -> str:
    seed_path = seed_evidence["relative_path"]
    supporting_paths = [f"`{item['relative_path']}`" for item in supporting_evidence[:6]]
    summary_reference = "已确认的 summary" if summary_text else "后续提供的 summary 基线"
    supporting_text = natural_join(supporting_paths) if supporting_paths else "当前分区下的代码与说明材料"
    schema_note = ""
    if output_schema:
        schema_note = (
            " 输出时应对齐 top_level_domain_tree_draft schema，至少明确 title、problem_statement、"
            "system_role、domain_value、evidence_paths、boundary_notes、child_domain_hints 和 open_questions。"
        )
    return (
        f"请当前会话中的 Codex 以 {summary_reference} 为主线，综合顶层证据入口 `{seed_path}` 以及 "
        f"{supporting_text} 的实际内容、职责、调用关系、配置语义和模块协作关系，"
        "判断这一组证据是否应被归纳成一个稳定功能域；如果应当成立，再决定它的职责、边界和下级功能树。"
        f"{schema_note}"
    )


def build_domain_placeholder(
    drafted_domain: dict,
    seed_group: dict,
    *,
    related_seed_groups: list[dict] | None = None,
    level: int,
    parent_id: str | None,
    summary_text: str | None = None,
    output_schema: dict | None = None,
) -> dict:
    related_seed_groups = related_seed_groups or [seed_group]
    seed_path = seed_group["seed_path"]
    seed_evidence = seed_group["seed_evidence"]
    supporting_evidence = []
    seen_supporting_paths = set()
    source_seed_paths = []
    for group in related_seed_groups:
        source_seed_paths.append(group["seed_path"])
        for item in group.get("supporting_evidence", []):
            if item["relative_path"] not in seen_supporting_paths:
                supporting_evidence.append(item)
                seen_supporting_paths.add(item["relative_path"])
    referenced_paths = list(
        dict.fromkeys(
            drafted_domain.get("evidence_paths", [])
            or [path for group in related_seed_groups for path in collect_group_evidence_paths(group, limit=9)]
        )
    )
    signal_basis = list(seed_evidence.get("signal_basis", []))
    if len(source_seed_paths) > 1:
        signal_basis.append(
            "当前顶层功能域同时参考了 "
            + natural_join([f"`{path}`" for path in source_seed_paths[:4]])
            + "。"
        )
    if supporting_evidence:
        signal_basis.append(
            "支持性路径包括 "
            + natural_join([f"`{item['relative_path']}`" for item in supporting_evidence[:4]])
            + "。"
        )
    weak_hints = list(seed_evidence.get("weak_hints", []))
    if summary_text:
        weak_hints.append("当前应优先以已确认的 summary 解释这组路径的共同职责。")
    else:
        weak_hints.append("当前缺少 summary 输入，这个占位域只代表宽松的顶层证据分区。")
    return {
        "id": drafted_domain.get("id") or slugify(seed_path),
        "title": drafted_domain.get("title") or seed_evidence["title"],
        "level": level,
        "parent_id": parent_id,
        "always_directory": seed_evidence["always_directory"],
        "summary": drafted_domain.get("problem_statement")
        or build_domain_placeholder_summary(seed_evidence, supporting_evidence, summary_text=summary_text),
        "functional_role": "top_level_domain_placeholder",
        "question_hints": list(drafted_domain.get("open_questions", []))[:4]
        or [
            f"这组路径在当前 summary 下是否共同服务于同一个稳定职责",
            f"`{seed_path}` 是功能域边界、实现入口，还是只是证据入口",
            "如果它构成功能域，最合理的下级功能树应该如何继续展开",
        ],
        "signal_type": "full_repo_evidence_protocol",
        "signal_strength": drafted_domain.get("draft_status", "placeholder_only"),
        "signal_basis": signal_basis[:6],
        "weak_hints": weak_hints[:4],
        "path_facts": dict(seed_evidence.get("path_facts", {})),
        "judgment_prompt": build_domain_placeholder_prompt(
            seed_evidence,
            supporting_evidence,
            summary_text=summary_text,
            output_schema=output_schema,
        ),
        "candidate": False,
        "inference_mode": "codex_guided_protocol",
        "inference_status": drafted_domain.get("draft_status", "pending_codex_judgment"),
        "protocol_status": drafted_domain.get("protocol_status", "ready_for_codex"),
        "summary_input_state": "provided" if summary_text else "missing",
        "repo_evidence_refs": {
            "seed_path": seed_path,
            "source_seed_paths": source_seed_paths,
            "supporting_paths": list(dict.fromkeys(item["relative_path"] for item in supporting_evidence)),
            "supporting_count": len(supporting_evidence),
        },
        "paths": referenced_paths,
        "problem_statement": drafted_domain.get("problem_statement", ""),
        "system_role": drafted_domain.get("system_role", ""),
        "domain_value": drafted_domain.get("domain_value", ""),
        "boundary_notes": drafted_domain.get("boundary_notes", ""),
        "child_domain_hints": list(drafted_domain.get("child_domain_hints", [])),
        "cross_domain_notes": list(drafted_domain.get("cross_domain_notes", [])),
    }


def resolve_seed_groups_for_domain_draft(
    drafted_domain: dict,
    seed_lookup: dict[str, dict],
) -> list[dict]:
    ordered_refs: list[str] = []
    for rel in drafted_domain.get("source_seed_paths", []):
        if rel not in ordered_refs:
            ordered_refs.append(rel)
    primary_source_seed = drafted_domain.get("source_seed_path")
    if primary_source_seed and primary_source_seed not in ordered_refs:
        ordered_refs.append(primary_source_seed)
    for rel in drafted_domain.get("evidence_paths", []):
        if rel in seed_lookup and rel not in ordered_refs:
            ordered_refs.append(rel)
    return [seed_lookup[rel] for rel in ordered_refs if rel in seed_lookup]


def build_architecture_domain_placeholders_from_draft(
    top_level_domain_draft: dict,
    protocol: dict,
) -> list[dict]:
    seed_lookup = {group["seed_path"]: group for group in protocol.get("top_level_groups", [])}
    mapped_domains = []
    global_cross_domain_notes = list(top_level_domain_draft.get("cross_domain_notes", []))
    draft_status = top_level_domain_draft.get("draft_status", "pending_codex_judgment")
    protocol_status = top_level_domain_draft.get("protocol_status", protocol.get("protocol_status", "ready_for_codex"))

    for drafted_domain in top_level_domain_draft.get("top_level_domains", []):
        matched_seed_groups = resolve_seed_groups_for_domain_draft(drafted_domain, seed_lookup)
        if not matched_seed_groups:
            continue
        mapped_domain = build_domain_placeholder(
            {
                **drafted_domain,
                "draft_status": drafted_domain.get("draft_status", draft_status),
                "protocol_status": drafted_domain.get("protocol_status", protocol_status),
                "cross_domain_notes": list(drafted_domain.get("cross_domain_notes", [])) or global_cross_domain_notes,
            },
            matched_seed_groups[0],
            related_seed_groups=matched_seed_groups,
            level=1,
            parent_id=None,
            summary_text=protocol.get("summary_text") or None,
            output_schema=protocol.get("requested_output_schema"),
        )
        mapped_domains.append(mapped_domain)

    return mapped_domains


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


def build_architecture_domain_protocol(project_root: Path, summary_text: str | None = None) -> dict:
    repository_evidence = collect_repository_evidence(project_root)
    return build_top_level_domain_inference_protocol(
        project_root,
        repository_evidence,
        summary_text=summary_text,
    )


def build_architecture_domain_placeholders(project_root: Path, summary_text: str | None = None) -> list[dict]:
    protocol = build_architecture_domain_protocol(project_root, summary_text=summary_text)
    top_level_domain_draft = build_top_level_domain_draft_from_protocol(protocol)
    top_level_domains = build_architecture_domain_placeholders_from_draft(
        top_level_domain_draft,
        protocol,
    )
    domains = assign_doc_paths(top_level_domains)
    domains.sort(key=lambda item: (item["level"], item["title"], item["id"]))
    return domains


def infer_architecture_domains(project_root: Path, summary_text: str | None = None) -> list[dict]:
    return build_architecture_domain_placeholders(project_root, summary_text=summary_text)


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
