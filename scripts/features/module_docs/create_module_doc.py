#!/usr/bin/env python3
"""
生成功能域文档，并将其登记到 index.json。

当前版本的重点不是“给一个路径生成说明”，而是：

- 优先按功能域生成文档
- 在文档中解释功能层级、代码落点和阅读入口
- 将路径输入仅作为解析到功能域的兼容方式
"""

from __future__ import annotations

import argparse
import json
import posixpath
from pathlib import Path

from scripts.features.structure.architecture_domains import domains_by_parent
from scripts.shared.git_tracking import capture_git_snapshot, merge_git_state
from scripts.shared.path_intelligence import (
    CODE_SUFFIXES,
    DEFAULT_OMIT_DIR_NAMES,
    MARKDOWN_SUFFIXES,
    STRUCTURED_TEXT_SUFFIXES,
    build_path_evidence,
    collect_readme_summary,
    collect_sample_entries,
    is_low_semantic_risk_path,
    normalize_relpath,
    summarize_path,
)
from scripts.shared.workflow_state import (
    ensure_workflow_state,
    mark_modules_aligned,
    mark_modules_drafted,
    structure_gate_message,
    structure_is_aligned,
    summary_gate_message,
    summary_is_confirmed,
)


DEFAULT_DOC_DIR = "project-docs"
SKILL_NAME = "auto-document"
SKILL_VERSION = "0.4.0"
DOC_SCHEMA_VERSION = "2.0.0"
README_CANDIDATES = ("README.md", "README.mdx", "readme.md")
IGNORED_ENTRY_NAMES = {"__pycache__", ".ds_store"} | DEFAULT_OMIT_DIR_NAMES
REPRESENTATIVE_SCAN_SUFFIXES = CODE_SUFFIXES | MARKDOWN_SUFFIXES | STRUCTURED_TEXT_SUFFIXES


# 将字符串列表渲染为 Markdown 项目符号。
def format_bullets(items: list[str]) -> str:
    return "\n".join([f"- {item}" for item in items]) if items else "- 无"


# 统一解析文档根目录，兼容相对路径和绝对路径输入。
def normalize_doc_root(project_root: Path, doc_root: str | None) -> Path:
    if doc_root:
        candidate = Path(doc_root)
        return candidate if candidate.is_absolute() else (project_root / candidate)
    return project_root / DEFAULT_DOC_DIR


# 将路径或域 ID 转成稳定的文档文件名片段。
def slugify(relative_path: str) -> str:
    value = relative_path.replace("\\", "/").strip("/")
    return value.replace("/", "__").replace(":", "").replace(".", "_")


# 读取 index.json，并在缺失时阻止继续生成模块文档。
def load_index(doc_root: Path) -> tuple[Path, dict]:
    index_path = doc_root / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"在 {index_path} 未找到 index.json。请先初始化文档。")
    return index_path, json.loads(index_path.read_text(encoding="utf-8"))


# 分别收集当前层可见的子目录名和文件名。
def collect_child_names(target_path: Path, limit: int = 12) -> tuple[list[str], list[str]]:
    if target_path.is_file():
        return [], []
    directories = []
    files = []
    for entry in sorted(target_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if entry.name.lower() in IGNORED_ENTRY_NAMES:
            continue
        if entry.is_dir():
            directories.append(entry.name)
        else:
            files.append(entry.name)
    return directories[:limit], files[:limit]


# 在当前路径同层查找可作为局部语境入口的 README。
def find_local_readme(target_path: Path) -> Path | None:
    search_dir = target_path if target_path.is_dir() else target_path.parent
    for name in README_CANDIDATES:
        candidate = search_dir / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


# 收集仓库根级可见的结构化配置事实。
def detect_project_traits(project_root: Path | None) -> list[str]:
    if project_root is None:
        return []
    traits = []
    if (project_root / "package.json").exists():
        traits.append("仓库根目录存在 `package.json`。")
    if (project_root / "pyproject.toml").exists():
        traits.append("仓库根目录存在 `pyproject.toml`。")
    if (project_root / "Cargo.toml").exists():
        traits.append("仓库根目录存在 `Cargo.toml`。")
    if (project_root / "go.mod").exists():
        traits.append("仓库根目录存在 `go.mod`。")
    if (project_root / "pom.xml").exists():
        traits.append("仓库根目录存在 `pom.xml`。")
    return traits


# 将相对路径压缩成更适合展示的名称。
def path_display_name(path_text: str, is_dir: bool | None = None) -> str:
    clean = normalize_relpath(path_text)
    if not clean:
        return "/"
    name = clean.split("/")[-1]
    if is_dir is True and not name.endswith("/"):
        return name + "/"
    return name


# 用更自然的中文连接多个名称或短语。
def natural_join(items: list[str]) -> str:
    cleaned = [item for item in items if item]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} 和 {cleaned[1]}"
    return f"{'、'.join(cleaned[:-1])} 以及 {cleaned[-1]}"


# 汇总单一路径的证据观察，供后续文档生成引用。
def collect_context_observations(
    relative_path: str,
    target_path: Path,
    child_dirs: list[str],
    child_files: list[str],
    readme_summary: str | None,
    project_traits: list[str] | None = None,
) -> list[str]:
    observations = build_path_evidence(relative_path, target_path)
    if project_traits:
        observations.extend(project_traits[:4])
    if readme_summary:
        observations.append(f"本地 README 摘要：{readme_summary}")
    if child_dirs:
        observations.append(f"当前直接可见的子目录包括 {natural_join([f'`{name}`' for name in child_dirs[:5]])}。")
    if child_files:
        observations.append(f"当前直接可见的文件包括 {natural_join([f'`{name}`' for name in child_files[:5]])}。")
    return observations


# 为候选阅读入口生成可直接观察到的事实说明。
def describe_reading_candidate(path: Path, rel_path: str, *, is_root_readme: bool = False) -> tuple[str, list[str]]:
    reasons = []
    if is_root_readme:
        reasons.append("同层存在 README。")
    if path.is_dir():
        reasons.append("这是一个子目录。")
    else:
        suffix = path.suffix.lower()
        if suffix in CODE_SUFFIXES:
            reasons.append("文件后缀显示它是代码文件。")
        elif suffix in MARKDOWN_SUFFIXES:
            reasons.append("文件后缀显示它是说明文档。")
        elif suffix in STRUCTURED_TEXT_SUFFIXES:
            reasons.append("文件后缀显示它是结构化配置文件。")
        else:
            reasons.append("这是一个可见文件。")
    if is_low_semantic_risk_path(rel_path):
        reasons.append("命名中带有测试、样例或辅助材料提示。")
    return ("候选入口", reasons)


# 汇总当前功能域下可继续核对的入口候选，不在代码里替 AI 决定优先级。
def collect_entry_candidates(relative_path: str, target_path: Path, readme_path: Path | None) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()

    def add_candidate(path: Path, rel_path: str, *, is_root_readme: bool = False) -> None:
        clean_rel = normalize_relpath(rel_path)
        if not clean_rel or clean_rel in seen:
            return
        seen.add(clean_rel)
        label, reasons = describe_reading_candidate(path, clean_rel, is_root_readme=is_root_readme)
        candidates.append(
            {
                "path": clean_rel,
                "name": path.name,
                "label": label,
                "basis": reasons,
                "is_dir": path.is_dir(),
            }
        )

    if target_path.is_file():
        add_candidate(target_path, relative_path)
    else:
        if readme_path:
            readme_rel = (Path(relative_path) / readme_path.name).as_posix() if relative_path else readme_path.name
            add_candidate(readme_path, readme_rel, is_root_readme=True)
        for child in sorted(target_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            if child.name.lower() in IGNORED_ENTRY_NAMES or child.name.startswith("."):
                continue
            rel_path = (Path(relative_path) / child.name).as_posix() if relative_path else child.name
            add_candidate(child, rel_path)
            if len(candidates) >= 12:
                break

    return candidates[:8]


# 为单一路径整理完整的证据包和判断提示。
def build_context(relative_path: str, target_path: Path, project_root: Path | None = None) -> dict:
    child_dirs, child_files = collect_child_names(target_path)
    readme_path = find_local_readme(target_path)
    readme_summary = collect_readme_summary(target_path)
    project_traits = detect_project_traits(project_root)
    observations = collect_context_observations(
        relative_path,
        target_path,
        child_dirs,
        child_files,
        readme_summary,
        project_traits,
    )
    entry_candidates = collect_entry_candidates(relative_path, target_path, readme_path)
    path_summary = summarize_path(relative_path, target_path)
    return {
        "relative_path": relative_path,
        "target_path": target_path,
        "path_type": "文件" if target_path.is_file() else "目录",
        "sample_entries": collect_sample_entries(target_path, limit=12),
        "child_dirs": child_dirs,
        "child_files": child_files,
        "readme_path": readme_path,
        "readme_summary": readme_summary,
        "path_facts": observations,
        "path_summary": path_summary,
        "entry_candidates": entry_candidates,
    }


# 把单一路径证据整理成“当前位置说明”文本。
def context_positioning(context: dict) -> str:
    relative_path = context["relative_path"]
    summary = context.get("path_summary") or summarize_path(relative_path, context["target_path"])
    return (
        f"`{relative_path}`：{summary} "
        "这是一条用于帮助 AI 和维护者继续判断的证据落点，而不是已经被系统锁定的最终职责结论。"
    )


# 计算文档之间的相对链接路径。
def relative_doc_link(from_doc_rel: str, to_doc_rel: str) -> str:
    from_dir = posixpath.dirname(from_doc_rel)
    return posixpath.relpath(to_doc_rel, start=from_dir or ".")


# 计算文档到源码路径的相对链接。
def relative_source_link(from_doc_rel: str, source_rel: str) -> str:
    from_dir = posixpath.dirname(from_doc_rel)
    clean = source_rel.replace("\\", "/").strip("/")
    return posixpath.relpath(clean, start=from_dir or ".")


# 生成指向其他功能域文档的引用文本。
def domain_ref_for_doc(target_domain: dict, current_doc_rel: str) -> str:
    target_doc_rel = target_domain.get("doc_path", "")
    if not target_doc_rel or target_doc_rel == current_doc_rel:
        return f"`{target_domain['title']}`"
    return f"[`{target_domain['title']}`](./{relative_doc_link(current_doc_rel, target_doc_rel)})"


# 汇总源码文件本身可直接观察到的事实。
def collect_source_observations(path: Path, source_rel: str) -> list[str]:
    observations = []
    lower_name = path.name.lower()
    suffix = path.suffix.lower()
    if "readme" in lower_name:
        observations.append("文件名显示它是 README。")
    elif suffix in STRUCTURED_TEXT_SUFFIXES:
        observations.append("文件后缀显示它是结构化配置文件。")
    elif suffix in MARKDOWN_SUFFIXES:
        observations.append("文件后缀显示它是说明文档。")
    elif suffix in CODE_SUFFIXES:
        observations.append("文件后缀显示它是代码文件。")
    else:
        observations.append("这是该功能域覆盖路径下的可见文件。")
    if is_low_semantic_risk_path(source_rel):
        observations.append("命名中带有测试、样例或辅助材料提示。")
    return observations


# 生成指向源码文件的 Markdown 链接。
def source_ref(source_rel: str, current_doc_rel: str) -> str:
    label = path_display_name(source_rel)
    target = relative_source_link(current_doc_rel, source_rel)
    return f"[`{label}`](./{target})"


# 生成在文件树中使用的源码路径链接，标签保留相对路径本身。
def source_tree_ref(source_rel: str, current_doc_rel: str) -> str:
    clean = source_rel.replace("\\", "/").strip("/")
    target = relative_source_link(current_doc_rel, clean)
    return f"[`{clean}`](./{target})"


# 在功能域覆盖路径下收集一批可继续核对的文件候选。
def collect_representative_domain_files(domain: dict, project_root: Path, limit: int = 8) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add_candidate(rel_path: str) -> None:
        clean = rel_path.replace("\\", "/")
        if clean in seen:
            return
        seen.add(clean)
        candidates.append(clean)

    for rel in domain.get("paths", []):
        target = (project_root / rel).resolve()
        if not target.exists():
            continue
        if target.is_file():
            add_candidate(rel.replace("\\", "/"))
            continue
        file_candidates: list[str] = []
        for file_path in target.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in REPRESENTATIVE_SCAN_SUFFIXES:
                continue
            try:
                rel_path = file_path.relative_to(project_root).as_posix()
            except ValueError:
                continue
            file_candidates.append(rel_path)
        for rel_path in sorted(file_candidates, key=lambda item: (len(Path(item).parts), item.lower(), item)):
            add_candidate(rel_path)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    return candidates[:limit]


# 归纳功能域在系统中的职责说明。
def collect_domain_role_items(
    domain: dict,
    parent: dict | None,
    child_domains: list[dict],
    all_domains: list[dict],
    current_doc_rel: str,
) -> list[str]:
    items: list[str] = []
    sibling_domains = [
        item
        for item in all_domains
        if item.get("parent_id") == domain.get("parent_id") and item["id"] != domain["id"]
    ]
    if sibling_domains:
        items.append(
            "同级关系：与 "
            + natural_join([domain_ref_for_doc(item, current_doc_rel) for item in sibling_domains[:4]])
            + " 一起构成当前层级的并列功能域。"
        )
    elif parent:
        items.append("同级关系：当前在这一层没有发现明确的并列专题，职责边界相对集中。")
    else:
        items.append("同级关系：当前是系统顶层功能域之一，与其他顶层功能一起构成主骨架。")
    if parent:
        items.append(
            f"对上层作用：作为 {domain_ref_for_doc(parent, current_doc_rel)} 的下级功能域，承接 `{domain['summary']}` 这一层的具体实现或拆分。"
        )
    else:
        items.append("对上层作用：当前位于系统顶层，直接承接项目级目标和整体功能结构。")
    if child_domains:
        items.append(
            f"价值：把 `{domain['title']}` 这一层继续拆成 {len(child_domains)} 个下级专题，帮助收敛边界并组织后续阅读。"
        )
    else:
        items.append(
            f"价值：把 `{domain['title']}` 落到可直接核对的实现证据上，帮助确认这一层的真实行为与边界。"
        )
    return items


# 生成功能域的下级功能列表，仅向下展开一层。
def collect_child_function_items(child_domains: list[dict], current_doc_rel: str) -> list[str]:
    return [f"{domain_ref_for_doc(child, current_doc_rel)}：{child['summary']}" for child in child_domains]


# 归纳叶子节点的关键实现细节。
def collect_implementation_detail_items(
    contexts: list[dict],
    representative_files: list[str],
    project_root: Path,
    current_doc_rel: str,
) -> list[str]:
    items: list[str] = []
    for context in contexts[:3]:
        items.append(context_positioning(context))
    for path in representative_files[:4]:
        observations = collect_source_observations((project_root / path).resolve(), path)
        items.append(f"{source_ref(path, current_doc_rel)}：{'；'.join(observations)}")
    return items[:8]


# 生成文档末尾使用的相关文件树条目。
def collect_file_tree_entries(
    domain: dict,
    contexts: list[dict],
    representative_files: list[str],
    current_doc_rel: str,
    *,
    root_only_directories: bool,
) -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()

    def add_entry(source_rel: str) -> None:
        clean = source_rel.replace("\\", "/").strip("/")
        if not clean or clean in seen:
            return
        seen.add(clean)
        entries.append(source_tree_ref(clean, current_doc_rel))

    if root_only_directories:
        for rel in domain.get("paths", []):
            clean = rel.replace("\\", "/").strip("/")
            if not clean:
                continue
            path_obj = Path(clean)
            if path_obj.suffix and len(path_obj.parts) > 1:
                add_entry(posixpath.dirname(clean))
            elif not path_obj.suffix:
                add_entry(clean.rstrip("/") + "/")
            else:
                add_entry(clean)
        return entries[:8]

    for path in representative_files:
        add_entry(path)
    if not entries:
        for context in contexts:
            add_entry(context["relative_path"])
    return entries[:10]


# 为功能域生成一组弱引导，让 AI 基于证据自行提出问题。
def collect_domain_open_questions(domain: dict, contexts: list[dict], child_domains: list[dict]) -> list[str]:
    questions = [
        f"基于 `summary`、当前功能层级和 `{domain['title']}` 的代码证据，自行提出这一层最值得继续确认的问题。",
    ]
    evidence_points: list[str] = []
    if child_domains:
        evidence_points.append(
            "下级专题域包括 "
            + natural_join([f"`{child['title']}`" for child in child_domains[:4]])
        )
    if contexts:
        evidence_points.append(
            "代码落点包括 "
            + natural_join([f"`{path_display_name(context['relative_path'], context['target_path'].is_dir())}`" for context in contexts[:4]])
        )
    if any(context.get("readme_summary") for context in contexts):
        evidence_points.append("同层 README 也提供了局部语境")
    if evidence_points:
        questions.append(f"提出问题时可以优先围绕这些证据展开：{natural_join(evidence_points)}。")
    questions.append("问题可以聚焦职责边界、主链入口、上下级关系，以及 README 与当前实现是否一致。")
    return questions[:5]


# 汇总单个功能域的证据、层级和文档渲染所需字段。
def analyze_domain(domain: dict, all_domains: list[dict], project_root: Path) -> dict:
    title = domain["title"]
    current_doc_rel = domain.get("doc_path", "")
    parent = next((item for item in all_domains if item["id"] == domain.get("parent_id")), None)
    child_domains = [item for item in all_domains if item.get("parent_id") == domain["id"]]
    contexts = [build_context(path, (project_root / path).resolve(), project_root) for path in domain.get("paths", []) if (project_root / path).exists()]
    representative_files = collect_representative_domain_files(domain, project_root)
    doc_kind = "root" if child_domains else "leaf"
    analysis = {
        "id": domain["id"],
        "title": title,
        "doc_kind": doc_kind,
        "problem_statement": domain["summary"],
        "system_role_items": collect_domain_role_items(domain, parent, child_domains, all_domains, current_doc_rel),
        "child_function_items": collect_child_function_items(child_domains, current_doc_rel),
        "implementation_detail_items": collect_implementation_detail_items(
            contexts,
            representative_files,
            project_root,
            current_doc_rel,
        ),
        "open_questions": collect_domain_open_questions(domain, contexts, child_domains),
        "file_tree_entries": collect_file_tree_entries(
            domain,
            contexts,
            representative_files,
            current_doc_rel,
            root_only_directories=bool(child_domains),
        ),
    }
    return analysis


# 把分析结果渲染成功能域文档，根节点与叶子节点共用主骨架。
def render_domain_doc_from_analysis(analysis: dict) -> str:
    title = analysis["title"]
    sections = [
        f"# 功能域：{title}",
        "",
        "## 1. 这个功能域解决什么问题",
        "",
        analysis["problem_statement"],
        "",
        "## 2. 它在整个系统中的职责是什么",
        "",
        format_bullets(analysis.get("system_role_items", [])),
    ]

    if analysis["doc_kind"] == "root" and analysis.get("child_function_items"):
        sections.extend(
            [
                "",
                "## 3. 它有哪些下级功能",
                "",
                format_bullets(analysis.get("child_function_items", [])),
            ]
        )
    elif analysis["doc_kind"] == "leaf" and analysis.get("implementation_detail_items"):
        sections.extend(
            [
                "",
                "## 3. 关键实现细节",
                "",
                format_bullets(analysis.get("implementation_detail_items", [])),
            ]
        )

    if analysis.get("open_questions"):
        sections.extend(
            [
                "",
                "## 4. 有哪些模糊问题仍需确认",
                "",
                format_bullets(analysis.get("open_questions", [])),
            ]
        )

    sections.extend(
        [
            "",
            "## 5. 相关文件树",
            "",
            format_bullets(analysis.get("file_tree_entries", [])),
        ]
    )
    return "\n".join(sections) + "\n"


# 对外暴露的模块文档生成入口。
def render_domain_doc(domain: dict, all_domains: list[dict], project_root: Path) -> str:
    return render_domain_doc_from_analysis(analyze_domain(domain, all_domains, project_root))


# 当前保留的 README 渲染入口，实际复用模块文档正文。
def render_domain_readme(domain: dict, all_domains: list[dict], project_root: Path) -> str:
    return render_domain_doc(domain, all_domains, project_root)


# 统一处理模块文档索引中使用的链接路径。
def doc_link_path(doc_rel: str, *, from_modules_root: bool = False) -> str:
    if not doc_rel:
        return ""
    normalized = Path(doc_rel)
    if from_modules_root:
        try:
            return normalized.relative_to("modules").as_posix()
        except ValueError:
            return normalized.as_posix()
    return normalized.as_posix()


# 生成带链接或纯文本的功能域标题。
def linked_domain_title(domain: dict, doc_rel: str, *, from_modules_root: bool = False) -> str:
    link_path = doc_link_path(doc_rel, from_modules_root=from_modules_root)
    if not link_path:
        return f"`{domain['title']}`"
    return f"[`{domain['title']}`](./{link_path})"


# 渲染 modules/README.md 中使用的功能域结构总览。
def render_domain_architecture_map(
    module_docs: dict,
    architecture_domains: list[dict] | None = None,
    *,
    from_modules_root: bool = False,
) -> list[str]:
    architecture_domains = architecture_domains or []
    grouped = domains_by_parent(architecture_domains) if architecture_domains else {}
    level_one_domains = grouped.get(None, [])
    if not level_one_domains:
        return ["- 当前还没有稳定的功能域，请先重新扫描并执行收敛。"]

    lines = []
    for domain in level_one_domains:
        doc_rel = module_docs.get(domain["id"], domain.get("doc_path", ""))
        lines.append(f"- {linked_domain_title(domain, doc_rel, from_modules_root=from_modules_root)}：{domain['summary']}")

        children = grouped.get(domain["id"], [])
        if children:
            for index, child in enumerate(children):
                child_doc_rel = module_docs.get(child["id"], child.get("doc_path", ""))
                branch = "└─" if index == len(children) - 1 else "├─"
                child_title = linked_domain_title(child, child_doc_rel, from_modules_root=from_modules_root)
                lines.append(f"  {branch} {child_title}：{child['summary']}")
        else:
            lines.append("  └─ 当前没有单独拆出的第二层专题域，直接进入这一层 README。")

        lines.append("")

    while lines and not lines[-1].strip():
        lines.pop()
    return lines


# 重写 modules/README.md，让模块索引与当前功能树保持一致。
def update_modules_readme(doc_root: Path, module_docs: dict, architecture_domains: list[dict] | None = None) -> None:
    architecture_domains = architecture_domains or []
    architecture_lines = render_domain_architecture_map(
        module_docs,
        architecture_domains,
        from_modules_root=True,
    )
    lines = [
        "# 模块文档",
        "",
        "这里按项目的功能树列出第一层功能域，以及已经单独拆出的下级功能域。",
        "",
        "## 当前功能架构",
        "",
    ]
    lines.extend(architecture_lines)
    (doc_root / "modules" / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# 把 CLI 传入的 target 解析成稳定功能域。
def resolve_domain_target(target: str, architecture_domains: list[dict], project_root: Path) -> tuple[dict, str]:
    cleaned = target.replace("\\", "/").strip("/")
    domain_lookup = {domain["id"]: domain for domain in architecture_domains}
    if cleaned in domain_lookup:
        return domain_lookup[cleaned], "domain_id"

    matches: list[tuple[int, int, dict]] = []
    for domain in architecture_domains:
        for domain_path in domain.get("paths", []):
            normalized_path = domain_path.replace("\\", "/").strip("/")
            if not normalized_path:
                continue
            if cleaned == normalized_path or cleaned.startswith(normalized_path + "/"):
                matches.append((normalized_path.count("/"), int(domain.get("level", 1)), domain))
            elif normalized_path.startswith(cleaned + "/"):
                matches.append((normalized_path.count("/"), int(domain.get("level", 1)), domain))
    if matches:
        matches.sort(key=lambda item: (item[0], item[1], item[2]["id"]), reverse=True)
        return matches[0][2], "path_resolved"

    candidate_path = (project_root / cleaned).resolve()
    if candidate_path.exists():
        raise FileNotFoundError(
            f"目标 `{cleaned}` 当前存在，但还没有映射到稳定功能域。"
            "请先重新扫描功能树，或改为传入明确的功能域 ID。"
        )
    raise FileNotFoundError(f"未找到功能域或路径：{cleaned}")


# 命令行主入口，负责门禁检查、生成文档和回写索引。
def main() -> int:
    parser = argparse.ArgumentParser(description="为功能域创建模块文档。")
    parser.add_argument("--project-root", required=True, help="仓库根目录。")
    parser.add_argument("--doc-root", help="文档根目录。默认使用 <project-root>/project-docs。")
    parser.add_argument(
        "--target",
        action="append",
        required=True,
        help="需要生成文档的功能域 ID。兼容传入路径，但路径会先解析到最接近的功能域。",
    )
    parser.add_argument("--force", action="store_true", help="如果模块文档已存在，则强制重写。")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    doc_root = normalize_doc_root(project_root, args.doc_root).resolve()
    index_path, index_payload = load_index(doc_root)
    ensure_workflow_state(index_payload)

    if not summary_is_confirmed(index_payload):
        print(f"[阻止] {summary_gate_message(index_payload)}")
        print("[下一步] 请先让 `overview/project-summary.md` 成为可继续的项目基线。")
        return 0
    if not structure_is_aligned(index_payload):
        print(f"[阻止] {structure_gate_message(index_payload)}")
        print("[下一步] 请先建立并对齐功能树与代码树映射文档 `overview/project-structure.md`。")
        return 0

    index_payload["skill_name"] = SKILL_NAME
    index_payload["skill_version"] = SKILL_VERSION
    index_payload["doc_schema_version"] = DOC_SCHEMA_VERSION
    mark_modules_drafted(index_payload)
    module_docs = dict(index_payload.get("module_docs", {}))
    generated_docs = set(index_payload.get("generated_docs", []))
    architecture_domains = list(index_payload.get("architecture_domains", []))
    if not architecture_domains:
        raise RuntimeError("当前索引中还没有稳定功能域。请先运行 `scan_project_tree.py` 建立功能树与代码映射。")

    created = []
    resolved_messages = []
    selected_domains: dict[str, dict] = {}

    for target in args.target:
        domain, resolved_by = resolve_domain_target(target, architecture_domains, project_root)
        selected_domains[domain["id"]] = domain
        doc_rel = domain.get("doc_path") or f"modules/{slugify(domain['id'])}.md"
        doc_path = doc_root / doc_rel
        if not doc_path.exists() or args.force:
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(render_domain_doc(domain, architecture_domains, project_root), encoding="utf-8")
            created.append(doc_rel)
        module_docs[domain["id"]] = doc_rel
        generated_docs.add(doc_rel)
        if resolved_by != "domain_id":
            resolved_messages.append(f"`{target}` -> `{domain['title']}`")

    index_payload["module_docs"] = dict(sorted(module_docs.items()))
    index_payload["generated_docs"] = sorted(generated_docs)
    tracked_paths = set(index_payload.get("tracked_paths", []))
    for domain in selected_domains.values():
        tracked_paths.update(domain.get("paths", []))
    index_payload["tracked_paths"] = sorted(tracked_paths)
    git_snapshot = capture_git_snapshot(project_root)
    mark_modules_aligned(index_payload, git_snapshot)
    index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot, align_to_current=True)
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    update_modules_readme(doc_root, module_docs, architecture_domains)

    if created:
        print(f"[完成] 已创建模块文档：{', '.join(created)}")
    else:
        print("[跳过] 没有模块文档被重写。")
    if resolved_messages:
        print(f"[提示] 路径输入已解析到功能域：{'; '.join(resolved_messages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
