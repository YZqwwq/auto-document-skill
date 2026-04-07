#!/usr/bin/env python3
"""
为 auto-document skill 初始化分层项目文档根目录。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from git_tracking import capture_git_snapshot, merge_git_state


SKILL_NAME = "auto-document"
SKILL_VERSION = "0.3.0"
DOC_SCHEMA_VERSION = "1.2.0"
DEFAULT_DOC_DIR = "project-docs"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_doc_root(project_root: Path, doc_root: str | None) -> Path:
    if doc_root:
        candidate = Path(doc_root)
        return candidate if candidate.is_absolute() else (project_root / candidate)
    return project_root / DEFAULT_DOC_DIR


def ensure_text_file(path: Path, content: str, force: bool = False) -> None:
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_index(project_root: Path, doc_root: Path) -> dict:
    git_snapshot = capture_git_snapshot(project_root)
    return {
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "doc_schema_version": DOC_SCHEMA_VERSION,
        "project_root": str(project_root),
        "doc_root": str(doc_root),
        "initialized": True,
        "initialized_at": utc_now(),
        "last_scan_at": None,
        "analysis_round": 0,
        "generated_docs": [
            "README.md",
            "overview/project-summary.md",
            "overview/project-structure.md",
            "modules/README.md",
            "history/analysis-log.md",
            "history/change-log.md",
        ],
        "tracked_paths": [],
        "round_two_targets": [],
        "architecture_domains": [],
        "module_docs": {},
        "pending_updates": [],
        "history_files": {
            "analysis_log": "history/analysis-log.md",
            "change_log": "history/change-log.md",
        },
        "git_state": merge_git_state({}, git_snapshot),
    }


def read_existing_index(index_path: Path) -> dict | None:
    if not index_path.exists():
        return None
    return json.loads(index_path.read_text(encoding="utf-8"))


def write_index(index_path: Path, payload: dict, force: bool = False) -> None:
    if index_path.exists() and not force:
        return
    index_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化分层项目文档。")
    parser.add_argument("--project-root", required=True, help="需要建立文档的仓库根目录。")
    parser.add_argument("--doc-root", help="文档根目录。默认使用 <project-root>/project-docs。")
    parser.add_argument(
        "--force-stubs",
        action="store_true",
        help="如果 markdown 骨架文件已存在，则重新写入。",
    )
    parser.add_argument(
        "--force-index",
        action="store_true",
        help="即使 index.json 已存在，也强制重写。",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    doc_root = normalize_doc_root(project_root, args.doc_root).resolve()
    index_path = doc_root / "index.json"

    existing_index = read_existing_index(index_path)
    if existing_index and existing_index.get("initialized") and not args.force_index:
        print(f"[跳过] 文档根目录已初始化：{doc_root}")
        print("[说明] index.json 显示 initialized=true，因此没有重新创建默认骨架。")
        return 0

    doc_root.mkdir(parents=True, exist_ok=True)
    (doc_root / "overview").mkdir(exist_ok=True)
    (doc_root / "modules").mkdir(exist_ok=True)
    (doc_root / "history").mkdir(exist_ok=True)

    readme = """# 项目文档

这个目录存放由 `auto-document` skill 维护的分层项目文档，用于帮助人和 AI 快速理解项目当前状态。

## 项目当前在做什么

待补充：用 1 到 3 句话说明这个项目当前在做什么、主要面向谁、为什么需要继续维护这些功能域文档。

## 这份目录怎么用

- 先读 `overview/project-summary.md`，确认项目是什么
- 再读 `overview/project-structure.md`，确认整体结构和阅读顺序
- 再读 `modules/README.md`，按功能域继续下沉
- 当你需要查看维护状态时，再读 `history/analysis-log.md` 和 `history/change-log.md`

## 按问题找文档

- 想先知道项目到底在解决什么：读 `overview/project-summary.md`
- 想先知道仓库应该从哪里开始进入：读 `overview/project-structure.md`
- 想先理解项目有哪些功能域：进入 `modules/README.md`
- 想知道文档系统当前对齐到了什么状态：看 `index.json`

## 文档职责

- `index.json`
  供后续文档运行使用的机器可读状态
- `overview/`
  项目整体理解与结构导航
- `modules/`
  第二轮功能域与专题域文档
- `history/`
  分析与更新轨迹
"""

    project_summary = """# 项目摘要

## 项目定位

待补充：用 1 到 3 句话说明这个项目当前在做什么、主要面向谁。

## 项目目标

待补充：说明项目当前最重要的目标、问题域和维护重点。

## 架构理念

- 先说明项目应该按哪些功能域理解，而不是按目录树理解
- 先给人类读者推荐阅读路径，再补充 AI 快速入口

## 第一层功能域

待补充

## 第二层专题域

待补充

## 推荐阅读方式

- 先读这份 `project-summary.md`
- 再读 `modules/README.md`
- 如果需要快速扫路径，再读 `project-structure.md`
"""

    project_structure = """# 项目结构

## 文档定位

这是一份偏 AI 使用的结构快照，用来在短时间内扫过大量路径、目录层级和功能域映射。

## 这份文档适合什么时候看

- 需要快速确认仓库里有哪些关键路径
- 需要把目录树和功能域做一次快速对照
- 需要让 AI 在短时间内建立路径地图

## 顶层目录树

```text
待补充
```

## 顶层路径说明

待补充

## 功能域快照

待补充

## 当前推荐继续下钻的专题

待补充
"""

    modules_readme = """# 模块文档

这个目录只负责两层事情：先解释项目有哪些第一层功能域，再解释每个功能域下有哪些第二层专题域。

## 这份文档怎么用

- 先看第一层功能域，建立项目的大体功能分层
- 再按问题进入对应的第二层专题域
- 如果问题已经落到具体实现链，继续去专题域 README 或叶子文档，不要在这里停留

## 当前模块文档

_暂时为空。_

## 建议下一步

运行结构扫描与收敛脚本后，这里会自动登记功能域文档。
"""

    analysis_log = """# 分析日志

## 记录

- 待补充：为每一轮总览分析或模块分析记录时间戳和简短范围说明。
"""

    change_log = """# 变更日志

## 记录

- 待补充：记录由代码变更触发的文档更新和待处理计划。
"""

    ensure_text_file(doc_root / "README.md", readme, force=args.force_stubs)
    ensure_text_file(doc_root / "overview" / "project-summary.md", project_summary, force=args.force_stubs)
    ensure_text_file(doc_root / "overview" / "project-structure.md", project_structure, force=args.force_stubs)
    ensure_text_file(doc_root / "modules" / "README.md", modules_readme, force=args.force_stubs)
    ensure_text_file(doc_root / "history" / "analysis-log.md", analysis_log, force=args.force_stubs)
    ensure_text_file(doc_root / "history" / "change-log.md", change_log, force=args.force_stubs)

    index_payload = build_index(project_root, doc_root)
    write_index(index_path, index_payload, force=args.force_index or not index_path.exists())

    print(f"[完成] 已初始化文档根目录：{doc_root}")
    print(f"[完成] 已创建或确认索引：{index_path}")
    if index_payload.get("git_state", {}).get("git_available"):
        branch = index_payload["git_state"].get("last_checked_branch") or "(detached)"
        head = index_payload["git_state"].get("last_checked_head_sha") or "unknown"
        print(f"[完成] 已记录当前 git 状态：{branch} @ {head}")
    else:
        print("[提示] 当前项目未检测到 git。后续若需要 git 感知更新，请先安装并初始化 git；否则请使用全量扫描/收敛工作流。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
