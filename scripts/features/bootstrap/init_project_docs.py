#!/usr/bin/env python3
"""
为 auto-document skill 初始化分层项目文档根目录。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.shared.git_tracking import capture_git_snapshot, merge_git_state
from scripts.shared.workflow_state import default_module_state, default_structure_state, default_summary_state


SKILL_NAME = "auto-document"
SKILL_VERSION = "0.4.0"
DOC_SCHEMA_VERSION = "2.0.0"
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
    summary_state = default_summary_state()
    structure_state = default_structure_state()
    module_state = default_module_state()
    structure_state["status"] = "blocked_by_summary"
    module_state["status"] = "blocked_by_summary"
    return {
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "doc_schema_version": DOC_SCHEMA_VERSION,
        "project_root": str(project_root),
        "doc_root": str(doc_root),
        "initialized": True,
        "initialized_at": utc_now(),
        "last_scan_at": None,
        "last_reconciled_at": None,
        "workflow_phase": "initialized",
        "analysis_round": 0,
        "summary_state": summary_state,
        "structure_state": structure_state,
        "module_state": module_state,
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
        "domain_analysis": {},
        "summary_analysis": {},
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

    readme = f"""# 项目文档

这份目录用于维护 `{project_root.name}` 的项目文档系统。这里主要说明固定文件和文件夹各自承担什么职责，帮助维护者快速判断应该去哪里阅读、补充或更新。

## 建议先读哪里

- 第一次接手时，先生成并确认 `overview` 下的 `project-summary.md`
- summary 确认后，再建立 `overview` 下的 `project-structure.md`
- 只有 summary 和 structure 都建立后，才继续进入 `modules` 下的 `README.md`
- 如果需要查看维护状态，再读 `history` 和 `index.json`

## 固定文件与文件夹的作用

```text
overview
|-- project-summary.md    项目级意图基线；先由 AI 生成草案，再由用户确认，后续 structure 和 modules 都以它为准
|-- project-structure.md  在 summary 确认后建立的结构责任树，用于解释技术栈默认目录和项目自己的功能边界

modules
|-- README.md             功能域总入口；只在 summary 和 structure 都建立后再正式生成

history
|-- analysis-log.md       记录每一轮分析、收敛或人工补充
|-- change-log.md         记录由代码变化触发的文档更新规划和影响范围

index.json                文档系统的机器可读控制面，记录工作流阶段、人类确认基线、功能域索引、待处理更新项和 git 对齐状态
```

## 文档职责

- `overview` 负责项目级理解和结构责任树
- `modules` 负责功能域级理解
- `history` 负责维护轨迹
- `index.json` 负责机器可读状态
"""

    project_summary = """# 项目摘要

## 文档状态

待生成：请先执行 summary 草案阶段。  
这份文档应先由 AI 生成一版草案，再由用户补充、修正并确认，之后才能作为后续 structure 和 modules 的认知基线。

## 项目定位

待补充：用 1 到 3 句话说明这个项目当前在做什么、最终希望成为什么，以及主要面向谁。

## 当前阶段与目标

待补充：说明当前已稳定的实现、正在演进的部分，以及当前阶段最重要的目标。

## 目标用户与使用场景

待补充

## 技术栈与运行形态

待补充：说明当前项目的主要技术栈、运行时形态和关键依赖边界。

## 当前稳定设计判断

待补充：说明哪些设计原则已经稳定，哪些只是阶段性实现。

## 后续文档生成规则

- 先确认这份 `project-summary.md`
- 再建立 `project-structure.md`
- 最后再生成 `modules/`
"""

    project_structure = """# 项目结构

## 文档状态

待生成：只有在 `project-summary.md` 被用户确认后，才建立这份结构责任树。

## 文档定位

这是一份偏 AI 和维护者使用的结构责任树，用来解释技术栈默认目录语义、项目当前真实路径，以及这些路径如何映射成功能责任树。

## 这份文档适合什么时候看

- summary 已确认，需要开始建立结构责任树
- 需要区分框架默认目录和项目自定义责任
- 需要把路径树映射到功能域，再为 modules 做准备

## 技术栈与默认目录语义

待补充

## 顶层目录树与路径快照

```text
待补充
```

## 当前责任树

待补充

## 当前推荐继续下钻的专题

待补充
"""

    modules_readme = """# 模块文档

这里按当前项目的功能架构列出第一层功能域，以及已经单独拆出的第二层专题域。

## 这份文档怎么用

- 先确认 `project-summary.md` 和 `project-structure.md` 已经建立
- 再按第一层功能域判断问题落在哪一层
- 如果已经拆出第二层专题域，再继续下钻到对应专题

## 当前功能架构

- 待补充：只有在 summary 和 structure 都建立后，这里才会生成正式功能架构图。

## 继续下钻时的原则

- 这份索引只负责回答“先从哪一块进入”
- 当问题已经落到具体实现链时，直接进入对应 README 或叶子文档
- 如果结构说明和代码冲突，以代码为准，再回头更新文档
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
