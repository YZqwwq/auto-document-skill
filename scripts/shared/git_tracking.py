#!/usr/bin/env python3
"""
为 auto-document 提供 git 感知、范围快照与维护建议整理能力。

这份工具层负责：

- 读取当前仓库的 git 状态
- 整理变更路径与对齐关系
- 输出供当前会话中的 Codex 使用的范围快照与维护建议

它不负责替代 Codex 做最终的语义判断，只负责把 git 事实整理成
后续可复用的结构化输入。
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts.shared.path_intelligence import is_low_semantic_risk_path, is_root_context_signal_path

RECONCILE_CHANGE_COUNT_THRESHOLD = 20
RECONCILE_MODULE_COUNT_THRESHOLD = 3
RECONCILE_TOP_LEVEL_THRESHOLD = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def short_sha(value: str | None) -> str:
    if not value:
        return "unknown"
    return value[:7]


def describe_ref(branch: str | None, sha: str | None) -> str:
    label = branch or "(detached)"
    return f"{label} @ {short_sha(sha)}"


def normalize_path(value: str) -> str:
    clean = value.strip().strip('"').replace("\\", "/")
    return clean.strip("/")


def is_ignored_root_tooling_path(path: str) -> bool:
    del path
    return False


def is_summary_trigger_path(path: str) -> bool:
    return is_root_context_signal_path(path)


def is_boundary_sensitive_path(path: str) -> bool:
    clean = normalize_path(path)
    if not clean:
        return False
    target = Path(clean)
    depth = len([part for part in clean.split("/") if part])
    if is_root_context_signal_path(clean):
        return True
    if depth <= 2 and target.suffix.lower() in {".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".java", ".rs"}:
        return True
    return depth <= 2 and target.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}


def run_git(project_root: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess | None:
    cmd = ["git", "-C", str(project_root), *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=check)
    except FileNotFoundError:
        return None
    except subprocess.CalledProcessError:
        if check:
            raise
        return None


def is_git_repo(project_root: Path) -> bool:
    result = run_git(project_root, ["rev-parse", "--is-inside-work-tree"], check=False)
    if result is None:
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def parse_status_line(line: str) -> tuple[str, str] | None:
    if len(line) < 4:
        return None
    status = line[:2]
    raw_path = line[3:].strip()
    if " -> " in raw_path:
        _, raw_path = raw_path.split(" -> ", 1)
    path = normalize_path(raw_path)
    if not path:
        return None
    return status, path


def working_tree_paths_from_status(status_lines: list[str]) -> list[str]:
    paths = []
    seen = set()
    for line in status_lines:
        parsed = parse_status_line(line)
        if not parsed:
            continue
        _, path = parsed
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def capture_git_snapshot(project_root: Path) -> dict:
    snapshot = {
        "mode": "full_scan_only",
        "git_available": False,
        "repo_root": None,
        "aligned_branch": None,
        "aligned_head_sha": None,
        "aligned_at": None,
        "last_checked_branch": None,
        "last_checked_head_sha": None,
        "last_checked_at": utc_now(),
        "working_tree_dirty": None,
        "status_porcelain": [],
        "last_relation": None,
    }
    if not is_git_repo(project_root):
        return snapshot

    repo_root_result = run_git(project_root, ["rev-parse", "--show-toplevel"])
    head_result = run_git(project_root, ["rev-parse", "HEAD"])
    branch_result = run_git(project_root, ["branch", "--show-current"])
    status_result = run_git(project_root, ["status", "--porcelain"])
    if repo_root_result is None or head_result is None or branch_result is None or status_result is None:
        return snapshot

    status_lines = [line for line in status_result.stdout.splitlines() if line.strip()]
    snapshot.update(
        {
            "mode": "git",
            "git_available": True,
            "repo_root": repo_root_result.stdout.strip() or str(project_root),
            "last_checked_branch": branch_result.stdout.strip() or "(detached)",
            "last_checked_head_sha": head_result.stdout.strip() or None,
            "working_tree_dirty": bool(status_lines),
            "status_porcelain": status_lines,
        }
    )
    return snapshot


def merge_git_state(existing: dict | None, snapshot: dict, *, align_to_current: bool = False, relation: str | None = None) -> dict:
    payload = dict(existing or {})
    payload.update(
        {
            "mode": snapshot.get("mode", "full_scan_only"),
            "git_available": snapshot.get("git_available", False),
            "repo_root": snapshot.get("repo_root"),
            "last_checked_branch": snapshot.get("last_checked_branch"),
            "last_checked_head_sha": snapshot.get("last_checked_head_sha"),
            "last_checked_at": snapshot.get("last_checked_at", utc_now()),
            "working_tree_dirty": snapshot.get("working_tree_dirty"),
            "status_porcelain": list(snapshot.get("status_porcelain", [])),
            "recommended_update_mode": None,
            "recommended_reason": None,
            "scope_summary": None,
            "merge_base_sha": None,
        }
    )
    if relation is not None:
        payload["last_relation"] = relation
    if not snapshot.get("git_available"):
        payload["mode"] = "full_scan_only"
        payload.setdefault("aligned_branch", None)
        payload.setdefault("aligned_head_sha", None)
        payload.setdefault("aligned_at", None)
        return payload
    if align_to_current:
        payload["aligned_branch"] = snapshot.get("last_checked_branch")
        payload["aligned_head_sha"] = snapshot.get("last_checked_head_sha")
        payload["aligned_at"] = utc_now()
        payload["last_relation"] = "aligned"
        payload["recommended_update_mode"] = None
        payload["recommended_reason"] = None
        payload["scope_summary"] = None
        payload["merge_base_sha"] = None
    else:
        payload.setdefault("aligned_branch", None)
        payload.setdefault("aligned_head_sha", None)
        payload.setdefault("aligned_at", None)
    return payload


def is_ancestor(project_root: Path, older: str, newer: str) -> bool:
    result = run_git(project_root, ["merge-base", "--is-ancestor", older, newer], check=False)
    return result is not None and result.returncode == 0


def merge_base(project_root: Path, left: str, right: str) -> str | None:
    result = run_git(project_root, ["merge-base", left, right], check=False)
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def diff_name_only(project_root: Path, revspec: str) -> list[str]:
    result = run_git(project_root, ["diff", "--name-only", revspec], check=False)
    if result is None or result.returncode != 0:
        return []
    paths = []
    seen = set()
    for raw in result.stdout.splitlines():
        path = normalize_path(raw)
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def unique_paths(*groups: list[str]) -> list[str]:
    ordered = []
    seen = set()
    for group in groups:
        for item in group:
            clean = normalize_path(item)
            if clean and clean not in seen:
                seen.add(clean)
                ordered.append(clean)
    return ordered


def classify_impacted_units(changed_paths: list[str], tracked_units: dict) -> tuple[list[str], list[str]]:
    impacted_units = set()
    uncovered_paths = []
    normalized_units: list[tuple[str, str]] = []
    for unit_name, unit_value in tracked_units.items():
        coverage_paths = unit_value if isinstance(unit_value, list) else [unit_name]
        for module_path in coverage_paths:
            module_prefix = module_path.replace("\\", "/").strip("/")
            if module_prefix:
                normalized_units.append((unit_name, module_prefix))
    normalized_units.sort(key=lambda item: (-len(item[1].split("/")), item[1], item[0]))

    for path in changed_paths:
        matched_unit = None
        for unit_name, module_prefix in normalized_units:
            if path == module_prefix or path.startswith(module_prefix + "/"):
                matched_unit = unit_name
                break
        if matched_unit:
            impacted_units.add(matched_unit)
        else:
            uncovered_paths.append(path)
    return sorted(impacted_units), uncovered_paths


def build_change_scope_report(
    changed_paths: list[str],
    tracked_units: dict,
    tracked_paths: list[str],
    *,
    relation: str | None = None,
) -> dict:
    """
    基于变化路径与已登记映射，整理一份维护范围报告。

    输出中的 `recommended_*` 字段表示“当前脚本整理出的维护建议”，
    供当前会话中的 Codex 继续判断，并不代表脚本已经完成最终拍板。
    """
    normalized = unique_paths(changed_paths)
    top_level_paths = sorted({path.split("/", 1)[0] for path in normalized if path})
    tracked_top_levels = {item.replace("\\", "/").strip("/") for item in tracked_paths}
    critical_root_files = sorted([Path(path).name for path in normalized if is_summary_trigger_path(path)])
    impacted_modules, uncovered_paths = classify_impacted_units(normalized, tracked_units)
    new_top_levels = sorted(
        [
            path
            for path in top_level_paths
            if path not in tracked_top_levels and Path(path).suffix == "" and path not in critical_root_files
        ]
    )
    low_semantic_risk_paths = [path for path in normalized if is_low_semantic_risk_path(path)]
    boundary_sensitive_paths = [path for path in normalized if is_boundary_sensitive_path(path)]
    root_dirs = sorted([path for path in normalized if "/" not in path and Path(path).suffix == ""])

    recommended_update_mode = "incremental"
    scope_level = "module"
    requires_human_review = False
    requires_summary_review = False
    requires_structure_review = False
    reasons = []

    if critical_root_files:
        recommended_update_mode = "user_review_required"
        scope_level = "summary"
        requires_human_review = True
        requires_summary_review = True
        reasons.append(f"触及根级项目入口或关键配置：{', '.join(critical_root_files)}。")

    if new_top_levels:
        if recommended_update_mode != "user_review_required":
            recommended_update_mode = "reconcile"
        scope_level = "structure"
        requires_structure_review = True
        reasons.append(f"出现了文档系统尚未跟踪的顶层路径：{', '.join(new_top_levels)}。")

    if uncovered_paths and not requires_summary_review:
        if recommended_update_mode not in {"user_review_required", "reconcile"}:
            recommended_update_mode = "incremental"
        if scope_level != "summary":
            scope_level = "structure"
        requires_structure_review = True
        reasons.append("部分变化尚未落入当前功能域映射，需要复查功能树到代码树映射。")

    if len(normalized) >= RECONCILE_CHANGE_COUNT_THRESHOLD:
        if recommended_update_mode != "user_review_required":
            recommended_update_mode = "reconcile"
        scope_level = "structure" if scope_level != "summary" else scope_level
        requires_structure_review = True
        reasons.append(f"变化文件数达到 {len(normalized)} 个。")
    if len(top_level_paths) >= RECONCILE_TOP_LEVEL_THRESHOLD:
        if recommended_update_mode != "user_review_required":
            recommended_update_mode = "reconcile"
        scope_level = "structure" if scope_level != "summary" else scope_level
        requires_structure_review = True
        reasons.append(f"变化已跨越 {len(top_level_paths)} 个顶层路径。")
    if len(impacted_modules) >= RECONCILE_MODULE_COUNT_THRESHOLD:
        if recommended_update_mode != "user_review_required":
            recommended_update_mode = "reconcile"
        scope_level = "structure" if scope_level != "summary" else scope_level
        requires_structure_review = True
        reasons.append(f"已影响 {len(impacted_modules)} 个已登记模块。")
    if relation == "diverged" and len(normalized) >= 8:
        if recommended_update_mode != "user_review_required":
            recommended_update_mode = "reconcile"
        scope_level = "structure" if scope_level != "summary" else scope_level
        requires_structure_review = True
        reasons.append("当前分支与文档基线已经分叉，且变化范围已超出轻量增量更新。")

    if (
        normalized
        and not requires_human_review
        and not requires_structure_review
        and len(normalized) == len(low_semantic_risk_paths)
        and len(top_level_paths) <= 1
        and len(impacted_modules) <= 1
    ):
        recommended_update_mode = "git_alignment_only"
        scope_level = "git"
        reasons.append("当前变化集中在测试或夹具等低语义风险路径，正文语义大概率仍然成立。")

    if recommended_update_mode == "incremental":
        if boundary_sensitive_paths:
            reasons.append("变化触及现有功能域中的入口或边界文件，建议最小范围更新对应功能域文档。")
        else:
            reasons.append("变化仍集中在有限功能域内，先按最小受影响功能域规划增量更新。")

    if not reasons:
        reasons.append("当前未识别到需要正文更新的结构性信号。")

    return {
        "recommended_update_mode": recommended_update_mode,
        "recommended_reason": " ".join(reasons),
        "changed_paths_count": len(normalized),
        "top_level_paths": top_level_paths,
        "scope_level": scope_level,
        "impacted_modules": impacted_modules,
        "new_top_levels": new_top_levels,
        "critical_root_files": critical_root_files,
        "uncovered_paths": uncovered_paths,
        "low_semantic_risk_paths": low_semantic_risk_paths,
        "boundary_sensitive_paths": boundary_sensitive_paths,
        "requires_human_review": requires_human_review,
        "requires_summary_review": requires_summary_review,
        "requires_structure_review": requires_structure_review,
        "root_dirs": root_dirs,
        "judgment_prompt": (
            "请基于当前变化路径、变化广度、是否触及根级上下文证据、"
            "以及是否仍落在现有功能域映射内，判断这次维护应该走 "
            "`git_alignment_only`、`content_update`、`reconcile` 还是 `user_review_required`。"
        ),
    }


def assess_change_scope(
    changed_paths: list[str],
    tracked_units: dict,
    tracked_paths: list[str],
    *,
    relation: str | None = None,
) -> dict:
    """兼容旧调用名，实际返回维护范围报告。"""
    return build_change_scope_report(
        changed_paths,
        tracked_units,
        tracked_paths,
        relation=relation,
    )


def format_scope_summary(scope: dict) -> str:
    parts = [
        f"变化文件 {scope.get('changed_paths_count', 0)} 个",
        f"顶层路径 {len(scope.get('top_level_paths', []))} 个",
        f"已登记功能域 {len(scope.get('impacted_modules', []))} 个",
    ]
    if scope.get("new_top_levels"):
        parts.append(f"新顶层路径：{', '.join(scope['new_top_levels'])}")
    if scope.get("critical_root_files"):
        parts.append(f"关键根级文件：{', '.join(scope['critical_root_files'])}")
    return "；".join(parts)


def explain_alignment(project_root: Path, recorded_head: str | None, snapshot: dict) -> tuple[str, list[str], str, str | None]:
    """
    解释当前 checkout 与文档对齐点的关系，并给出变更路径输入。

    返回值用于后续维护建议整理，不应被理解为已经完成正文更新决策。
    """
    if not snapshot.get("git_available"):
        return "no_git", [], "当前项目未检测到可用的 git 工作区。", None

    current_head = snapshot.get("last_checked_head_sha")
    working_tree_paths = working_tree_paths_from_status(snapshot.get("status_porcelain", []))
    if not recorded_head:
        return "no_alignment", working_tree_paths, "文档系统还没有记录已对齐的 commit，需要先做一次收敛建立基线。", None
    if not current_head:
        return "no_head", working_tree_paths, "当前 git 状态缺少 HEAD，无法比较文档对齐点。", None
    if current_head == recorded_head:
        if working_tree_paths:
            return "same_head_dirty", working_tree_paths, "当前 HEAD 与文档对齐点一致，但工作区存在未提交变化。", None
        return "same_head_clean", [], "当前 HEAD 与文档对齐点一致，且工作区干净。", None
    if is_ancestor(project_root, recorded_head, current_head):
        committed_paths = diff_name_only(project_root, f"{recorded_head}..{current_head}")
        paths = unique_paths(committed_paths, working_tree_paths)
        return "current_ahead", paths, "当前 HEAD 领先于文档对齐点，应按新增提交与工作区变化规划文档更新。", recorded_head
    if is_ancestor(project_root, current_head, recorded_head):
        return "current_behind", [], "当前 checkout 早于文档对齐点，默认不自动回写文档。", recorded_head
    base = merge_base(project_root, recorded_head, current_head)
    if base:
        committed_paths = diff_name_only(project_root, f"{base}..{current_head}")
        paths = unique_paths(committed_paths, working_tree_paths)
        return "diverged", paths, "当前 HEAD 与文档对齐点已经分叉，应按当前分支相对共同祖先的变化重新评估文档。", base
    return "unrelated", working_tree_paths, "无法找到共同祖先，建议下沉到全量阅读并执行收敛。", None
