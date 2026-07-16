#!/usr/bin/env python3
"""
Initialize the minimal auto-document workspace.

This script intentionally does not generate project plans, module templates,
summary files, or structure documents. It only records the project description,
creates an empty document folder, and writes an AI-readable index.md.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.shared.git_tracking import capture_git_snapshot


DEFAULT_DOC_DIR = "project-docs"
MAX_PROJECT_DESCRIPTION_CHARS = 200


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_doc_root(project_root: Path, doc_root: str | None) -> Path:
    if doc_root:
        candidate = Path(doc_root)
        return candidate if candidate.is_absolute() else project_root / candidate
    return project_root / DEFAULT_DOC_DIR


def read_project_description(args: argparse.Namespace) -> str:
    if args.project_description and args.project_description_file:
        raise ValueError("只能提供 --project-description 或 --project-description-file 其中一个。")
    if args.project_description_file:
        text = Path(args.project_description_file).read_text(encoding="utf-8").strip()
    else:
        text = (args.project_description or "").strip()
    if not text:
        raise ValueError("初始化前需要先由用户提供项目用途说明。")
    if len(text) > MAX_PROJECT_DESCRIPTION_CHARS:
        raise ValueError(f"项目用途说明不能超过 {MAX_PROJECT_DESCRIPTION_CHARS} 字。")
    return text


def compact_git_snapshot(project_root: Path) -> dict:
    snapshot = capture_git_snapshot(project_root)
    return {
        "available": bool(snapshot.get("git_available")),
        "repo_root": snapshot.get("repo_root"),
        "branch": snapshot.get("last_checked_branch"),
        "head_sha": snapshot.get("last_checked_head_sha"),
        "working_tree_dirty": snapshot.get("working_tree_dirty"),
        "status_porcelain": list(snapshot.get("status_porcelain", [])),
        "recorded_at": snapshot.get("last_checked_at") or utc_now(),
    }


def render_index(project_root: Path) -> str:
    initialized_at = utc_now()
    git = compact_git_snapshot(project_root)
    dirty_text = "有未提交变化" if git["working_tree_dirty"] else "干净"
    if git["working_tree_dirty"] is None:
        dirty_text = "未知"
    git_available = "是" if git["available"] else "否"
    git_json = json.dumps(git, indent=2, ensure_ascii=False)
    return f"""# 项目文档索引

## 项目用途

见 `project-description.md`。

## 最近 git 记录

- git 可用：{git_available}
- 仓库：{git["repo_root"] or "未检测到"}
- 分支：{git["branch"] or "未检测到"}
- 提交：{git["head_sha"] or "未检测到"}
- 工作区：{dirty_text}
- 记录时间：{git["recorded_at"]}

```json
{git_json}
```

## 当前阅读进度

已经完成：
- 已初始化文档工作区。
- 已创建 `index.md`、`project-description.md` 和空的 `document/`。

接下来：
- 浅层阅读项目入口和已有文档。
- 提出大功能模块，并请求用户确认。

## 大功能模块

- 待确认

## 最近一次阅读记录

### {initialized_at} 初始化

已经干了什么：
- 为 `{project_root.name}` 创建最小项目文档工作区。
- 记录了本次初始化时的 git 位置。

还要干什么：
- 阅读项目入口，提出大功能模块。
- 用户确认大功能模块后，再为每个模块创建目录和干净的 `catalog.md`。

记录规则：
- 这里以后只保留最近一次阅读记录，不继续追加历史记录。
- 每次继续阅读时，直接覆盖本节内容，并同步更新“当前阅读进度”。
"""


def write_project_description(path: Path, description: str, *, force: bool) -> None:
    if path.exists() and not force:
        return
    path.write_text(description.rstrip() + "\n", encoding="utf-8")


def write_index(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        return
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 auto-document 最小文档工作区。")
    parser.add_argument("--project-root", required=True, help="需要建立文档的项目根目录。")
    parser.add_argument("--doc-root", help="文档根目录。默认使用 <project-root>/project-docs。")
    parser.add_argument("--project-description", help="用户提供的项目用途说明，不超过 200 字。")
    parser.add_argument("--project-description-file", help="从文件读取项目用途说明。")
    parser.add_argument("--force", action="store_true", help="允许覆盖 index.md 和 project-description.md。")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    doc_root = normalize_doc_root(project_root, args.doc_root).resolve()
    try:
        description = read_project_description(args)
    except ValueError as error:
        print(f"[错误] {error}")
        return 2

    index_path = doc_root / "index.md"
    description_path = doc_root / "project-description.md"
    document_root = doc_root / "document"

    if index_path.exists() and not args.force:
        print(f"[跳过] 文档工作区已存在：{doc_root}")
        print("[说明] 如需重新初始化，请使用 --force。")
        return 0

    doc_root.mkdir(parents=True, exist_ok=True)
    document_root.mkdir(parents=True, exist_ok=True)

    write_project_description(description_path, description, force=args.force)
    write_index(index_path, render_index(project_root), force=args.force or not index_path.exists())

    print(f"[完成] 已初始化文档工作区：{doc_root}")
    print(f"[完成] 已写入项目用途说明：{description_path}")
    print(f"[完成] 已创建空文档目录：{document_root}")
    print(f"[完成] 已记录 AI 阅读索引：{index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
