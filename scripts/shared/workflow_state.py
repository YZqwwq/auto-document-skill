#!/usr/bin/env python3
"""
为 auto-document 提供统一的工作流状态机辅助函数。

当前这份状态机仍保留部分旧阶段名以兼容已有脚本，
但它们在当前项目里的语义已经更新为：

- `summary` 表示项目级意图是否已被人工校准到可作为后续基线
- `structure` 表示功能树与代码树映射状态，而不是简单目录树状态
- `module` 表示功能域文档是否仍与当前项目状态对齐
- git 变化不自动等于正文要改写，允许出现“只更新 git 基线”的处理结果

这份状态机只负责记录和推进工作流状态，不负责替代当前会话中的
Codex 完成项目语义判断。
"""

from __future__ import annotations

from datetime import datetime, timezone


PHASE_INITIALIZED = "initialized"
PHASE_SUMMARY_DRAFT = "summary_draft"
PHASE_SUMMARY_PENDING_REVIEW = "summary_pending_review"
PHASE_SUMMARY_CONFIRMED = "summary_confirmed"
PHASE_STRUCTURE_DRAFT = "structure_draft"
PHASE_STRUCTURE_ALIGNED = "structure_aligned"
PHASE_MODULES_DRAFT = "modules_draft"
PHASE_MODULES_ALIGNED = "modules_aligned"
PHASE_MAINTENANCE = "maintenance"
PHASE_HOLD = "hold"
PHASE_SUMMARY_REOPEN_REQUIRED = "summary_reopen_required"

# Compatibility aliases with the newer positioning language.
PHASE_FUNCTION_MAP_DRAFT = PHASE_STRUCTURE_DRAFT
PHASE_FUNCTION_MAP_ALIGNED = PHASE_STRUCTURE_ALIGNED


SUMMARY_MISSING = "missing"
SUMMARY_DRAFTED = "drafted"
SUMMARY_PENDING_REVIEW = "pending_review"
SUMMARY_CONFIRMED = "confirmed"
SUMMARY_STALE = "stale"

STRUCTURE_MISSING = "missing"
STRUCTURE_BLOCKED_BY_SUMMARY = "blocked_by_summary"
STRUCTURE_DRAFTED = "drafted"
STRUCTURE_ALIGNED = "aligned"
STRUCTURE_STALE = "stale"

MODULE_MISSING = "missing"
MODULE_BLOCKED_BY_SUMMARY = "blocked_by_summary"
MODULE_BLOCKED_BY_STRUCTURE = "blocked_by_structure"
MODULE_DRAFTED = "drafted"
MODULE_ALIGNED = "aligned"
MODULE_STALE = "stale"


SUMMARY_STATUS_SET = {
    SUMMARY_MISSING,
    SUMMARY_DRAFTED,
    SUMMARY_PENDING_REVIEW,
    SUMMARY_CONFIRMED,
    SUMMARY_STALE,
}
STRUCTURE_STATUS_SET = {
    STRUCTURE_MISSING,
    STRUCTURE_BLOCKED_BY_SUMMARY,
    STRUCTURE_DRAFTED,
    STRUCTURE_ALIGNED,
    STRUCTURE_STALE,
}
MODULE_STATUS_SET = {
    MODULE_MISSING,
    MODULE_BLOCKED_BY_SUMMARY,
    MODULE_BLOCKED_BY_STRUCTURE,
    MODULE_DRAFTED,
    MODULE_ALIGNED,
    MODULE_STALE,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_summary_state() -> dict:
    return {
        "status": SUMMARY_MISSING,
        "doc_path": "overview/project-summary.md",
        "source": None,
        "draft_generated_at": None,
        "confirmed_by": None,
        "confirmed_at": None,
        "confirmation_mode": None,
        "baseline_branch": None,
        "baseline_head_sha": None,
        "intent_lock": False,
        "requires_human_review": False,
        "notes": None,
    }


def default_structure_state() -> dict:
    return {
        "status": STRUCTURE_BLOCKED_BY_SUMMARY,
        "doc_path": "overview/project-structure.md",
        "generated_at": None,
        "aligned_branch": None,
        "aligned_head_sha": None,
        "based_on_summary_confirmed_at": None,
        "mapping_scope": "function_to_code",
        "tree_kind": "function_map",
        "requires_human_review": False,
        "notes": None,
    }


def default_module_state() -> dict:
    return {
        "status": MODULE_BLOCKED_BY_SUMMARY,
        "generated_at": None,
        "aligned_branch": None,
        "aligned_head_sha": None,
        "based_on_summary_confirmed_at": None,
        "based_on_structure_generated_at": None,
        "last_update_strategy": None,
        "git_alignment_only_pending": False,
        "requires_human_review": False,
        "notes": None,
    }


def current_ref(snapshot: dict | None) -> tuple[str | None, str | None]:
    snapshot = snapshot or {}
    return snapshot.get("last_checked_branch"), snapshot.get("last_checked_head_sha")


def normalize_status(value: str | None, allowed: set[str], fallback: str) -> str:
    if value in allowed:
        return value
    return fallback


def sync_analysis_round(index_payload: dict) -> int:
    summary_status = index_payload.get("summary_state", {}).get("status")
    structure_status = index_payload.get("structure_state", {}).get("status")
    module_status = index_payload.get("module_state", {}).get("status")

    if module_status in {MODULE_DRAFTED, MODULE_ALIGNED, MODULE_STALE}:
        return 3
    if structure_status in {STRUCTURE_DRAFTED, STRUCTURE_ALIGNED, STRUCTURE_STALE}:
        return 2
    if summary_status in {SUMMARY_DRAFTED, SUMMARY_PENDING_REVIEW, SUMMARY_CONFIRMED, SUMMARY_STALE}:
        return 1
    return 0


def infer_phase(index_payload: dict) -> str:
    summary_status = index_payload.get("summary_state", {}).get("status")
    structure_status = index_payload.get("structure_state", {}).get("status")
    module_status = index_payload.get("module_state", {}).get("status")
    current_phase = index_payload.get("workflow_phase")

    if current_phase == PHASE_HOLD:
        return PHASE_HOLD
    if summary_status == SUMMARY_STALE:
        return PHASE_SUMMARY_REOPEN_REQUIRED
    if summary_status in {SUMMARY_DRAFTED, SUMMARY_PENDING_REVIEW}:
        return PHASE_SUMMARY_PENDING_REVIEW
    if summary_status == SUMMARY_CONFIRMED and structure_status in {STRUCTURE_BLOCKED_BY_SUMMARY, STRUCTURE_MISSING}:
        return PHASE_SUMMARY_CONFIRMED
    if structure_status == STRUCTURE_DRAFTED:
        return PHASE_STRUCTURE_DRAFT
    if structure_status == STRUCTURE_ALIGNED and module_status in {MODULE_BLOCKED_BY_STRUCTURE, MODULE_MISSING}:
        return PHASE_STRUCTURE_ALIGNED
    if module_status == MODULE_DRAFTED:
        return PHASE_MODULES_DRAFT
    if module_status == MODULE_ALIGNED:
        return PHASE_MAINTENANCE
    return PHASE_INITIALIZED


def ensure_workflow_state(index_payload: dict) -> dict:
    summary_state = dict(default_summary_state())
    summary_state.update(index_payload.get("summary_state", {}))
    structure_state = dict(default_structure_state())
    structure_state.update(index_payload.get("structure_state", {}))
    module_state = dict(default_module_state())
    module_state.update(index_payload.get("module_state", {}))

    summary_state["status"] = normalize_status(summary_state.get("status"), SUMMARY_STATUS_SET, SUMMARY_MISSING)
    structure_state["status"] = normalize_status(
        structure_state.get("status"),
        STRUCTURE_STATUS_SET,
        STRUCTURE_BLOCKED_BY_SUMMARY,
    )
    module_state["status"] = normalize_status(module_state.get("status"), MODULE_STATUS_SET, MODULE_BLOCKED_BY_SUMMARY)

    has_structure_doc = "overview/project-structure.md" in set(index_payload.get("generated_docs", []))
    has_structure_data = bool(index_payload.get("architecture_domains"))
    has_modules = bool(index_payload.get("module_docs"))

    if structure_state["status"] == STRUCTURE_BLOCKED_BY_SUMMARY and has_structure_doc and has_structure_data:
        structure_state["status"] = STRUCTURE_STALE if summary_state["status"] != SUMMARY_CONFIRMED else STRUCTURE_ALIGNED

    if module_state["status"] in {MODULE_BLOCKED_BY_SUMMARY, MODULE_BLOCKED_BY_STRUCTURE} and has_modules:
        if summary_state["status"] != SUMMARY_CONFIRMED:
            module_state["status"] = MODULE_STALE
        elif structure_state["status"] != STRUCTURE_ALIGNED:
            module_state["status"] = MODULE_STALE
        else:
            module_state["status"] = MODULE_ALIGNED

    if summary_state["status"] == SUMMARY_CONFIRMED and structure_state["status"] == STRUCTURE_BLOCKED_BY_SUMMARY:
        structure_state["status"] = STRUCTURE_MISSING
    if summary_state["status"] == SUMMARY_CONFIRMED and module_state["status"] == MODULE_BLOCKED_BY_SUMMARY:
        module_state["status"] = MODULE_BLOCKED_BY_STRUCTURE
    if structure_state["status"] == STRUCTURE_ALIGNED and module_state["status"] == MODULE_BLOCKED_BY_STRUCTURE:
        module_state["status"] = MODULE_MISSING

    index_payload["summary_state"] = summary_state
    index_payload["structure_state"] = structure_state
    index_payload["module_state"] = module_state
    index_payload["analysis_round"] = sync_analysis_round(index_payload)
    index_payload["workflow_phase"] = infer_phase(index_payload)
    return index_payload


def summary_is_confirmed(index_payload: dict) -> bool:
    ensure_workflow_state(index_payload)
    return index_payload["summary_state"]["status"] == SUMMARY_CONFIRMED


def structure_is_aligned(index_payload: dict) -> bool:
    ensure_workflow_state(index_payload)
    return index_payload["structure_state"]["status"] == STRUCTURE_ALIGNED


def modules_are_aligned(index_payload: dict) -> bool:
    ensure_workflow_state(index_payload)
    return index_payload["module_state"]["status"] == MODULE_ALIGNED


def summary_gate_message(index_payload: dict) -> str:
    ensure_workflow_state(index_payload)
    status = index_payload["summary_state"]["status"]
    if status == SUMMARY_MISSING:
        return "项目级 summary 尚未生成。请先生成用于人工校准的 `overview/project-summary.md` 草案。"
    if status in {SUMMARY_DRAFTED, SUMMARY_PENDING_REVIEW}:
        return "项目级 summary 还未完成校准。请先让用户补充、修正或明确接受 `overview/project-summary.md`。"
    if status == SUMMARY_STALE:
        return "项目级 summary 已被标记为过期。请先重新校准 `overview/project-summary.md`。"
    return "项目级 summary 当前不可作为后续功能树分析基线。"


def structure_gate_message(index_payload: dict) -> str:
    ensure_workflow_state(index_payload)
    status = index_payload["structure_state"]["status"]
    if status in {STRUCTURE_MISSING, STRUCTURE_BLOCKED_BY_SUMMARY}:
        return "功能树与代码树映射尚未建立。请先生成并对齐 `overview/project-structure.md`。"
    if status == STRUCTURE_STALE:
        return "当前功能树与代码树映射已过期。请先重新建立 `overview/project-structure.md`。"
    return "当前功能树与代码树映射不可用于模块生成。"


def mark_summary_drafted(index_payload: dict, git_snapshot: dict | None = None, *, source: str = "codex_session_draft") -> None:
    ensure_workflow_state(index_payload)
    branch, sha = current_ref(git_snapshot)
    index_payload["summary_state"].update(
        {
            "status": SUMMARY_PENDING_REVIEW,
            "source": source,
            "draft_generated_at": utc_now(),
            "confirmed_by": None,
            "confirmed_at": None,
            "confirmation_mode": None,
            "baseline_branch": branch,
            "baseline_head_sha": sha,
            "intent_lock": False,
            "requires_human_review": True,
            "notes": None,
        }
    )
    index_payload["structure_state"]["status"] = STRUCTURE_BLOCKED_BY_SUMMARY
    index_payload["structure_state"]["requires_human_review"] = False
    index_payload["structure_state"]["notes"] = None
    index_payload["module_state"]["status"] = MODULE_BLOCKED_BY_SUMMARY
    index_payload["module_state"]["git_alignment_only_pending"] = False
    index_payload["module_state"]["requires_human_review"] = False
    index_payload["module_state"]["notes"] = None
    index_payload["workflow_phase"] = PHASE_SUMMARY_PENDING_REVIEW
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_summary_confirmed(
    index_payload: dict,
    git_snapshot: dict | None = None,
    *,
    confirmed_by: str = "user",
    confirmation_mode: str | None = None,
) -> None:
    ensure_workflow_state(index_payload)
    branch, sha = current_ref(git_snapshot)
    confirmed_at = utc_now()
    if confirmation_mode is None:
        confirmation_mode = "human_explicit" if confirmed_by == "user" else "codex_assisted"
    index_payload["summary_state"].update(
        {
            "status": SUMMARY_CONFIRMED,
            "confirmed_by": confirmed_by,
            "confirmed_at": confirmed_at,
            "confirmation_mode": confirmation_mode,
            "baseline_branch": branch,
            "baseline_head_sha": sha,
            "intent_lock": True,
            "requires_human_review": False,
        }
    )
    if index_payload["structure_state"]["status"] == STRUCTURE_BLOCKED_BY_SUMMARY:
        index_payload["structure_state"]["status"] = STRUCTURE_MISSING
    if index_payload["module_state"]["status"] == MODULE_BLOCKED_BY_SUMMARY:
        index_payload["module_state"]["status"] = MODULE_BLOCKED_BY_STRUCTURE
    index_payload["structure_state"]["requires_human_review"] = False
    index_payload["module_state"]["requires_human_review"] = False
    index_payload["workflow_phase"] = PHASE_SUMMARY_CONFIRMED
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_summary_stale(index_payload: dict, *, reason: str | None = None) -> None:
    ensure_workflow_state(index_payload)
    index_payload["summary_state"]["status"] = SUMMARY_STALE
    index_payload["summary_state"]["intent_lock"] = False
    index_payload["summary_state"]["requires_human_review"] = True
    if reason:
        index_payload["summary_state"]["notes"] = reason
    if index_payload["structure_state"]["status"] != STRUCTURE_MISSING:
        index_payload["structure_state"]["status"] = STRUCTURE_STALE
        index_payload["structure_state"]["requires_human_review"] = True
        index_payload["structure_state"]["notes"] = reason
    if index_payload["module_state"]["status"] != MODULE_MISSING:
        index_payload["module_state"]["status"] = MODULE_STALE
        index_payload["module_state"]["requires_human_review"] = True
        index_payload["module_state"]["notes"] = reason
    index_payload["workflow_phase"] = PHASE_SUMMARY_REOPEN_REQUIRED
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_structure_drafted(index_payload: dict) -> None:
    ensure_workflow_state(index_payload)
    index_payload["structure_state"]["status"] = STRUCTURE_DRAFTED
    index_payload["structure_state"]["notes"] = None
    index_payload["workflow_phase"] = PHASE_STRUCTURE_DRAFT
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_structure_aligned(index_payload: dict, git_snapshot: dict | None = None) -> None:
    ensure_workflow_state(index_payload)
    branch, sha = current_ref(git_snapshot)
    index_payload["structure_state"].update(
        {
            "status": STRUCTURE_ALIGNED,
            "generated_at": utc_now(),
            "aligned_branch": branch,
            "aligned_head_sha": sha,
            "based_on_summary_confirmed_at": index_payload["summary_state"].get("confirmed_at"),
            "requires_human_review": False,
            "notes": None,
        }
    )
    if index_payload["module_state"]["status"] == MODULE_BLOCKED_BY_STRUCTURE:
        index_payload["module_state"]["status"] = MODULE_MISSING
    index_payload["workflow_phase"] = PHASE_STRUCTURE_ALIGNED
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_structure_stale(index_payload: dict, *, reason: str | None = None) -> None:
    ensure_workflow_state(index_payload)
    index_payload["structure_state"]["status"] = STRUCTURE_STALE
    index_payload["structure_state"]["requires_human_review"] = True
    if reason:
        index_payload["structure_state"]["notes"] = reason
    if index_payload["module_state"]["status"] not in {MODULE_MISSING, MODULE_BLOCKED_BY_SUMMARY}:
        index_payload["module_state"]["status"] = MODULE_STALE
        index_payload["module_state"]["requires_human_review"] = True
        if reason:
            index_payload["module_state"]["notes"] = reason
    index_payload["workflow_phase"] = PHASE_SUMMARY_CONFIRMED if summary_is_confirmed(index_payload) else PHASE_SUMMARY_PENDING_REVIEW
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_modules_drafted(index_payload: dict) -> None:
    ensure_workflow_state(index_payload)
    index_payload["module_state"]["status"] = MODULE_DRAFTED
    index_payload["module_state"]["git_alignment_only_pending"] = False
    index_payload["module_state"]["notes"] = None
    index_payload["workflow_phase"] = PHASE_MODULES_DRAFT
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_modules_aligned(
    index_payload: dict,
    git_snapshot: dict | None = None,
    *,
    strategy: str = "content_update",
) -> None:
    ensure_workflow_state(index_payload)
    branch, sha = current_ref(git_snapshot)
    index_payload["module_state"].update(
        {
            "status": MODULE_ALIGNED,
            "generated_at": utc_now(),
            "aligned_branch": branch,
            "aligned_head_sha": sha,
            "based_on_summary_confirmed_at": index_payload["summary_state"].get("confirmed_at"),
            "based_on_structure_generated_at": index_payload["structure_state"].get("generated_at"),
            "last_update_strategy": strategy,
            "git_alignment_only_pending": False,
            "requires_human_review": False,
            "notes": None,
        }
    )
    index_payload["workflow_phase"] = PHASE_MAINTENANCE
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_modules_stale(index_payload: dict, *, reason: str | None = None) -> None:
    ensure_workflow_state(index_payload)
    if index_payload["module_state"]["status"] != MODULE_MISSING:
        index_payload["module_state"]["status"] = MODULE_STALE
        index_payload["module_state"]["requires_human_review"] = True
        if reason:
            index_payload["module_state"]["notes"] = reason
    index_payload["workflow_phase"] = PHASE_MAINTENANCE if summary_is_confirmed(index_payload) else PHASE_SUMMARY_PENDING_REVIEW
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_git_alignment_only(index_payload: dict, git_snapshot: dict | None = None) -> None:
    """
    记录本轮变化只需要更新 git 基线，而不需要改写正文。

    这个操作不会改变 summary / structure / module 的核心对齐关系，
    只会把模块层最近一次更新策略标记为 `git_alignment_only`，
    供维护脚本在后续真正接入该分支时复用。
    """

    ensure_workflow_state(index_payload)
    branch, sha = current_ref(git_snapshot)
    module_status = index_payload["module_state"].get("status")
    if module_status not in {MODULE_MISSING, MODULE_BLOCKED_BY_SUMMARY, MODULE_BLOCKED_BY_STRUCTURE}:
        index_payload["module_state"].update(
            {
                "status": MODULE_ALIGNED,
                "generated_at": utc_now(),
                "aligned_branch": branch,
                "aligned_head_sha": sha,
                "based_on_summary_confirmed_at": index_payload["summary_state"].get("confirmed_at"),
                "based_on_structure_generated_at": index_payload["structure_state"].get("generated_at"),
                "last_update_strategy": "git_alignment_only",
                "git_alignment_only_pending": False,
                "requires_human_review": False,
                "notes": None,
            }
        )
    else:
        index_payload["module_state"].update(
            {
                "last_update_strategy": "git_alignment_only",
                "git_alignment_only_pending": False,
                "requires_human_review": False,
                "notes": None,
            }
        )

    if structure_is_aligned(index_payload):
        index_payload["workflow_phase"] = PHASE_MAINTENANCE
    elif summary_is_confirmed(index_payload):
        index_payload["workflow_phase"] = PHASE_SUMMARY_CONFIRMED
    else:
        index_payload["workflow_phase"] = PHASE_SUMMARY_PENDING_REVIEW
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_hold(index_payload: dict) -> None:
    ensure_workflow_state(index_payload)
    index_payload["workflow_phase"] = PHASE_HOLD
