#!/usr/bin/env python3
"""
确认项目级 summary，使其成为后续结构分析和模块生成的认知基线。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.shared.git_tracking import capture_git_snapshot, merge_git_state
from scripts.shared.workflow_state import ensure_workflow_state, mark_summary_confirmed
from scripts.features.bootstrap.init_project_docs import normalize_doc_root


SKILL_NAME = "auto-document"
SKILL_VERSION = "0.4.0"
DOC_SCHEMA_VERSION = "2.0.0"


def load_index(doc_root: Path) -> tuple[Path, dict]:
    index_path = doc_root / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"在 {index_path} 未找到 index.json。请先初始化文档。")
    return index_path, json.loads(index_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="确认项目级 summary。")
    parser.add_argument("--project-root", required=True, help="仓库根目录。")
    parser.add_argument("--doc-root", help="文档根目录。默认使用 <project-root>/project-docs。")
    parser.add_argument("--confirmed-by", default="user", help="确认者标识，默认 user。")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    doc_root = normalize_doc_root(project_root, args.doc_root).resolve()
    index_path, index_payload = load_index(doc_root)
    ensure_workflow_state(index_payload)

    summary_path = doc_root / "overview" / "project-summary.md"
    if not summary_path.exists():
        raise FileNotFoundError(f"未找到 summary 文档：{summary_path}")

    git_snapshot = capture_git_snapshot(project_root)
    index_payload["skill_name"] = SKILL_NAME
    index_payload["skill_version"] = SKILL_VERSION
    index_payload["doc_schema_version"] = DOC_SCHEMA_VERSION
    mark_summary_confirmed(index_payload, git_snapshot, confirmed_by=args.confirmed_by)
    generated = set(index_payload.get("generated_docs", []))
    generated.add("overview/project-summary.md")
    index_payload["generated_docs"] = sorted(generated)
    index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot)
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[完成] 已确认 summary：{summary_path}")
    print("[下一步] 现在可以继续建立 `overview/project-structure.md`。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
