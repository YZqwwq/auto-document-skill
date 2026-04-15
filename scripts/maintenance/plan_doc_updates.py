#!/usr/bin/env python3
"""
在代码变更后规划文档维护动作。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from core.git_tracking import (
    assess_change_scope,
    capture_git_snapshot,
    describe_ref,
    explain_alignment,
    format_scope_summary,
    merge_git_state,
    short_sha,
    working_tree_paths_from_status,
)
from core.workflow_state import (
    ensure_workflow_state,
    mark_git_alignment_only,
    mark_hold,
    mark_modules_stale,
    mark_structure_stale,
    mark_summary_stale,
    summary_gate_message,
    summary_is_confirmed,
)

DEFAULT_DOC_DIR = "project-docs"
SKILL_NAME = "auto-document"
SKILL_VERSION = "0.4.0"
DOC_SCHEMA_VERSION = "2.0.0"
STRUCTURE_DOC = "overview/project-structure.md"
SUMMARY_DOC = "overview/project-summary.md"
MODULE_INDEX_DOC = "modules/README.md"


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


def doc_root_relative(project_root: Path, doc_root: Path) -> str | None:
    try:
        return doc_root.resolve().relative_to(project_root.resolve()).as_posix().strip("/")
    except ValueError:
        return None


def filter_doc_root_changes(paths: list[str], doc_root_rel: str | None) -> list[str]:
    if not doc_root_rel:
        return paths
    filtered = []
    for path in paths:
        clean = path.replace("\\", "/").strip("/")
        if clean == doc_root_rel or clean.startswith(doc_root_rel + "/"):
            continue
        filtered.append(clean)
    return filtered


def build_domain_catalog(index_payload: dict) -> tuple[dict[str, list[str]], dict[str, str], dict[str, str]]:
    coverage: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    docs: dict[str, str] = {}
    module_docs = dict(index_payload.get("module_docs", {}))
    for domain in index_payload.get("architecture_domains", []):
        domain_id = domain.get("id")
        if not domain_id:
            continue
        paths = [item.replace("\\", "/").strip("/") for item in domain.get("paths", []) if item]
        if paths:
            coverage[domain_id] = paths
        if domain.get("title"):
            titles[domain_id] = domain["title"]
        doc_rel = module_docs.get(domain_id, domain.get("doc_path"))
        if doc_rel:
            docs[domain_id] = doc_rel.replace("\\", "/")
    return coverage, titles, docs


def append_change_log(change_log_path: Path, entries: list[dict]) -> None:
    if not entries:
        return
    lines = ["", f"## {utc_now()}", ""]
    for entry in entries:
        changed_paths = entry.get("changed_paths") or ([entry["changed_path"]] if entry.get("changed_path") else [])
        docs = entry.get("docs", [])
        paths_text = ", ".join(f"`{path}`" for path in changed_paths) if changed_paths else "`(无变更路径)`"
        docs_text = ", ".join(docs) if docs else "无正文更新（仅 git 对齐）"
        strategy = entry.get("update_strategy")
        scope_level = entry.get("scope_level")
        lines.append(f"- {paths_text} -> {docs_text}")
        if strategy or scope_level:
            detail = "；".join(part for part in [f"策略：{strategy}" if strategy else "", f"层级：{scope_level}" if scope_level else ""] if part)
            if detail:
                lines.append(f"  判定：{detail}")
        lines.append(f"  原因：{entry['reason']}")
        evidence_summary = entry.get("evidence_summary", [])
        if evidence_summary:
            lines.append(f"  证据：{' '.join(evidence_summary)}")
        if entry.get("judgment_prompt"):
            lines.append(f"  判断提示：{entry['judgment_prompt']}")
    with change_log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def remember_scope(index_payload: dict, scope: dict, merge_base_sha: str | None = None) -> None:
    git_state = dict(index_payload.get("git_state", {}))
    git_state["recommended_update_mode"] = scope.get("recommended_update_mode")
    git_state["recommended_reason"] = scope.get("recommended_reason")
    git_state["scope_summary"] = format_scope_summary(scope)
    git_state["scope_judgment_prompt"] = scope.get("judgment_prompt")
    git_state["merge_base_sha"] = merge_base_sha
    index_payload["git_state"] = git_state


def clear_scope(index_payload: dict, merge_base_sha: str | None = None) -> None:
    git_state = dict(index_payload.get("git_state", {}))
    git_state["recommended_update_mode"] = None
    git_state["recommended_reason"] = None
    git_state["scope_summary"] = None
    git_state["scope_judgment_prompt"] = None
    git_state["merge_base_sha"] = merge_base_sha
    index_payload["git_state"] = git_state


def print_behind_notice(git_state: dict, git_snapshot: dict) -> None:
    aligned_ref = describe_ref(git_state.get("aligned_branch"), git_state.get("aligned_head_sha"))
    current_ref = describe_ref(git_snapshot.get("last_checked_branch"), git_snapshot.get("last_checked_head_sha"))
    print("[提示] 当前 checkout 早于文档基线。")
    print(f"       文档对齐点：{aligned_ref}")
    print(f"       当前代码：{current_ref}")
    print("       为避免把文档回滚到旧状态，本次不会自动改写 project-docs。")
    print("       如果你只是临时查看旧代码，可以保持不动；如果要让文档改为对齐当前 checkout，请手动执行 reconcile_project_docs.py。")


def print_diverged_notice(git_state: dict, git_snapshot: dict, scope: dict, merge_base_sha: str | None) -> None:
    aligned_ref = describe_ref(git_state.get("aligned_branch"), git_state.get("aligned_head_sha"))
    current_ref = describe_ref(git_snapshot.get("last_checked_branch"), git_snapshot.get("last_checked_head_sha"))
    print("[提示] 当前分支与文档基线已分叉。")
    print(f"       文档对齐点：{aligned_ref}")
    print(f"       当前代码：{current_ref}")
    if merge_base_sha:
        print(f"       共同祖先：{short_sha(merge_base_sha)}")
    print(f"       变化概况：{format_scope_summary(scope)}")
    print(f"       建议模式：{scope['recommended_update_mode']}")
    print(f"       原因：{scope['recommended_reason']}")


def create_plan_entry(
    *,
    changed_paths: list[str],
    docs: list[str],
    reason: str,
    update_strategy: str,
    scope_level: str,
    requires_human_review: bool = False,
    impacted_domain_ids: list[str] | None = None,
    impacted_domain_titles: list[str] | None = None,
    evidence_summary: list[str] | None = None,
    judgment_prompt: str | None = None,
    scope_snapshot: dict | None = None,
) -> dict:
    normalized_paths = [path.replace("\\", "/").strip("/") for path in changed_paths if path]
    normalized_docs = []
    seen_docs = set()
    for doc in docs:
        clean = doc.replace("\\", "/").strip("/")
        if clean and clean not in seen_docs:
            normalized_docs.append(clean)
            seen_docs.add(clean)
    entry = {
        "planned_at": utc_now(),
        "changed_path": normalized_paths[0] if len(normalized_paths) == 1 else None,
        "changed_paths": normalized_paths,
        "docs": normalized_docs,
        "reason": reason,
        "update_strategy": update_strategy,
        "scope_level": scope_level,
        "requires_human_review": requires_human_review,
    }
    if impacted_domain_ids:
        entry["impacted_domain_ids"] = impacted_domain_ids
    if impacted_domain_titles:
        entry["impacted_domain_titles"] = impacted_domain_titles
    if evidence_summary:
        entry["evidence_summary"] = evidence_summary
    if judgment_prompt:
        entry["judgment_prompt"] = judgment_prompt
    if scope_snapshot:
        entry["scope_snapshot"] = scope_snapshot
    return entry


def build_scope_snapshot(scope: dict) -> dict:
    return {
        "changed_paths_count": scope.get("changed_paths_count", 0),
        "top_level_paths": list(scope.get("top_level_paths", [])),
        "impacted_modules": list(scope.get("impacted_modules", [])),
        "new_top_levels": list(scope.get("new_top_levels", [])),
        "critical_root_files": list(scope.get("critical_root_files", [])),
        "uncovered_paths": list(scope.get("uncovered_paths", [])),
        "boundary_sensitive_paths": list(scope.get("boundary_sensitive_paths", [])),
        "low_semantic_risk_paths": list(scope.get("low_semantic_risk_paths", [])),
    }


def build_scope_evidence_summary(changed_paths: list[str], scope: dict, domain_titles: dict[str, str]) -> list[str]:
    evidence = []
    if changed_paths:
        preview = "、".join(f"`{path}`" for path in changed_paths[:5])
        suffix = " 等路径" if len(changed_paths) > 5 else ""
        evidence.append(f"本轮实际变化路径包括 {preview}{suffix}。")
    top_level_paths = scope.get("top_level_paths", [])
    if top_level_paths:
        evidence.append(f"变化已覆盖 {len(top_level_paths)} 个顶层路径：{', '.join(f'`{path}`' for path in top_level_paths[:5])}。")
    critical_root_files = scope.get("critical_root_files", [])
    if critical_root_files:
        evidence.append(f"已触及根级上下文文件或关键配置：{', '.join(f'`{name}`' for name in critical_root_files[:5])}。")
    impacted_modules = scope.get("impacted_modules", [])
    if impacted_modules:
        titles = [domain_titles.get(domain_id, domain_id) for domain_id in impacted_modules[:5]]
        evidence.append(f"当前变化已命中已有功能域映射：{natural_join([f'`{title}`' for title in titles])}。")
    uncovered_paths = scope.get("uncovered_paths", [])
    if uncovered_paths:
        evidence.append(f"仍有未被现有功能域映射覆盖的路径：{', '.join(f'`{path}`' for path in uncovered_paths[:4])}。")
    new_top_levels = scope.get("new_top_levels", [])
    if new_top_levels:
        evidence.append(f"出现了尚未跟踪的新顶层路径：{', '.join(f'`{path}`' for path in new_top_levels[:4])}。")
    boundary_sensitive_paths = scope.get("boundary_sensitive_paths", [])
    if boundary_sensitive_paths:
        evidence.append(f"变化中包含边界敏感入口：{', '.join(f'`{path}`' for path in boundary_sensitive_paths[:4])}。")
    low_semantic_risk_paths = scope.get("low_semantic_risk_paths", [])
    if low_semantic_risk_paths and len(low_semantic_risk_paths) == len(changed_paths):
        evidence.append("所有变化都落在测试、夹具或低语义风险路径中。")
    return evidence[:6]


def natural_join(items: list[str]) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} 和 {cleaned[1]}"
    return f"{'、'.join(cleaned[:-1])} 以及 {cleaned[-1]}"


def build_summary_review_entry(changed_paths: list[str], scope: dict) -> dict:
    return create_plan_entry(
        changed_paths=changed_paths,
        docs=[SUMMARY_DOC],
        reason=scope["recommended_reason"],
        update_strategy="user_review_required",
        scope_level="summary",
        requires_human_review=True,
        evidence_summary=build_scope_evidence_summary(changed_paths, scope, {}),
        judgment_prompt=scope.get("judgment_prompt"),
        scope_snapshot=build_scope_snapshot(scope),
    )


def build_structure_entry(changed_paths: list[str], scope: dict, domain_titles: dict[str, str]) -> dict:
    return create_plan_entry(
        changed_paths=changed_paths,
        docs=[STRUCTURE_DOC, MODULE_INDEX_DOC],
        reason=scope["recommended_reason"],
        update_strategy=scope["recommended_update_mode"],
        scope_level="structure",
        requires_human_review=scope.get("requires_human_review", False),
        impacted_domain_ids=scope.get("impacted_modules", []),
        impacted_domain_titles=[domain_titles.get(domain_id, domain_id) for domain_id in scope.get("impacted_modules", [])],
        evidence_summary=build_scope_evidence_summary(changed_paths, scope, domain_titles),
        judgment_prompt=scope.get("judgment_prompt"),
        scope_snapshot=build_scope_snapshot(scope),
    )


def build_module_entries(
    changed_paths: list[str],
    scope: dict,
    domain_titles: dict[str, str],
    domain_docs: dict[str, str],
) -> list[dict]:
    entries = []
    impacted_ids = scope.get("impacted_modules", [])
    base_evidence = build_scope_evidence_summary(changed_paths, scope, domain_titles)
    for domain_id in impacted_ids:
        doc_rel = domain_docs.get(domain_id)
        if not doc_rel:
            continue
        title = domain_titles.get(domain_id, domain_id)
        reason = f"{scope['recommended_reason']} 最小受影响功能域为 `{title}`。"
        evidence_summary = list(base_evidence)
        evidence_summary.append(f"当前条目下沉到最小受影响功能域 `{title}`。")
        entries.append(
            create_plan_entry(
                changed_paths=changed_paths,
                docs=[doc_rel],
                reason=reason,
                update_strategy="content_update",
                scope_level="module",
                impacted_domain_ids=[domain_id],
                impacted_domain_titles=[title],
                evidence_summary=evidence_summary[:6],
                judgment_prompt=scope.get("judgment_prompt"),
                scope_snapshot=build_scope_snapshot(scope),
            )
        )
    if entries:
        return entries
    return [
        create_plan_entry(
            changed_paths=changed_paths,
            docs=[STRUCTURE_DOC, MODULE_INDEX_DOC],
            reason=f"{scope['recommended_reason']} 当前没有找到可直接复用的功能域文档映射，先复查功能树到代码树映射。",
            update_strategy="reconcile",
            scope_level="structure",
            evidence_summary=base_evidence,
            judgment_prompt=scope.get("judgment_prompt"),
            scope_snapshot=build_scope_snapshot(scope),
        )
    ]


def print_planned_entry(entry: dict) -> None:
    changed_paths = entry.get("changed_paths") or ([entry["changed_path"]] if entry.get("changed_path") else [])
    docs = entry.get("docs", [])
    print(f"[规划] {', '.join(changed_paths) if changed_paths else '(无变更路径)'}")
    print(f"       策略：{entry.get('update_strategy')} / 层级：{entry.get('scope_level')}")
    print(f"       文档：{', '.join(docs) if docs else '无正文更新（仅 git 对齐）'}")
    print(f"       原因：{entry['reason']}")
    evidence_summary = entry.get("evidence_summary", [])
    if evidence_summary:
        print(f"       证据：{' '.join(evidence_summary)}")
    if entry.get("judgment_prompt"):
        print(f"       判断提示：{entry['judgment_prompt']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="根据项目变更路径规划文档更新。")
    parser.add_argument("--project-root", required=True, help="仓库根目录。")
    parser.add_argument("--doc-root", help="文档根目录。默认使用 <project-root>/project-docs。")
    parser.add_argument("--changed", action="append", help="发生变化的项目相对路径。")
    parser.add_argument("--git-status", action="store_true", help="从 git status --porcelain 读取变更路径。")
    parser.add_argument(
        "--git-sense",
        action="store_true",
        help="对比 index.json 记录的对齐 commit 与当前 git HEAD，自动推导需要更新的文档。",
    )
    args = parser.parse_args()

    if not args.changed and not args.git_status and not args.git_sense:
        args.git_sense = True

    project_root = Path(args.project_root).resolve()
    doc_root = normalize_doc_root(project_root, args.doc_root).resolve()
    index_path, index_payload = load_index(doc_root)
    ensure_workflow_state(index_payload)
    index_payload["skill_name"] = SKILL_NAME
    index_payload["skill_version"] = SKILL_VERSION
    index_payload["doc_schema_version"] = DOC_SCHEMA_VERSION
    doc_root_rel = doc_root_relative(project_root, doc_root)

    changed_paths = list(args.changed or [])
    git_snapshot = capture_git_snapshot(project_root)
    git_state = dict(index_payload.get("git_state", {}))
    alignment_message = None
    merge_base_sha = None

    if args.git_status:
        if not git_snapshot.get("git_available"):
            print("[提示] 当前项目未检测到 git。若要使用 git 感知，请先安装并初始化 git；否则请下沉到全量阅读项目并执行 reconcile。")
        else:
            changed_paths.extend(filter_doc_root_changes(working_tree_paths_from_status(git_snapshot.get("status_porcelain", [])), doc_root_rel))
            alignment_message = "本轮依据当前 git 工作区未提交变化规划文档维护。"

    if args.git_sense:
        relation, sensed_paths, reason, merge_base_sha = explain_alignment(project_root, git_state.get("aligned_head_sha"), git_snapshot)
        git_state = merge_git_state(git_state, git_snapshot, relation=relation)
        git_state["merge_base_sha"] = merge_base_sha
        index_payload["git_state"] = git_state
        alignment_message = reason
        if relation == "no_git":
            clear_scope(index_payload)
            index_payload["pending_updates"] = []
            index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print("[提示] 当前项目未检测到 git。若要使用 git 感知，请先安装并初始化 git；否则请下沉到全量阅读项目，例如执行 `reconcile_project_docs.py`。")
            return 0
        if relation == "current_behind":
            mark_hold(index_payload)
            remember_scope(
                index_payload,
                {
                    "recommended_update_mode": "hold",
                    "recommended_reason": "当前 checkout 早于文档对齐点，默认保持文档不动。",
                    "changed_paths_count": 0,
                    "top_level_paths": [],
                    "impacted_modules": [],
                    "new_top_levels": [],
                    "critical_root_files": [],
                },
                merge_base_sha=merge_base_sha,
            )
            index_payload["pending_updates"] = []
            index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print_behind_notice(index_payload.get("git_state", {}), git_snapshot)
            return 0
        changed_paths.extend(filter_doc_root_changes(sensed_paths, doc_root_rel))

    normalized_changed = []
    seen = set()
    for item in changed_paths:
        clean = item.replace("\\", "/").strip("/")
        if clean and clean not in seen:
            normalized_changed.append(clean)
            seen.add(clean)

    if not summary_is_confirmed(index_payload):
        index_payload["pending_updates"] = []
        index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot, relation=index_payload.get("git_state", {}).get("last_relation"))
        index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[提示] {summary_gate_message(index_payload)}")
        print("[提示] 在 summary 确认前，当前只记录 git 状态，不进入正式文档维护规划。")
        return 0

    domain_coverage, domain_titles, domain_docs = build_domain_catalog(index_payload)
    tracked_paths = list(index_payload.get("tracked_paths", []))
    relation = index_payload.get("git_state", {}).get("last_relation")

    if not normalized_changed:
        clear_scope(index_payload, merge_base_sha=index_payload.get("git_state", {}).get("merge_base_sha"))
        index_payload["pending_updates"] = []
        index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot, relation=relation)
        index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if alignment_message:
            print(f"[提示] {alignment_message}")
        else:
            print("[提示] 当前没有发现需要规划的代码变化。")
        return 0

    legacy_module_units = {
        key.replace("\\", "/").strip("/"): [key.replace("\\", "/").strip("/")]
        for key in index_payload.get("module_docs", {})
        if "/" in str(key)
    }
    scope = assess_change_scope(normalized_changed, domain_coverage or legacy_module_units, tracked_paths, relation=relation)
    remember_scope(index_payload, scope, merge_base_sha=merge_base_sha or index_payload.get("git_state", {}).get("merge_base_sha"))

    if relation == "diverged":
        print_diverged_notice(index_payload.get("git_state", {}), git_snapshot, scope, index_payload.get("git_state", {}).get("merge_base_sha"))

    entries: list[dict]
    mode = scope.get("recommended_update_mode")
    reason = scope.get("recommended_reason")

    if mode == "user_review_required":
        mark_summary_stale(index_payload, reason=reason)
        entries = [build_summary_review_entry(normalized_changed, scope)]
    elif mode == "reconcile" or scope.get("scope_level") == "structure":
        mark_structure_stale(index_payload, reason=reason)
        entries = [build_structure_entry(normalized_changed, scope, domain_titles)]
    elif mode == "git_alignment_only":
        mark_git_alignment_only(index_payload, git_snapshot)
        index_payload["pending_updates"] = []
        index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot, align_to_current=True, relation="aligned")
        index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log_entry = create_plan_entry(
            changed_paths=normalized_changed,
            docs=[],
            reason=reason,
            update_strategy="git_alignment_only",
            scope_level="git",
            evidence_summary=build_scope_evidence_summary(normalized_changed, scope, domain_titles),
            judgment_prompt=scope.get("judgment_prompt"),
            scope_snapshot=build_scope_snapshot(scope),
        )
        append_change_log(doc_root / "history" / "change-log.md", [log_entry])
        print("[完成] 本轮变化被判定为仅需 git 对齐，不改写正文。")
        print(f"       原因：{reason}")
        return 0
    else:
        mark_modules_stale(index_payload, reason=reason)
        entries = build_module_entries(normalized_changed, scope, domain_titles, domain_docs)

    if alignment_message:
        print(f"[提示] {alignment_message}")

    index_payload["pending_updates"] = entries
    index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot, relation=index_payload.get("git_state", {}).get("last_relation"))
    remember_scope(index_payload, scope, merge_base_sha=merge_base_sha or index_payload.get("git_state", {}).get("merge_base_sha"))
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    append_change_log(doc_root / "history" / "change-log.md", entries)

    for entry in entries:
        print_planned_entry(entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
