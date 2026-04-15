#!/usr/bin/env python3
"""
生成项目级 summary 草案，并等待用户确认。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from core.git_tracking import capture_git_snapshot, merge_git_state
from core.path_intelligence import (
    DEFAULT_OMIT_DIR_NAMES,
    build_path_evidence,
    collect_readme_summary,
    infer_title_from_path,
    is_root_context_signal_path,
    normalize_relpath,
    score_root_entry,
    summarize_path,
)
from core.workflow_state import ensure_workflow_state, mark_summary_drafted
from entrypoints.init_project_docs import normalize_doc_root
from generation.create_module_doc import detect_project_traits


SKILL_NAME = "auto-document"
SKILL_VERSION = "0.4.0"
DOC_SCHEMA_VERSION = "2.0.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def natural_join(items: list[str]) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} 和 {cleaned[1]}"
    return f"{'、'.join(cleaned[:-1])} 以及 {cleaned[-1]}"


def load_index(doc_root: Path) -> tuple[Path, dict]:
    index_path = doc_root / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"在 {index_path} 未找到 index.json。请先初始化文档。")
    return index_path, json.loads(index_path.read_text(encoding="utf-8"))


def visible_root_entries(project_root: Path) -> list[Path]:
    return [
        entry
        for entry in sorted(project_root.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        if not entry.name.startswith(".") and entry.name.lower() not in DEFAULT_OMIT_DIR_NAMES
    ]


def collect_root_context_signals(project_root: Path, limit: int = 6) -> list[dict]:
    signals = []
    for entry in visible_root_entries(project_root):
        if not entry.is_file() or not is_root_context_signal_path(entry.name):
            continue
        rel_path = normalize_relpath(entry.name)
        signals.append(
            {
                "path": rel_path,
                "title": infer_title_from_path(rel_path),
                "summary": summarize_path(rel_path, entry),
                "evidence_items": build_path_evidence(rel_path, entry)[:4],
            }
        )
        if len(signals) >= limit:
            break
    return signals


def collect_root_candidates(project_root: Path, limit: int = 6) -> list[dict]:
    ranked: list[tuple[int, dict]] = []
    for entry in visible_root_entries(project_root):
        if is_root_context_signal_path(entry.name):
            continue
        rel_path = normalize_relpath(entry.name)
        ranked.append(
            (
                score_root_entry(entry),
                {
                    "path": rel_path,
                    "title": infer_title_from_path(rel_path),
                    "summary": summarize_path(rel_path, entry),
                    "is_dir": entry.is_dir(),
                    "evidence_items": build_path_evidence(rel_path, entry)[:4],
                },
            )
        )
    ranked.sort(key=lambda item: (-item[0], item[1]["path"]))
    return [item for _, item in ranked[:limit]]


def collect_domain_candidates(domains: list[dict] | None, domain_analysis: dict | None) -> dict:
    level_one = []
    level_two = []
    analysis_map = domain_analysis or {}
    for domain in sorted(domains or [], key=lambda item: (item.get("level", 99), item.get("title", ""), item.get("id", ""))):
        entry = {
            "id": domain.get("id"),
            "title": domain.get("title"),
            "level": domain.get("level"),
            "summary": domain.get("summary"),
            "paths": list(domain.get("paths", [])),
            "doc_path": domain.get("doc_path"),
            "evidence_items": list((analysis_map.get(domain.get("id")) or {}).get("evidence_items", []))[:3],
        }
        if domain.get("level") == 1:
            level_one.append(entry)
        elif domain.get("level") == 2:
            level_two.append(entry)
    return {
        "level_one": level_one[:6],
        "level_two": level_two[:8],
    }


def build_positioning_draft(evidence: dict) -> str:
    repo_summary = evidence.get("repo_summary")
    level_one = evidence.get("domain_candidates", {}).get("level_one", [])
    root_candidates = evidence.get("root_candidates", [])
    if level_one:
        titles = natural_join([f"`{item['title']}`" for item in level_one[:3]])
        base = f"当前仓库更像一个围绕 {titles} 等候选功能域组织实现和文档入口的系统。"
    elif root_candidates:
        titles = natural_join([f"`{item['title']}`" for item in root_candidates[:3]])
        base = f"当前仓库更像一个围绕 {titles} 等根级主题入口组织材料的项目。"
    else:
        base = "当前仓库还缺少足够稳定的路径证据，暂时无法把项目定位收敛成单一结论。"
    if repo_summary:
        return f"README 当前提供的项目表述是：{repo_summary}\n\n结合根级路径、工具链和候选功能域证据，AI 的暂定理解是：{base}"
    return f"当前还缺少可信 README 表述，因此这份定位只能更多依赖仓库结构和路径证据。AI 的暂定理解是：{base}"


def build_goal_lines(evidence: dict) -> list[str]:
    lines = [
        "- 这部分先记录基于证据包整理出的暂定目标，不把它视为已经确认的项目真相。",
        "- 请用户明确标记：哪些描述代表当前已经稳定的实现，哪些只是过渡状态，哪些是长期目标。",
    ]
    level_one = evidence.get("domain_candidates", {}).get("level_one", [])
    if level_one:
        titles = natural_join([f"`{item['title']}`" for item in level_one[:3]])
        lines.append(f"- 现阶段至少可以确认，项目正在围绕 {titles} 等候选功能域逐步建立稳定阅读入口。")
    else:
        lines.append("- 当前更像是在先建立项目总览和阅读入口，具体长期目标仍需要用户直接补充。")
    return lines


def build_usage_lines(evidence: dict) -> list[str]:
    hints = []
    if evidence.get("repo_summary"):
        hints.append("- README 已提供局部背景，但仍不足以单独确认目标用户和主使用链。")
    if evidence.get("domain_candidates", {}).get("level_one"):
        titles = natural_join([item["title"] for item in evidence["domain_candidates"]["level_one"][:3]])
        hints.append(f"- 当前可见的候选功能域集中在 {titles}，但这些域面向谁、优先服务什么场景，仍应由用户确认。")
    hints.extend(
        [
            "- 待用户确认：这个项目主要服务谁，或者希望替代哪种现有工作方式。",
            "- 待用户确认：最关键的使用链、运行链或维护链到底是什么。",
        ]
    )
    return hints[:4]


def build_stack_lines(evidence: dict) -> list[str]:
    traits = evidence.get("project_traits", [])
    root_signals = evidence.get("root_context_signals", [])
    root_candidates = evidence.get("root_candidates", [])
    lines = [
        f"- 当前从仓库根级配置可见的技术信号：{natural_join(traits) if traits else '暂未识别到清晰工具链信号'}。",
    ]
    if root_signals:
        signal_refs = [f"`{item['path']}`" for item in root_signals[:4]]
        lines.append(
            f"- 当前根级上下文证据主要包括 {natural_join(signal_refs)}。"
        )
    if root_candidates:
        candidate_refs = [f"`{item['path']}`" for item in root_candidates[:4]]
        lines.append(
            f"- 当前值得继续阅读的根级候选入口包括 {natural_join(candidate_refs)}。"
        )
    lines.append("- 请用户补充：是否还存在代码里尚未完整表达的部署、运行、数据或 AI 约束。")
    return lines


def build_architecture_lines(evidence: dict) -> list[str]:
    level_one = evidence.get("domain_candidates", {}).get("level_one", [])
    root_candidates = evidence.get("root_candidates", [])
    lines = [
        "- 后续文档应优先按功能域和阅读入口组织，而不是直接把目录树当成最终架构结论。",
        "- 当前所有架构表述都应被视为“基于证据的暂定判断”，需要接受用户后续校准。",
    ]
    if level_one:
        level_one_refs = [f"`{item['title']}`" for item in level_one[:4]]
        lines.append(
            f"- 目前最可信的一级候选功能域是 {natural_join(level_one_refs)}。"
        )
    elif root_candidates:
        root_candidate_refs = [f"`{item['title']}`" for item in root_candidates[:4]]
        lines.append(
            f"- 在尚未建立功能域映射前，可先从 {natural_join(root_candidate_refs)} 这些根级入口继续判断。"
        )
    lines.append("- 如果当前代码与长期目标存在偏差，后续模块文档必须优先服从用户确认后的项目定位。")
    return lines


def build_open_questions(evidence: dict) -> list[str]:
    questions = [
        "项目当前真正稳定的核心职责是什么，哪些只是短期过渡实现?",
        "后续功能树应该优先围绕业务能力、技术子系统，还是维护工作流来组织?",
        "如果 README 与代码现状不一致，后续文档应以哪一边作为优先基线?",
    ]
    if evidence.get("domain_candidates", {}).get("level_one"):
        questions.append("这些一级候选功能域里，哪些已经可以视为稳定边界，哪些仍可能继续合并或拆分?")
    return questions[:5]


def collect_summary_evidence(
    project_root: Path,
    *,
    domains: list[dict] | None = None,
    domain_analysis: dict | None = None,
) -> dict:
    repo_summary = collect_readme_summary(project_root)
    project_traits = detect_project_traits(project_root)
    root_context_signals = collect_root_context_signals(project_root)
    root_candidates = collect_root_candidates(project_root)
    domain_candidates = collect_domain_candidates(domains, domain_analysis)

    evidence_items = []
    if repo_summary:
        evidence_items.append(f"README 摘要：{repo_summary}")
    if project_traits:
        evidence_items.append(f"根级工具链信号：{natural_join(project_traits)}。")
    if root_context_signals:
        evidence_items.extend(
            [
                f"`{item['path']}`：{item['summary']}"
                for item in root_context_signals[:3]
            ]
        )
    if root_candidates:
        evidence_items.extend(
            [
                f"`{item['path']}`：{item['summary']}"
                for item in root_candidates[:4]
            ]
        )
    if domain_candidates["level_one"]:
        evidence_items.extend(
            [
                f"一级候选功能域 `{item['title']}`：{item['summary']}"
                for item in domain_candidates["level_one"][:4]
            ]
        )

    judgment_prompt = (
        "请基于 README 摘要、根级上下文文件、工具链信号、根级候选入口以及已生成的候选功能域，"
        "判断这个项目当前真正稳定的定位、主要服务对象、优先阅读入口和后续文档组织基线。"
        "不要把单一路径名或单份 README 文案直接视为最终真相。"
    )

    evidence = {
        "generated_at": utc_now(),
        "repo_summary": repo_summary,
        "project_traits": project_traits,
        "root_context_signals": root_context_signals,
        "root_candidates": root_candidates,
        "domain_candidates": domain_candidates,
        "evidence_items": evidence_items[:12],
        "judgment_prompt": judgment_prompt,
    }
    evidence["draft_sections"] = {
        "positioning": build_positioning_draft(evidence),
        "goal_lines": build_goal_lines(evidence),
        "usage_lines": build_usage_lines(evidence),
        "stack_lines": build_stack_lines(evidence),
        "architecture_lines": build_architecture_lines(evidence),
        "open_questions": build_open_questions(evidence),
    }
    return evidence


def build_summary_analysis_cache(evidence: dict) -> dict:
    return {
        "generated_at": evidence.get("generated_at"),
        "repo_summary": evidence.get("repo_summary"),
        "project_traits": list(evidence.get("project_traits", [])),
        "root_context_signals": list(evidence.get("root_context_signals", [])),
        "root_candidates": list(evidence.get("root_candidates", [])),
        "domain_candidates": dict(evidence.get("domain_candidates", {})),
        "evidence_items": list(evidence.get("evidence_items", [])),
        "judgment_prompt": evidence.get("judgment_prompt"),
        "draft_sections": dict(evidence.get("draft_sections", {})),
    }


def render_evidence_group(title: str, items: list[str]) -> str:
    if not items:
        return f"### {title}\n\n- 暂无"
    return f"### {title}\n\n" + "\n".join(f"- {item}" for item in items)


def render_summary(evidence: dict, *, confirmed: bool = False) -> str:
    draft_sections = evidence.get("draft_sections", {})
    root_signal_lines = [
        f"`{item['path']}`：{item['summary']}"
        for item in evidence.get("root_context_signals", [])
    ]
    root_candidate_lines = [
        f"`{item['path']}`：{item['summary']}"
        for item in evidence.get("root_candidates", [])
    ]
    domain_lines = [
        f"`{item['title']}`：{item['summary']}"
        for item in evidence.get("domain_candidates", {}).get("level_one", [])
    ]
    open_questions = draft_sections.get("open_questions", [])
    if confirmed:
        status_text = (
            "这是一份基于已确认项目定位和当前仓库证据整理出的对齐版 summary。  \n"
            "当前版本默认可继续作为 structure 和 modules 的上层判断基线，但如果项目定位本身发生变化，仍应重新发起人工校准。"
        )
        next_steps = [
            "- 如果本轮代码变化没有改变项目定位，可继续沿这份 summary 维护 `project-structure.md` 和 `modules/`。",
            "- 如果项目目标、服务对象或稳定边界已经改变，应先重新校准这份 `project-summary.md`。",
            "- 后续维护应复用这里的证据包与判断提示，而不是回退到固定路径名匹配。",
        ]
    else:
        status_text = (
            "这是一份由 AI 根据当前仓库证据整理出的 summary 草案。  \n"
            "在用户明确确认之前，这份文档只代表“当前证据下的暂定理解”，不是最终真相。"
        )
        next_steps = [
            "- 用户应直接修改这份 `project-summary.md`，把暂定判断校准成项目真实意图。",
            "- 只有当这份 summary 被确认后，才继续建立或重建 `project-structure.md` 和 `modules/`。",
            "- 后续结构文档和模块文档都应把这里的已确认定位当成判断基线，而不是反过来被临时路径牵着走。",
        ]

    return f"""# 项目摘要

## 文档状态

{status_text}

## 当前证据包

{render_evidence_group("根级上下文证据", root_signal_lines)}

{render_evidence_group("根级候选入口", root_candidate_lines)}

{render_evidence_group("候选功能域", domain_lines)}

### 判断提示

- {evidence.get('judgment_prompt', '待补充')}

## AI 暂定草案

### 暂定项目定位

{draft_sections.get('positioning', '待补充')}

### 暂定当前阶段与目标

{chr(10).join(draft_sections.get('goal_lines', ['- 待补充']))}

### 暂定目标用户与使用场景

{chr(10).join(draft_sections.get('usage_lines', ['- 待补充']))}

### 暂定技术与运行边界

{chr(10).join(draft_sections.get('stack_lines', ['- 待补充']))}

### 暂定架构理解原则

{chr(10).join(draft_sections.get('architecture_lines', ['- 待补充']))}

## 待用户校准

{chr(10).join(f"- {item}" for item in open_questions) if open_questions else '- 待补充'}

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

    evidence = collect_summary_evidence(project_root)
    summary_path.write_text(render_summary(evidence, confirmed=False), encoding="utf-8")

    git_snapshot = capture_git_snapshot(project_root)
    index_payload["skill_name"] = SKILL_NAME
    index_payload["skill_version"] = SKILL_VERSION
    index_payload["doc_schema_version"] = DOC_SCHEMA_VERSION
    index_payload["summary_analysis"] = build_summary_analysis_cache(evidence)
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
