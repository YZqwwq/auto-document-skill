#!/usr/bin/env python3
"""
在代码变更后规划文档的增量更新。
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
    mark_hold,
    mark_structure_stale,
    mark_summary_stale,
    summary_gate_message,
    summary_is_confirmed,
)

DEFAULT_DOC_DIR = "project-docs"
SKILL_NAME = "auto-document"
SKILL_VERSION = "0.3.0"
DOC_SCHEMA_VERSION = "1.2.0"
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
SUMMARY_TRIGGER_FILES = {
    "README.md",
    "ARCHITECTURE.md",
    "architecture.md",
    "SYSTEM.md",
    "system.md",
    "DESIGN.md",
    "design.md",
    "CONTRIBUTING.md",
}
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


def filter_tooling_only_changes(paths: list[str]) -> list[str]:
    filtered = []
    for path in paths:
        clean = path.replace("\\", "/").strip("/")
        if "/" not in clean and Path(clean).name in IGNORED_ROOT_TOOLING_FILES:
            continue
        filtered.append(clean)
    return filtered


def build_domain_coverage(index_payload: dict) -> dict[str, list[str]]:
    coverage = {}
    for domain in index_payload.get("architecture_domains", []):
        domain_id = domain.get("id")
        paths = [item.replace("\\", "/").strip("/") for item in domain.get("paths", []) if item]
        if domain_id and paths:
            coverage[domain_id] = paths
    return coverage


def collect_impacted_docs(
    changed_path: str,
    module_docs: dict,
    tracked_paths: list[str],
    architecture_domains: list[dict] | None = None,
) -> tuple[list[str], str]:
    docs = set()
    reasons = []
    normalized = changed_path.replace("\\", "/").strip("/")
    path_parts = normalized.split("/") if normalized else []

    architecture_domains = architecture_domains or []
    matching_domains = []
    if architecture_domains:
        for domain in architecture_domains:
            doc_rel = module_docs.get(domain.get("id"), domain.get("doc_path"))
            if not doc_rel:
                continue
            for domain_path in domain.get("paths", []):
                module_prefix = domain_path.replace("\\", "/").strip("/")
                if normalized == module_prefix or normalized.startswith(module_prefix + "/"):
                    matching_domains.append((module_prefix.count("/"), doc_rel, domain["title"], module_prefix))
        matching_domains.sort(reverse=True)
        if matching_domains:
            _, doc_rel, domain_title, module_prefix = matching_domains[0]
            docs.add(doc_rel)
            reasons.append(f"匹配到功能域 `{domain_title}` 覆盖的路径 `{module_prefix}`。")
    else:
        matching_modules = []
        for module_path, doc_rel in module_docs.items():
            module_prefix = module_path.replace("\\", "/").strip("/")
            if normalized == module_prefix or normalized.startswith(module_prefix + "/"):
                matching_modules.append((module_prefix.count("/"), doc_rel, module_prefix))
        matching_modules.sort(reverse=True)
        if matching_modules:
            _, doc_rel, module_prefix = matching_modules[0]
            docs.add(doc_rel)
            reasons.append(f"匹配到已登记的模块路径 `{module_prefix}`。")

    if len(path_parts) == 1:
        docs.add(STRUCTURE_DOC)
        reasons.append("触及根级路径，因此需要复查顶层结构。")

    if path_parts and path_parts[0] not in tracked_paths:
        docs.add(STRUCTURE_DOC)
        docs.add(MODULE_INDEX_DOC)
        reasons.append("引入或触及了文档索引尚未跟踪的路径。")

    if path_parts and path_parts[0] == "project-docs":
        reasons.append("变化已经发生在文档根目录内部。")

    if Path(normalized).name in SUMMARY_TRIGGER_FILES:
        docs.add(SUMMARY_DOC)
        reasons.append("触及根级配置文件，可能会改变项目摘要。")

    if not docs:
        docs.add(SUMMARY_DOC)
        reasons.append("没有找到直接匹配的功能域，因此需要复查项目总览摘要。")

    return sorted(docs), " ".join(reasons)


def append_change_log(change_log_path: Path, entries: list[dict]) -> None:
    if not entries:
        return
    lines = ["", f"## {utc_now()}", ""]
    for entry in entries:
        docs_text = ", ".join(entry["docs"])
        lines.append(f"- `{entry['changed_path']}` -> {docs_text}")
        lines.append(f"  原因：{entry['reason']}")
    with change_log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def remember_scope(index_payload: dict, scope: dict, merge_base_sha: str | None = None) -> None:
    git_state = dict(index_payload.get("git_state", {}))
    git_state["recommended_update_mode"] = scope.get("recommended_update_mode")
    git_state["recommended_reason"] = scope.get("recommended_reason")
    git_state["scope_summary"] = format_scope_summary(scope)
    git_state["merge_base_sha"] = merge_base_sha
    index_payload["git_state"] = git_state


def clear_scope(index_payload: dict, merge_base_sha: str | None = None) -> None:
    git_state = dict(index_payload.get("git_state", {}))
    git_state["recommended_update_mode"] = None
    git_state["recommended_reason"] = None
    git_state["scope_summary"] = None
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


def summary_review_reason(changed_paths: list[str], scope: dict) -> str | None:
    root_changes = [path for path in changed_paths if "/" not in path]
    summary_roots = [path for path in root_changes if Path(path).name in SUMMARY_TRIGGER_FILES or Path(path).name in IGNORED_ROOT_TOOLING_FILES]
    if summary_roots:
        return f"根级项目入口或关键配置发生变化：{', '.join(summary_roots)}。"
    if scope.get("new_top_levels"):
        return f"出现了新的顶层路径：{', '.join(scope['new_top_levels'])}。"
    return None


def structure_review_reason(changed_paths: list[str], scope: dict) -> str | None:
    top_level_paths = scope.get("top_level_paths", [])
    root_dirs = [path for path in changed_paths if "/" not in path and Path(path).suffix == ""]
    if root_dirs:
        return f"顶层目录发生变化：{', '.join(root_dirs)}。"
    if len(top_level_paths) >= 2:
        return f"变化已跨越多个顶层路径：{', '.join(top_level_paths)}。"
    return None


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

    if args.git_status:
        if not git_snapshot.get("git_available"):
            print("[提示] 当前项目未检测到 git。若要使用 git 感知，请先安装并初始化 git；否则请下沉到全量阅读项目并执行 reconcile。")
        else:
            changed_paths.extend(
                filter_tooling_only_changes(
                    filter_doc_root_changes(working_tree_paths_from_status(git_snapshot.get("status_porcelain", [])), doc_root_rel)
                )
            )
            alignment_message = "本轮依据当前 git 工作区未提交变化规划文档更新。"

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
        changed_paths.extend(filter_tooling_only_changes(filter_doc_root_changes(sensed_paths, doc_root_rel)))

    normalized_changed = []
    seen = set()
    for item in filter_tooling_only_changes(changed_paths):
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

    module_docs = dict(index_payload.get("module_docs", {}))
    architecture_domains = list(index_payload.get("architecture_domains", []))
    domain_coverage = build_domain_coverage(index_payload)
    tracked_paths = list(index_payload.get("tracked_paths", []))
    relation = index_payload.get("git_state", {}).get("last_relation")
    scope = None
    if normalized_changed:
        scope = assess_change_scope(normalized_changed, domain_coverage or module_docs, tracked_paths, relation=relation)
        remember_scope(index_payload, scope, merge_base_sha=index_payload.get("git_state", {}).get("merge_base_sha"))
        if relation == "diverged":
            print_diverged_notice(index_payload.get("git_state", {}), git_snapshot, scope, index_payload.get("git_state", {}).get("merge_base_sha"))
        summary_reason = summary_review_reason(normalized_changed, scope)
        structure_reason = structure_review_reason(normalized_changed, scope)
        if summary_reason:
            mark_summary_stale(index_payload, reason=summary_reason)
        elif structure_reason:
            mark_structure_stale(index_payload, reason=structure_reason)
    else:
        clear_scope(index_payload, merge_base_sha=index_payload.get("git_state", {}).get("merge_base_sha"))
    entries = []
    for changed_path in normalized_changed:
        docs, reason = collect_impacted_docs(changed_path, module_docs, tracked_paths, architecture_domains)
        if index_payload.get("summary_state", {}).get("status") == "stale":
            docs = sorted(set(docs + [SUMMARY_DOC, STRUCTURE_DOC, MODULE_INDEX_DOC]))
            reason = f"{reason} 项目级 summary 需要重新确认。"
        elif index_payload.get("structure_state", {}).get("status") == "stale":
            docs = sorted(set(docs + [STRUCTURE_DOC, MODULE_INDEX_DOC]))
            reason = f"{reason} 结构责任树需要重新建立。"
        entries.append(
            {
                "planned_at": utc_now(),
                "changed_path": changed_path,
                "docs": docs,
                "reason": reason,
            }
        )

    if alignment_message and not entries:
        print(f"[提示] {alignment_message}")

    index_payload["pending_updates"] = entries
    index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot, relation=index_payload.get("git_state", {}).get("last_relation"))
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    append_change_log(doc_root / "history" / "change-log.md", entries)

    for entry in entries:
        print(f"[规划] {entry['changed_path']}")
        print(f"       文档：{', '.join(entry['docs'])}")
        print(f"       原因：{entry['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
