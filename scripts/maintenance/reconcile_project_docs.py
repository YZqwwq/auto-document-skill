#!/usr/bin/env python3
"""
在大范围代码调整后，将 project-docs 收敛到当前项目状态。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from analysis.architecture_domains import infer_architecture_domains, recommended_domain_ids, tracked_top_level_paths
from analysis.scan_project_tree import build_tree, load_index, summarize_top_level, write_structure_doc
from core.git_tracking import capture_git_snapshot, merge_git_state
from core.workflow_state import (
    ensure_workflow_state,
    mark_modules_aligned,
    mark_modules_drafted,
    mark_structure_aligned,
    mark_structure_drafted,
    summary_gate_message,
    summary_is_confirmed,
)
from generation.create_module_doc import (
    analyze_domain,
    detect_project_traits,
    normalize_doc_root,
    render_domain_doc_from_analysis,
    update_modules_readme,
)


BASE_DOCS = {
    "README.md",
    "overview/project-summary.md",
    "overview/project-structure.md",
    "modules/README.md",
    "history/analysis-log.md",
    "history/change-log.md",
}
SKILL_NAME = "auto-document"
SKILL_VERSION = "0.4.0"
DOC_SCHEMA_VERSION = "2.0.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def merge_targets(preferred: list[str], fallback: list[str]) -> list[str]:
    merged = []
    seen = set()
    for rel in preferred + fallback:
        clean = rel.replace("\\", "/").strip("/")
        if clean and clean not in seen:
            merged.append(clean)
            seen.add(clean)
    return merged


def extract_repo_summary(project_root: Path) -> str | None:
    for name in ("README.md", "readme.md", "README.mdx"):
        candidate = project_root / name
        if not candidate.exists():
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("- [") or line.startswith("* ["):
                continue
            lowered = line.lower()
            if lowered.startswith("## recommended ide setup"):
                break
            if lowered.startswith("## project setup"):
                break
            if lowered.startswith("### install"):
                break
            if lowered.startswith("```"):
                break
            lines.append(line)
            if len(" ".join(lines)) >= 180:
                break
        summary = " ".join(lines).strip()
        if summary:
            return summary[:220].rstrip(" .") + ("。" if not summary.endswith(("。", ".", "！", "？")) else "")
    return None


def parse_markdown_sections(path: Path) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def extract_section_summary(lines: list[str], *, max_items: int = 2) -> list[str]:
    items = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
        elif not stripped.startswith("#"):
            items.append(stripped)
        if len(items) >= max_items:
            break
    return items


def normalize_statement(text: str) -> str:
    value = text.strip()
    value = value.removeprefix("负责").removeprefix("这是一个以").strip()
    value = value.rstrip("。.!！?？")
    return value


def natural_join(items: list[str]) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]}和{cleaned[1]}"
    return f"{'、'.join(cleaned[:-1])}以及{cleaned[-1]}"


def collect_second_layer_insights(doc_root: Path, level_two: list[dict], module_docs: dict) -> list[dict]:
    insights = []
    for domain in level_two:
        doc_rel = module_docs.get(domain["id"], domain.get("doc_path", ""))
        if not doc_rel:
            continue
        path = doc_root / doc_rel
        if not path.exists():
            continue
        sections = parse_markdown_sections(path)
        insights.append(
            {
                "id": domain["id"],
                "title": domain["title"],
                "positioning": normalize_statement(" ".join(extract_section_summary(sections.get("定位", []), max_items=1))),
                "core_points": extract_section_summary(sections.get("这一层内部怎么分", []), max_items=3),
                "responsibilities": extract_section_summary(sections.get("这一层主要承载什么", []), max_items=2),
            }
        )
    return insights


def get_insight(insights: list[dict], domain_id: str) -> dict | None:
    return next((item for item in insights if item["id"] == domain_id), None)


def infer_project_positioning(domains: list[dict], traits: list[str], repo_summary: str | None, second_layer_insights: list[dict]) -> str:
    trait_text = "、".join(traits) if traits else "桌面应用"
    if repo_summary and "An Electron application with Vue and TypeScript" not in repo_summary:
        return repo_summary
    level_two_titles = [item["title"] for item in second_layer_insights[:3]]
    if level_two_titles:
        return (
            f"这是一个以 {trait_text} 为基础的项目，当前重点围绕 {natural_join(level_two_titles)} 等专题域组织实现。"
            "项目文档更强调先建立功能分层和阅读入口，再逐步进入具体实现链。"
        )
    first_domain_names = "、".join(domain["title"] for domain in domains if domain.get("level") == 1)
    return (
        f"这是一个以 {trait_text} 为基础的项目，当前主要围绕 {first_domain_names or '核心功能域'} 组织架构。"
        "项目更强调功能分层、运行时边界和长期维护，而不是把目录树本身当成理解入口。"
    )


def infer_project_goal_lines(domains: list[dict], second_layer_insights: list[dict]) -> list[str]:
    level_one = [domain for domain in domains if domain.get("level") == 1]
    lines = []
    if level_one:
        lines.append(f"- 先把 {natural_join([domain['title'] for domain in level_one[:3]])} 等主要功能域的阅读入口稳定下来，降低首次接手成本。")
    for insight in second_layer_insights[:3]:
        if insight.get("positioning"):
            lines.append(f"- 围绕{insight['positioning']}继续细化专题域，让这块能力有稳定的阅读入口和实现边界。")
    if not second_layer_insights and len(level_one) > 1:
        lines.append("- 当某个功能域内部已经形成稳定专题时，再继续下钻，避免总览文档承载过多实现细节。")
    if not lines:
        lines.append("- 先把项目的核心功能域和阅读入口稳定下来，再让专题域逐步细化实现说明。")
    return lines


def infer_architecture_principles(domains: list[dict], second_layer_insights: list[dict]) -> list[str]:
    level_one = [domain for domain in domains if domain.get("level") == 1]
    principles = [
        "- 先按功能域理解项目，而不是按目录树或工具链配置理解项目。",
        "- 第一层只负责说明系统由哪些大块组成；第二层才解释专题域；更细的实现链留给下层文档。",
    ]
    if level_one:
        principles.append(f"- 当前总览先把系统收拢为 {natural_join([domain['title'] for domain in level_one[:3]])} 等一级功能域，再由下层文档展开细节。")
    if second_layer_insights:
        titles = [item["title"] for item in second_layer_insights[:4]]
        principles.append(f"- 第一层功能域之下继续按 {'、'.join(titles)} 等专题域下钻，避免把所有实现细节堆在同一层。")
        principles.append("- 项目目标与架构理念应优先从第二层专题域反推，再由第一层功能域负责收拢和导航。")
    elif level_one:
        principles.append("- 只有当某个一级功能域内部已经形成稳定专题时，再继续下钻；否则保持总览克制。")
    principles.append("- `project-summary.md` 服务人类首次接手，`project-structure.md` 服务 AI 快速扫路径，两者职责应明确区分。")
    return principles


def write_project_summary(doc_root: Path, project_root: Path, domains: list[dict], module_docs: dict) -> None:
    summary_path = doc_root / "overview" / "project-summary.md"
    traits = detect_project_traits(project_root)
    level_one = [domain for domain in domains if domain.get("level") == 1]
    level_two = [domain for domain in domains if domain.get("level") == 2]
    repo_summary = extract_repo_summary(project_root)
    second_layer_insights = collect_second_layer_insights(doc_root, level_two, module_docs)
    first_domain_names = "、".join(domain["title"] for domain in level_one[:3]) if level_one else "核心功能域"
    first_domain_lines = [
        f"- `{domain['title']}`：{domain['summary']} 详见 `{module_docs.get(domain['id'], domain.get('doc_path', ''))}`"
        for domain in level_one
    ]
    second_domain_lines = [
        f"- `{domain['title']}`：{domain['summary']} 详见 `{module_docs.get(domain['id'], domain.get('doc_path', ''))}`"
        for domain in level_two
    ]
    positioning = infer_project_positioning(domains, traits, repo_summary, second_layer_insights)
    goal_lines = infer_project_goal_lines(domains, second_layer_insights)
    architecture_lines = infer_architecture_principles(domains, second_layer_insights)
    reading_lines = [
        "- 人类第一次接手：先读这份 `project-summary.md`，再读 `modules/README.md`，然后沿功能域 README 继续下钻。",
        "- 当问题已经落到具体专题时，直接进入对应的第二层专题域 README。",
        "- 只有在需要快速确认大量路径或目录快照时，再读 `project-structure.md`。",
    ]
    content = f"""# 项目摘要

## 项目定位

{positioning}

## 项目目标

{chr(10).join(goal_lines)}

## 架构理念

{chr(10).join(architecture_lines)}

## 第一层功能域

{chr(10).join(first_domain_lines) if first_domain_lines else "- 待补充"}

## 第二层专题域

{chr(10).join(second_domain_lines) if second_domain_lines else "- 待补充"}

## 推荐阅读方式

{chr(10).join(reading_lines)}

## AI 速读入口

- `overview/project-structure.md`：给 AI 或需要快速扫路径的人使用的结构快照。
- `index.json`：记录文档系统当前对齐状态与机器可读索引。
"""
    summary_path.write_text(content, encoding="utf-8")


def remove_stale_module_docs(doc_root: Path, previous_module_docs: dict, next_module_docs: dict) -> tuple[list[str], list[str]]:
    removed = []
    retained = []
    for rel, doc_rel in previous_module_docs.items():
        if rel in next_module_docs:
            continue
        doc_path = doc_root / doc_rel
        if doc_path.exists():
            try:
                doc_path.chmod(0o666)
                doc_path.unlink()
                removed.append(doc_rel)
            except OSError:
                doc_path.write_text(
                    "# 已失效文档\n\n"
                    "这个文件对应的项目路径已不存在，当前不属于有效模块文档集合。\n"
                    "如果环境允许，可以手动删除这个残留文件。\n",
                    encoding="utf-8",
                )
                retained.append(doc_rel)
    return removed, retained


def remove_orphan_module_files(
    doc_root: Path,
    next_module_docs: dict,
    *,
    strict: bool = False,
) -> tuple[list[str], list[str]]:
    removed = []
    retained = []
    modules_dir = doc_root / "modules"
    keep = {"modules/README.md", *[path.replace("\\", "/") for path in next_module_docs.values()]}
    if not modules_dir.exists():
        return removed, retained
    for path in modules_dir.rglob("*.md"):
        rel = path.relative_to(doc_root).as_posix()
        if rel in keep:
            continue
        try:
            path.chmod(0o666)
            path.unlink()
            removed.append(rel)
        except OSError:
            if not strict:
                path.write_text(
                    "# 已失效文档\n\n"
                    "这个文件不再属于当前功能域文档集合，但当前环境未能自动删除它。\n",
                    encoding="utf-8",
                )
            retained.append(rel)
    return removed, retained


def remove_empty_module_directories(doc_root: Path) -> list[str]:
    modules_dir = doc_root / "modules"
    removed = []
    if not modules_dir.exists():
        return removed
    directories = sorted([path for path in modules_dir.rglob("*") if path.is_dir()], key=lambda item: len(item.parts), reverse=True)
    for path in directories:
        if path == modules_dir:
            continue
        try:
            next(path.iterdir())
            continue
        except StopIteration:
            path.rmdir()
            removed.append(path.relative_to(doc_root).as_posix())
    return removed


def write_root_readme(doc_root: Path, domains: list[dict], module_docs: dict) -> None:
    project_name = doc_root.parent.name or "当前项目"

    content = f"""# 项目文档

这份目录用于维护 `{project_name}` 的项目文档系统。这里不负责展开具体功能架构，而是说明这套文档目录里各个固定文件和文件夹分别做什么，帮助维护者快速判断应该去哪里阅读、补充或更新。

## 建议先读哪里

- 第一次接手时，先读 `overview` 下的 `project-summary.md`，再读 `modules` 下的 `README.md`。
- 如果需要快速扫目录和路径关系，再读 `overview` 下的 `project-structure.md`。
- 如果要判断最近一次分析、变更规划和待处理项，再读 `history` 和 `index.json`。

## 固定文件与文件夹的作用

```text
overview
|-- project-structure.md  项目的文件层次，用于引导 AI 快速建立路径地图；项目开发者通常可以按需查看
|-- project-summary.md    对项目目的与设计理念的阐述；AI 会先生成模板，但仍需要开发者维护和补充，用来给后续 AI 工作一个明确方向

modules
|-- README.md             功能域总入口，用来判断应该先从哪个功能域进入

history
|-- analysis-log.md       记录每一轮分析、收敛或人工补充
|-- change-log.md         记录由代码变更触发的文档更新规划和影响范围

index.json                文档系统的机器可读控制面，记录已生成文档、功能域索引、待处理更新项和 git 对齐状态
```

## 文档职责

- `overview` 负责项目级理解。
- `modules` 负责功能域级理解。
- `history` 负责维护轨迹。
- `index.json` 负责机器可读状态。
"""
    (doc_root / "README.md").write_text(content, encoding="utf-8")


def write_module_docs(project_root: Path, doc_root: Path, domains: list[dict], selected_ids: list[str]) -> tuple[dict, dict]:
    module_docs = {}
    domain_analysis = {}
    selected = [domain for domain in domains if domain["id"] in selected_ids]
    for domain in selected:
        doc_rel = domain["doc_path"]
        doc_path = doc_root / doc_rel
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        analysis = analyze_domain(domain, domains, project_root)
        doc_path.write_text(render_domain_doc_from_analysis(analysis), encoding="utf-8")
        module_docs[domain["id"]] = doc_rel
        domain_analysis[domain["id"]] = analysis
    update_modules_readme(doc_root, module_docs, selected)
    write_root_readme(doc_root, selected, module_docs)
    return module_docs, domain_analysis


def rebuild_index(
    index_path: Path,
    index_payload: dict,
    top_level: list[dict],
    architecture_domains: list[dict],
    module_docs: dict,
    targets: list[str],
    domain_analysis: dict | None = None,
) -> None:
    generated_docs = sorted(BASE_DOCS.union(module_docs.values()))
    git_snapshot = capture_git_snapshot(Path(index_payload["project_root"]))
    ensure_workflow_state(index_payload)
    index_payload["skill_name"] = SKILL_NAME
    index_payload["skill_version"] = SKILL_VERSION
    index_payload["doc_schema_version"] = DOC_SCHEMA_VERSION
    index_payload["last_scan_at"] = utc_now()
    index_payload["last_reconciled_at"] = utc_now()
    index_payload["tracked_paths"] = tracked_top_level_paths(architecture_domains) or [item["path"] for item in top_level]
    index_payload["architecture_domains"] = architecture_domains
    index_payload["round_two_targets"] = targets
    index_payload["module_docs"] = dict(sorted(module_docs.items()))
    index_payload["domain_analysis"] = domain_analysis or {}
    index_payload["generated_docs"] = generated_docs
    index_payload["pending_updates"] = []
    mark_structure_aligned(index_payload, git_snapshot)
    mark_modules_aligned(index_payload, git_snapshot)
    index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot, align_to_current=True)
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="在大范围变更后，将 project-docs 收敛到当前项目状态。")
    parser.add_argument("--project-root", required=True, help="仓库根目录。")
    parser.add_argument("--doc-root", help="文档根目录。默认使用 <project-root>/project-docs。")
    parser.add_argument("--target", action="append", help="显式指定需要保留并重写的模块路径。")
    parser.add_argument(
        "--use-recommended-only",
        action="store_true",
        help="仅使用本轮扫描推荐的第二轮目标，忽略历史模块登记。",
    )
    parser.add_argument(
        "--prune-mode",
        choices=("safe", "strict"),
        default="safe",
        help="清理旧文档的模式。safe 会在删除失败时保留失效占位，strict 会继续尝试只保留当前有效文档。",
    )
    parser.add_argument("--max-depth", type=int, default=2, help="顶层结构文档的目录树最大深度。")
    parser.add_argument("--include-hidden", action="store_true", help="包含以点开头的文件和目录。")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    doc_root = normalize_doc_root(project_root, args.doc_root).resolve()
    index_path, index_payload = load_index(doc_root)
    ensure_workflow_state(index_payload)

    if not summary_is_confirmed(index_payload):
        print(f"[阻止] {summary_gate_message(index_payload)}")
        print("[下一步] 请先确认 `overview/project-summary.md`，再执行收敛。")
        return 0

    mark_structure_drafted(index_payload)
    tree_lines = build_tree(project_root, project_root, args.max_depth, args.include_hidden)
    top_level = summarize_top_level(project_root, args.include_hidden)
    architecture_domains = infer_architecture_domains(project_root)
    recommended_targets = recommended_domain_ids(architecture_domains)
    write_structure_doc(
        doc_root,
        project_root,
        top_level,
        tree_lines,
        recommended_targets,
        architecture_domains,
        args.max_depth,
        summary_confirmed_at=index_payload.get("summary_state", {}).get("confirmed_at"),
    )

    explicit_targets = [item.replace("\\", "/").strip("/") for item in (args.target or [])]
    previous_targets = [item["id"] for item in index_payload.get("architecture_domains", []) if item.get("id")]

    if explicit_targets:
        next_targets = merge_targets(explicit_targets, [])
    elif args.use_recommended_only:
        next_targets = merge_targets(recommended_targets, [])
    else:
        next_targets = merge_targets(previous_targets, recommended_targets)

    previous_module_docs = dict(index_payload.get("module_docs", {}))
    mark_modules_drafted(index_payload)
    next_module_docs, domain_analysis = write_module_docs(project_root, doc_root, architecture_domains, next_targets)
    removed_docs, retained_stale_docs = remove_stale_module_docs(doc_root, previous_module_docs, next_module_docs)
    orphan_removed, orphan_retained = remove_orphan_module_files(
        doc_root,
        next_module_docs,
        strict=args.prune_mode == "strict",
    )
    removed_docs.extend(orphan_removed)
    retained_stale_docs.extend(orphan_retained)
    removed_dirs = remove_empty_module_directories(doc_root) if args.prune_mode == "strict" else []
    rebuild_index(index_path, index_payload, top_level, architecture_domains, next_module_docs, next_targets, domain_analysis)

    print(f"[完成] 已重写结构文档：{doc_root / 'overview' / 'project-structure.md'}")
    print(f"[完成] 已收敛并补写模块文档：{', '.join(next_module_docs.values()) if next_module_docs else '无'}")
    print(f"[完成] 已移除失效模块文档：{', '.join(removed_docs) if removed_docs else '无'}")
    print(f"[完成] 已标记但未删除的失效文档：{', '.join(retained_stale_docs) if retained_stale_docs else '无'}")
    if args.prune_mode == "strict":
        print(f"[完成] 已移除空目录：{', '.join(removed_dirs) if removed_dirs else '无'}")
    print("[完成] 已清空 pending_updates，并将索引同步到当前状态。")
    git_state = index_payload.get("git_state", {})
    if git_state.get("git_available"):
        print(f"[完成] 已记录文档对齐点：{git_state.get('aligned_branch')} @ {git_state.get('aligned_head_sha')}")
    else:
        print("[提示] 当前项目未检测到 git。已完成基于文件系统的收敛；后续如需 git 感知，请先安装并初始化 git。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
