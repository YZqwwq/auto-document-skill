#!/usr/bin/env python3
"""
生成项目级 summary 草案，并等待用户确认。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.git_tracking import capture_git_snapshot, merge_git_state
from core.workflow_state import ensure_workflow_state, mark_summary_drafted
from entrypoints.init_project_docs import normalize_doc_root
from generation.create_module_doc import detect_project_traits


SKILL_NAME = "auto-document"
SKILL_VERSION = "0.4.0"
DOC_SCHEMA_VERSION = "2.0.0"


def load_index(doc_root: Path) -> tuple[Path, dict]:
    index_path = doc_root / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"在 {index_path} 未找到 index.json。请先初始化文档。")
    return index_path, json.loads(index_path.read_text(encoding="utf-8"))


def extract_repo_summary(project_root: Path) -> str | None:
    for name in ("README.md", "readme.md", "README.mdx"):
        candidate = project_root / name
        if not candidate.exists():
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("```"):
                continue
            if line.startswith("- [") or line.startswith("* ["):
                continue
            lines.append(line)
            if len(" ".join(lines)) >= 220:
                break
        summary = " ".join(lines).strip()
        if summary:
            return summary[:240].rstrip(" .") + ("。" if not summary.endswith(("。", ".", "！", "？")) else "")
    return None


def top_level_paths(project_root: Path) -> list[str]:
    ignored = {".git", "node_modules", "dist", "build", "out", ".next", ".cache", "coverage", "project-docs"}
    items = []
    for entry in sorted(project_root.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if entry.name.startswith(".") or entry.name in ignored:
            continue
        items.append(entry.name + ("/" if entry.is_dir() else ""))
    return items[:10]


def render_summary(project_root: Path) -> str:
    repo_summary = extract_repo_summary(project_root)
    traits = detect_project_traits(project_root)
    trait_text = "、".join(traits) if traits else "待用户确认"
    top_level = top_level_paths(project_root)
    top_level_text = "、".join(f"`{item}`" for item in top_level) if top_level else "待补充"

    positioning = repo_summary or (
        "待用户确认：请用 1 到 3 句话说明这个项目现在在做什么，以及它最终希望成为什么样的系统。"
    )
    stage_lines = [
        "- 这里先记录 AI 基于当前代码和 README 的理解草案，不把它视为最终真相。",
        "- 请用户明确指出：哪些内容代表当前已经稳定的实现，哪些只是阶段性过渡。",
        "- 如果项目尚未写完，请在这里补充长期目标，避免后续模块文档把临时实现误写成稳定架构。",
    ]
    usage_lines = [
        "- 待用户确认：这个项目主要服务谁，或主要解决哪类场景。",
        "- 待用户确认：最关键的使用链、运行链或交互链是什么。",
    ]
    stack_lines = [
        f"- 当前从仓库推断到的技术栈：{trait_text}",
        "- 请用户补充：是否还存在 AI 框架、数据库、中间件、服务协议等当前代码尚未完整表达的技术约束。",
        f"- 当前可见的重要顶层路径：{top_level_text}",
    ]
    principle_lines = [
        "- 待用户确认：应优先按哪些功能域理解项目，而不是按目录树理解项目。",
        "- 待用户确认：哪些架构边界已经稳定，哪些仍可能继续拆分或重写。",
        "- 待用户确认：如果当前代码和长期目标存在偏差，应以什么目标作为后续文档组织基线。",
    ]
    next_steps = [
        "- 用户审阅并直接修改这份 `project-summary.md`，使其成为项目意图基线。",
        "- 只有当这份 summary 被确认后，才继续建立 `project-structure.md` 和后续 `modules/`。",
        "- 这份 summary 被确认后，后续 structure 和 modules 都应围绕它生成。",
    ]

    return f"""# 项目摘要

## 文档状态

这是一份由 AI 生成的项目级 summary 草案，用于帮助用户先校准项目意图。  
在用户明确确认之前，这份文档不是最终真相，也不应直接驱动 `modules/` 生成。

## 项目定位

{positioning}

## 当前阶段与目标

{chr(10).join(stage_lines)}

## 目标用户与使用场景

{chr(10).join(usage_lines)}

## 技术栈与运行形态

{chr(10).join(stack_lines)}

## 当前稳定设计判断

{chr(10).join(principle_lines)}

## 后续文档生成规则

{chr(10).join(next_steps)}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="生成项目级 summary 草案。")
    parser.add_argument("--project-root", required=True, help="仓库根目录。")
    parser.add_argument("--doc-root", help="文档根目录。默认使用 <project-root>/project-docs。")
    parser.add_argument("--force", action="store_true", help="即使 summary 已存在，也强制重写草案。")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    doc_root = normalize_doc_root(project_root, args.doc_root).resolve()
    index_path, index_payload = load_index(doc_root)
    ensure_workflow_state(index_payload)

    summary_path = doc_root / "overview" / "project-summary.md"
    if summary_path.exists() and not args.force and index_payload.get("summary_state", {}).get("status") == "confirmed":
        print(f"[跳过] summary 已确认：{summary_path}")
        return 0

    summary_path.write_text(render_summary(project_root), encoding="utf-8")

    git_snapshot = capture_git_snapshot(project_root)
    index_payload["skill_name"] = SKILL_NAME
    index_payload["skill_version"] = SKILL_VERSION
    index_payload["doc_schema_version"] = DOC_SCHEMA_VERSION
    mark_summary_drafted(index_payload, git_snapshot)
    generated = set(index_payload.get("generated_docs", []))
    generated.add("overview/project-summary.md")
    index_payload["generated_docs"] = sorted(generated)
    index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot)
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[完成] 已生成 summary 草案：{summary_path}")
    print("[下一步] 请让用户审阅并确认 `overview/project-summary.md`，确认后再继续 structure 和 modules。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
