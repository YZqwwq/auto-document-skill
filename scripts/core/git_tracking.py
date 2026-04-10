#!/usr/bin/env python3
"""
为 auto-document 提供 git 感知与对齐状态判断能力。
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

RECONCILE_CHANGE_COUNT_THRESHOLD = 20
RECONCILE_MODULE_COUNT_THRESHOLD = 3
RECONCILE_TOP_LEVEL_THRESHOLD = 2
IGNORED_ROOT_TOOLING_FILES = {
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
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
    clean = normalize_path(path)
    return "/" not in clean and Path(clean).name in IGNORED_ROOT_TOOLING_FILES


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


def assess_change_scope(
    changed_paths: list[str],
    tracked_units: dict,
    tracked_paths: list[str],
    *,
    relation: str | None = None,
) -> dict:
    normalized = [path for path in unique_paths(changed_paths) if not is_ignored_root_tooling_path(path)]
    top_level_paths = sorted({path.split("/", 1)[0] for path in normalized if path})
    tracked_top_levels = {item.replace("\\", "/").strip("/") for item in tracked_paths}
    impacted_modules = set()
    for path in normalized:
        for unit_name, unit_value in tracked_units.items():
            coverage_paths = unit_value if isinstance(unit_value, list) else [unit_name]
            for module_path in coverage_paths:
                module_prefix = module_path.replace("\\", "/").strip("/")
                if path == module_prefix or path.startswith(module_prefix + "/"):
                    impacted_modules.add(unit_name)
                    break
    new_top_levels = sorted([path for path in top_level_paths if path not in tracked_top_levels])

    recommended_update_mode = "incremental"
    reasons = []
    if len(normalized) >= RECONCILE_CHANGE_COUNT_THRESHOLD:
        recommended_update_mode = "reconcile"
        reasons.append(f"变化文件数达到 {len(normalized)} 个。")
    if len(top_level_paths) >= RECONCILE_TOP_LEVEL_THRESHOLD:
        recommended_update_mode = "reconcile"
        reasons.append(f"变化已跨越 {len(top_level_paths)} 个顶层路径。")
    if len(impacted_modules) >= RECONCILE_MODULE_COUNT_THRESHOLD:
        recommended_update_mode = "reconcile"
        reasons.append(f"已影响 {len(impacted_modules)} 个已登记模块。")
    if new_top_levels:
        recommended_update_mode = "reconcile"
        reasons.append(f"出现了文档系统尚未跟踪的顶层路径：{', '.join(new_top_levels)}。")
    if relation == "diverged" and len(normalized) >= 8:
        recommended_update_mode = "reconcile"
        reasons.append("当前分支与文档基线已经分叉，且变化范围已超出轻量增量更新。")

    if not reasons:
        reasons.append("变化仍集中在有限路径内，适合先走增量更新。")

    return {
        "recommended_update_mode": recommended_update_mode,
        "recommended_reason": " ".join(reasons),
        "changed_paths_count": len(normalized),
        "top_level_paths": top_level_paths,
        "impacted_modules": sorted(impacted_modules),
        "new_top_levels": new_top_levels,
        "critical_root_files": [],
    }


def format_scope_summary(scope: dict) -> str:
    parts = [
        f"变化文件 {scope.get('changed_paths_count', 0)} 个",
        f"顶层路径 {len(scope.get('top_level_paths', []))} 个",
        f"已登记功能域 {len(scope.get('impacted_modules', []))} 个",
    ]
    if scope.get("new_top_levels"):
        parts.append(f"新顶层路径：{', '.join(scope['new_top_levels'])}")
    return "；".join(parts)


def explain_alignment(project_root: Path, recorded_head: str | None, snapshot: dict) -> tuple[str, list[str], str, str | None]:
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
