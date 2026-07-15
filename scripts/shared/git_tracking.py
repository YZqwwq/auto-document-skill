#!/usr/bin/env python3
"""Minimal git state capture for auto-document initialization."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_git(project_root: Path, args: list[str], check: bool = False) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", "-C", str(project_root), *args],
            capture_output=True,
            text=True,
            check=check,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def is_git_repo(project_root: Path) -> bool:
    result = run_git(project_root, ["rev-parse", "--is-inside-work-tree"])
    return bool(result and result.returncode == 0 and result.stdout.strip().lower() == "true")


def capture_git_snapshot(project_root: Path) -> dict:
    snapshot = {
        "git_available": False,
        "repo_root": None,
        "last_checked_branch": None,
        "last_checked_head_sha": None,
        "last_checked_at": utc_now(),
        "working_tree_dirty": None,
        "status_porcelain": [],
    }
    if not is_git_repo(project_root):
        return snapshot

    repo_root = run_git(project_root, ["rev-parse", "--show-toplevel"])
    head = run_git(project_root, ["rev-parse", "HEAD"])
    branch = run_git(project_root, ["branch", "--show-current"])
    status = run_git(project_root, ["status", "--porcelain"])
    if not repo_root or not head or not branch or not status:
        return snapshot

    status_lines = [line for line in status.stdout.splitlines() if line.strip()]
    snapshot.update(
        {
            "git_available": True,
            "repo_root": repo_root.stdout.strip() or str(project_root),
            "last_checked_branch": branch.stdout.strip() or "(detached)",
            "last_checked_head_sha": head.stdout.strip() or None,
            "working_tree_dirty": bool(status_lines),
            "status_porcelain": status_lines,
        }
    )
    return snapshot
