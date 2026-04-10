#!/usr/bin/env python3
"""
为 auto-document 提供统一的工作流状态机辅助函数。
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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_summary_state() -> dict:
    return {
        "status": SUMMARY_MISSING,
        "doc_path": "overview/project-summary.md",
        "source": None,
        "confirmed_by": None,
        "confirmed_at": None,
        "baseline_branch": None,
        "baseline_head_sha": None,
        "intent_lock": False,
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
    }


def default_module_state() -> dict:
    return {
        "status": MODULE_BLOCKED_BY_SUMMARY,
        "generated_at": None,
        "aligned_branch": None,
        "aligned_head_sha": None,
        "based_on_summary_confirmed_at": None,
        "based_on_structure_generated_at": None,
    }


def current_ref(snapshot: dict | None) -> tuple[str | None, str | None]:
    snapshot = snapshot or {}
    return snapshot.get("last_checked_branch"), snapshot.get("last_checked_head_sha")


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

    has_summary_doc = "overview/project-summary.md" in set(index_payload.get("generated_docs", []))
    has_structure_doc = "overview/project-structure.md" in set(index_payload.get("generated_docs", []))
    has_structure_data = bool(index_payload.get("architecture_domains"))
    has_modules = bool(index_payload.get("module_docs"))

    if summary_state["status"] == SUMMARY_MISSING and has_summary_doc:
        summary_state["status"] = SUMMARY_PENDING_REVIEW
        summary_state["source"] = summary_state.get("source") or "legacy_generated"

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
        return "项目 summary 尚未生成。请先执行 summary 草案阶段。"
    if status in {SUMMARY_DRAFTED, SUMMARY_PENDING_REVIEW}:
        return "项目 summary 还未确认。请先让用户审阅并确认 `overview/project-summary.md`。"
    if status == SUMMARY_STALE:
        return "项目 summary 已被标记为过期。请先重新确认 `overview/project-summary.md`。"
    return "项目 summary 当前不可用于后续阶段。"


def structure_gate_message(index_payload: dict) -> str:
    ensure_workflow_state(index_payload)
    status = index_payload["structure_state"]["status"]
    if status in {STRUCTURE_MISSING, STRUCTURE_BLOCKED_BY_SUMMARY}:
        return "项目 structure 尚未建立。请先生成并对齐 `overview/project-structure.md`。"
    if status == STRUCTURE_STALE:
        return "项目 structure 已过期。请先重新建立结构责任树。"
    return "项目 structure 当前不可用于模块生成。"


def mark_summary_drafted(index_payload: dict, git_snapshot: dict | None = None, *, source: str = "ai_draft") -> None:
    ensure_workflow_state(index_payload)
    branch, sha = current_ref(git_snapshot)
    index_payload["summary_state"].update(
        {
            "status": SUMMARY_PENDING_REVIEW,
            "source": source,
            "confirmed_by": None,
            "confirmed_at": None,
            "baseline_branch": branch,
            "baseline_head_sha": sha,
            "intent_lock": False,
        }
    )
    index_payload["structure_state"]["status"] = STRUCTURE_BLOCKED_BY_SUMMARY
    index_payload["module_state"]["status"] = MODULE_BLOCKED_BY_SUMMARY
    index_payload["workflow_phase"] = PHASE_SUMMARY_PENDING_REVIEW
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_summary_confirmed(index_payload: dict, git_snapshot: dict | None = None, *, confirmed_by: str = "user") -> None:
    ensure_workflow_state(index_payload)
    branch, sha = current_ref(git_snapshot)
    confirmed_at = utc_now()
    index_payload["summary_state"].update(
        {
            "status": SUMMARY_CONFIRMED,
            "confirmed_by": confirmed_by,
            "confirmed_at": confirmed_at,
            "baseline_branch": branch,
            "baseline_head_sha": sha,
            "intent_lock": True,
        }
    )
    if index_payload["structure_state"]["status"] == STRUCTURE_BLOCKED_BY_SUMMARY:
        index_payload["structure_state"]["status"] = STRUCTURE_MISSING
    if index_payload["module_state"]["status"] == MODULE_BLOCKED_BY_SUMMARY:
        index_payload["module_state"]["status"] = MODULE_BLOCKED_BY_STRUCTURE
    index_payload["workflow_phase"] = PHASE_SUMMARY_CONFIRMED
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_summary_stale(index_payload: dict, *, reason: str | None = None) -> None:
    ensure_workflow_state(index_payload)
    index_payload["summary_state"]["status"] = SUMMARY_STALE
    index_payload["summary_state"]["intent_lock"] = False
    if reason:
        index_payload["summary_state"]["notes"] = reason
    if index_payload["structure_state"]["status"] != STRUCTURE_MISSING:
        index_payload["structure_state"]["status"] = STRUCTURE_STALE
    if index_payload["module_state"]["status"] != MODULE_MISSING:
        index_payload["module_state"]["status"] = MODULE_STALE
    index_payload["workflow_phase"] = PHASE_SUMMARY_REOPEN_REQUIRED
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_structure_drafted(index_payload: dict) -> None:
    ensure_workflow_state(index_payload)
    index_payload["structure_state"]["status"] = STRUCTURE_DRAFTED
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
        }
    )
    if index_payload["module_state"]["status"] == MODULE_BLOCKED_BY_STRUCTURE:
        index_payload["module_state"]["status"] = MODULE_MISSING
    index_payload["workflow_phase"] = PHASE_STRUCTURE_ALIGNED
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_structure_stale(index_payload: dict, *, reason: str | None = None) -> None:
    ensure_workflow_state(index_payload)
    index_payload["structure_state"]["status"] = STRUCTURE_STALE
    if reason:
        index_payload["summary_state"]["notes"] = reason
    if index_payload["module_state"]["status"] not in {MODULE_MISSING, MODULE_BLOCKED_BY_SUMMARY}:
        index_payload["module_state"]["status"] = MODULE_STALE
    index_payload["workflow_phase"] = PHASE_SUMMARY_CONFIRMED if summary_is_confirmed(index_payload) else PHASE_SUMMARY_PENDING_REVIEW
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_modules_drafted(index_payload: dict) -> None:
    ensure_workflow_state(index_payload)
    index_payload["module_state"]["status"] = MODULE_DRAFTED
    index_payload["workflow_phase"] = PHASE_MODULES_DRAFT
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_modules_aligned(index_payload: dict, git_snapshot: dict | None = None) -> None:
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
        }
    )
    index_payload["workflow_phase"] = PHASE_MAINTENANCE
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_modules_stale(index_payload: dict) -> None:
    ensure_workflow_state(index_payload)
    if index_payload["module_state"]["status"] != MODULE_MISSING:
        index_payload["module_state"]["status"] = MODULE_STALE
    index_payload["workflow_phase"] = PHASE_MAINTENANCE if summary_is_confirmed(index_payload) else PHASE_SUMMARY_PENDING_REVIEW
    index_payload["analysis_round"] = sync_analysis_round(index_payload)


def mark_hold(index_payload: dict) -> None:
    ensure_workflow_state(index_payload)
    index_payload["workflow_phase"] = PHASE_HOLD

