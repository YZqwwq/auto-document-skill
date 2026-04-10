#!/usr/bin/env python3
"""
创建第二轮模块文档，并将其登记到 index.json。

这一版把模块文档生成器从“模板解释器”降级为“证据打包器”：
- 脚本负责收集路径事实、候选信号、阅读锚点和待确认问题
- 最终职责判断保留给后续 agent 与用户共同确认
"""

from __future__ import annotations

import argparse
import json
import posixpath
from pathlib import Path

from analysis.architecture_domains import domains_by_parent
from core.git_tracking import capture_git_snapshot, merge_git_state
from core.workflow_state import (
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
MARKDOWN_SUFFIXES = {".md", ".mdx", ".markdown"}
IGNORED_ENTRY_NAMES = {"__pycache__", ".ds_store"}
TEXT_LIKE_SUFFIXES = {
    ".md",
    ".mdx",
    ".markdown",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".vue",
    ".py",
    ".go",
    ".java",
    ".rs",
    ".sh",
}
CODE_LIKE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".vue", ".py", ".go", ".java", ".rs", ".sh"}
SOURCE_DIR_HINTS = {"src", "app", "server", "client", "backend", "frontend", "lib", "packages"}
DOC_DIR_HINTS = {"docs", "doc", "documentation", "developmentlog", "design", "spec", "specs"}
BUILD_DIR_HINTS = {"out", "dist", "build", ".next"}
RESOURCE_DIR_HINTS = {"resources", "assets", "public", "static"}
TEST_DIR_HINTS = {"test", "tests", "__tests__", "spec", "specs"}
CONFIG_FILE_HINTS = {
    "package.json",
    "tsconfig.json",
    "tsconfig.node.json",
    "tsconfig.web.json",
    "pyproject.toml",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "electron-builder.yml",
    "electron-builder.yaml",
    "vite.config.ts",
    "vite.config.js",
    "eslint.config.mjs",
}
CORE_TRAIT_HINTS = {
    "electron": "Electron",
    "electron-builder": "Electron",
    "electron-vite": "Electron",
    "vue": "Vue 3",
    "@vitejs/plugin-vue": "Vue 3",
    "react": "React",
    "next": "Next.js",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
}
STACK_CONFIG_HINTS = {
    "package.json": "发现 `package.json`，说明仓库至少包含 Node.js / 前端工具链信号。",
    "pyproject.toml": "发现 `pyproject.toml`，说明仓库可能包含 Python 工具链或 Python 模块。",
    "Cargo.toml": "发现 `Cargo.toml`，说明仓库可能包含 Rust 模块。",
    "go.mod": "发现 `go.mod`，说明仓库可能包含 Go 模块。",
    "pom.xml": "发现 `pom.xml`，说明仓库可能包含 Java / Maven 工具链。",
}
SIGNAL_RULES = [
    {
        "id": "doc_like",
        "title": "文档/知识候选",
        "summary": "路径名、README 或 Markdown 比例提示这里更像说明、设计资料或知识沉淀位置。",
        "path_names": DOC_DIR_HINTS,
        "child_names": DOC_DIR_HINTS,
        "file_suffixes": MARKDOWN_SUFFIXES,
    },
    {
        "id": "source_like",
        "title": "实现代码候选",
        "summary": "路径名提示这里更像实现代码聚合位置，但真实入口和边界仍需回到代码确认。",
        "path_names": SOURCE_DIR_HINTS,
        "child_names": SOURCE_DIR_HINTS,
        "file_suffixes": CODE_LIKE_SUFFIXES,
    },
    {
        "id": "runtime_like",
        "title": "运行时/服务候选",
        "summary": "命名里出现 main、server、service、runtime、api 等词，提示这里可能接近运行编排或服务实现。",
        "tokens": {"main", "server", "service", "services", "runtime", "api", "backend"},
    },
    {
        "id": "ui_like",
        "title": "界面/交互候选",
        "summary": "命名里出现 renderer、view、page、component、frontend 等词，提示这里可能更靠近界面或交互层。",
        "tokens": {"renderer", "view", "views", "page", "pages", "component", "components", "frontend", "client", "ui"},
    },
    {
        "id": "shared_like",
        "title": "共享能力候选",
        "summary": "命名里出现 share、shared、common、lib 等词，提示这里可能是共享契约、公共能力或通用工具的承载处。",
        "tokens": {"share", "shared", "common", "core", "lib", "libs"},
    },
    {
        "id": "resource_like",
        "title": "资源承载候选",
        "summary": "路径名提示这里更像静态资源、素材或运行时附带资源的承载处。",
        "path_names": RESOURCE_DIR_HINTS,
        "child_names": RESOURCE_DIR_HINTS,
        "tokens": {"assets", "public", "static", "resources"},
    },
    {
        "id": "test_like",
        "title": "测试/样例候选",
        "summary": "命名里出现 test、spec、mock、fixture 等词，提示这里更像验证或示例材料，而不是主链实现。",
        "path_names": TEST_DIR_HINTS,
        "child_names": TEST_DIR_HINTS,
        "tokens": {"test", "tests", "spec", "specs", "mock", "mocks", "fixture", "fixtures", "example", "examples"},
    },
    {
        "id": "build_like",
        "title": "构建产物候选",
        "summary": "路径名提示这里更像构建输出或生成结果，适合核对，不适合直接当成长期真相来源。",
        "path_names": BUILD_DIR_HINTS,
        "child_names": BUILD_DIR_HINTS,
        "tokens": {"dist", "build", "out", ".next"},
    },
    {
        "id": "config_like",
        "title": "配置入口候选",
        "summary": "文件名或后缀提示这里更像工程配置、工具链清单或结构化参数入口。",
        "file_names": CONFIG_FILE_HINTS,
        "file_suffixes": {".json", ".yaml", ".yml", ".toml"},
    },
]
ENTRY_NAME_WEIGHTS = {
    "readme.md": ("说明入口候选", 12, "目录中存在 README，通常适合作为第一层导航入口。"),
    "readme.mdx": ("说明入口候选", 12, "目录中存在 README，通常适合作为第一层导航入口。"),
    "index.ts": ("实现入口候选", 9, "文件名像常见聚合入口，适合先核对它是否承担导出或装配职责。"),
    "index.tsx": ("实现入口候选", 9, "文件名像常见聚合入口，适合先核对它是否承担页面或组件出口职责。"),
    "index.js": ("实现入口候选", 9, "文件名像常见聚合入口，适合先核对它是否承担导出或装配职责。"),
    "index.jsx": ("实现入口候选", 9, "文件名像常见聚合入口，适合先核对它是否承担页面或组件出口职责。"),
    "main.ts": ("主链入口候选", 9, "文件名像主链入口，适合确认这里是否真的是运行起点。"),
    "main.js": ("主链入口候选", 9, "文件名像主链入口，适合确认这里是否真的是运行起点。"),
    "package.json": ("工程入口候选", 9, "这个文件通常能暴露脚本、依赖和工具链信息。"),
}
ENTRY_TOKEN_HINTS = [
    ("entry", "入口候选", 5, "名字里出现 entry，可能承担切入或装配角色。"),
    ("main", "主链入口候选", 5, "名字里出现 main，可能更接近主链起点。"),
    ("app", "应用入口候选", 5, "名字里出现 app，可能更接近应用级装配入口。"),
    ("router", "路由/分发候选", 4, "名字里出现 router，可能承担分发或路由职责。"),
    ("route", "路由/分发候选", 4, "名字里出现 route，可能承担分发或路由职责。"),
    ("service", "服务锚点候选", 4, "名字里出现 service，适合确认它是否是服务实现锚点。"),
    ("provider", "能力提供者候选", 4, "名字里出现 provider，适合确认它是否提供上层能力。"),
    ("client", "调用侧锚点候选", 4, "名字里出现 client，适合确认它是否是对外调用侧。"),
    ("bridge", "桥接候选", 4, "名字里出现 bridge，适合确认它是否承担跨层桥接。"),
    ("config", "配置锚点候选", 4, "名字里出现 config，适合确认它会影响哪些工作流。"),
    ("schema", "结构定义候选", 4, "名字里出现 schema，适合确认这里是否约束数据形态。"),
    ("types", "结构定义候选", 4, "名字里出现 types，适合确认这里是否约束数据形态。"),
    ("model", "结构定义候选", 4, "名字里出现 model，适合确认这里是否保存领域模型。"),
]
REPRESENTATIVE_SCAN_SUFFIXES = CODE_LIKE_SUFFIXES | {".md", ".mdx", ".json", ".yaml", ".yml", ".toml"}


def format_bullets(items: list[str]) -> str:
    return "\n".join([f"- {item}" for item in items]) if items else "- 无"


def normalize_doc_root(project_root: Path, doc_root: str | None) -> Path:
    if doc_root:
        candidate = Path(doc_root)
        return candidate if candidate.is_absolute() else (project_root / candidate)
    return project_root / DEFAULT_DOC_DIR


def slugify(relative_path: str) -> str:
    value = relative_path.replace("\\", "/").strip("/")
    return value.replace("/", "__").replace(":", "").replace(".", "_")


def load_index(doc_root: Path) -> tuple[Path, dict]:
    index_path = doc_root / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"在 {index_path} 未找到 index.json。请先初始化文档。")
    return index_path, json.loads(index_path.read_text(encoding="utf-8"))


def collect_sample_entries(target_path: Path, limit: int = 12) -> list[str]:
    if target_path.is_file():
        return [target_path.name]
    entries = sorted(target_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    sample = []
    for entry in entries:
        if entry.name.lower() in IGNORED_ENTRY_NAMES:
            continue
        sample.append(entry.name + ("/" if entry.is_dir() else ""))
        if len(sample) >= limit:
            break
    return sample


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


def safe_read_text(path: Path, max_chars: int = 6000) -> str | None:
    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except (OSError, UnicodeDecodeError):
        return None


def find_local_readme(target_path: Path) -> Path | None:
    search_dir = target_path if target_path.is_dir() else target_path.parent
    for name in README_CANDIDATES:
        candidate = search_dir / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def extract_markdown_summary(text: str) -> str | None:
    lines = []
    in_code_block = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not line:
            if lines:
                break
            continue
        if line.startswith("#"):
            continue
        if line.startswith(("-", "*", ">")):
            continue
        lines.append(line)
        if len(" ".join(lines)) >= 160:
            break
    if not lines:
        return None
    summary = " ".join(lines).strip()
    if len(summary) > 180:
        summary = summary[:177].rstrip() + "..."
    return summary or None


def detect_project_traits(project_root: Path | None) -> list[str]:
    if project_root is None:
        return []
    package_json = project_root / "package.json"
    if not package_json.exists():
        return []
    text = safe_read_text(package_json, max_chars=20000)
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    dependency_names = set(payload.get("dependencies", {}).keys()) | set(payload.get("devDependencies", {}).keys())
    traits = []
    seen = set()
    for dependency_name, label in CORE_TRAIT_HINTS.items():
        if dependency_name in dependency_names and label not in seen:
            seen.add(label)
            traits.append(label)
    return traits


def path_display_name(path_text: str, is_dir: bool | None = None) -> str:
    clean = path_text.replace("\\", "/").strip("/")
    if not clean:
        return "/"
    name = clean.split("/")[-1]
    if is_dir is True and not name.endswith("/"):
        return name + "/"
    return name


def natural_join(items: list[str]) -> str:
    cleaned = [item for item in items if item]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} 和 {cleaned[1]}"
    return f"{'、'.join(cleaned[:-1])} 以及 {cleaned[-1]}"


def path_name_parts(relative_path: str, target_path: Path) -> list[str]:
    clean = relative_path.replace("\\", "/").strip("/")
    parts = [part.lower() for part in clean.split("/") if part]
    if target_path.name:
        parts.append(target_path.name.lower())
    return list(dict.fromkeys(parts))


def suffix_label(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MARKDOWN_SUFFIXES:
        return "Markdown 文档"
    if suffix in CODE_LIKE_SUFFIXES:
        return "代码文件"
    if suffix in {".json", ".yaml", ".yml", ".toml"}:
        return "配置或结构化文本"
    if suffix:
        return f"`{suffix}` 文件"
    return "无后缀文件"


def sibling_modules(project_root: Path | None, target_path: Path) -> dict[str, str]:
    if project_root is None:
        return {}
    top_level = {}
    for candidate in ("src", "app", "server", "client", "packages"):
        path = project_root / candidate
        if path.exists() and path.resolve() != target_path.resolve():
            top_level["source"] = candidate
            break
    for candidate in ("developmentlog", "docs", "doc", "project-docs"):
        path = project_root / candidate
        if path.exists() and path.resolve() != target_path.resolve():
            top_level["docs"] = candidate
            break
    for candidate in ("out", "dist", "build"):
        path = project_root / candidate
        if path.exists() and path.resolve() != target_path.resolve():
            top_level["build"] = candidate
            break
    for candidate in ("resources", "assets", "public", "static"):
        path = project_root / candidate
        if path.exists() and path.resolve() != target_path.resolve():
            top_level["resources"] = candidate
            break
    return top_level


def collect_stack_hints(project_root: Path | None, target_path: Path, project_traits: list[str]) -> list[str]:
    hints = []
    if project_traits:
        hints.append(f"从依赖特征看，仓库当前至少暴露出 {natural_join(project_traits)} 等技术栈信号。")
    if project_root is not None:
        for name, statement in STACK_CONFIG_HINTS.items():
            if (project_root / name).exists():
                hints.append(statement)
    if target_path.is_dir():
        for name in ("package.json", "pyproject.toml", "Cargo.toml", "go.mod"):
            candidate = target_path / name
            if candidate.exists():
                hints.append(f"`{target_path.name or '.'}/` 下存在 `{name}`，说明这一块可能自带独立的工具链或子模块边界。")
    return list(dict.fromkeys(hints))


def collect_path_facts(relative_path: str, target_path: Path, child_dirs: list[str], child_files: list[str], sample_entries: list[str], readme_path: Path | None, readme_summary: str | None) -> list[str]:
    facts = [
        f"当前路径是{'文件' if target_path.is_file() else '目录'}，相对路径为 `{relative_path}`。",
        f"路径深度约为 {max(1, len([part for part in relative_path.split('/') if part]))} 层。",
    ]
    if target_path.is_file():
        facts.append(f"文件类型信号：{suffix_label(target_path)}。")
        facts.append(f"所在目录为 `{target_path.parent.name or '.'}`。")
    else:
        facts.append(f"当前可直接看到 {len(child_dirs)} 个子目录、{len(child_files)} 个文件。")
        if sample_entries:
            facts.append(f"首批可见条目包括 {natural_join([f'`{name}`' for name in sample_entries[:6]])}。")
    if readme_path:
        facts.append(f"同层存在 `{readme_path.name}`，这通常意味着这里已经有一层本地说明入口。")
    if readme_summary:
        facts.append(f"本地 README 摘要信号：{readme_summary}")
    return facts


def _match_rule_basis(rule: dict, relative_path: str, target_path: Path, child_dirs: list[str], child_files: list[str]) -> list[str]:
    bases: list[str] = []
    parts = set(path_name_parts(relative_path, target_path))
    child_names = {name.lower() for name in child_dirs + child_files}
    path_name = target_path.name.lower()
    suffix = target_path.suffix.lower()

    for candidate in rule.get("path_names", set()):
        if candidate.lower() == path_name or candidate.lower() in parts:
            bases.append(f"路径名包含 `{candidate}`。")
            break
    for candidate in rule.get("child_names", set()):
        if candidate.lower() in child_names:
            bases.append(f"子条目中出现 `{candidate}`。")
            break
    for token in rule.get("tokens", set()):
        if any(token in item for item in parts | child_names):
            bases.append(f"命名里出现 `{token}` 相关信号。")
            break
    if target_path.is_file():
        for candidate in rule.get("file_names", set()):
            if target_path.name.lower() == candidate.lower():
                bases.append(f"文件名命中 `{candidate}`。")
                break
        if suffix and suffix in rule.get("file_suffixes", set()):
            bases.append(f"文件后缀为 `{suffix}`。")
    else:
        if child_files:
            markdown_count = sum(1 for name in child_files if Path(name).suffix.lower() in MARKDOWN_SUFFIXES)
            code_count = sum(1 for name in child_files if Path(name).suffix.lower() in CODE_LIKE_SUFFIXES)
            if rule["id"] == "doc_like" and markdown_count >= max(2, len(child_files) // 2):
                bases.append("当前目录内 Markdown 文件占比较高。")
            if rule["id"] == "doc_like" and any(name.lower() in {candidate.lower() for candidate in README_CANDIDATES} for name in child_files):
                bases.append("当前目录内存在 README。")
            if rule["id"] == "source_like" and code_count >= max(1, len(child_files) // 2):
                bases.append("当前目录内可见代码文件占比较高。")
    return bases


def collect_module_signals(relative_path: str, target_path: Path, child_dirs: list[str], child_files: list[str]) -> list[dict]:
    signals = []
    for rule in SIGNAL_RULES:
        basis = _match_rule_basis(rule, relative_path, target_path, child_dirs, child_files)
        if not basis:
            continue
        strength = min(5, max(1, len(basis)))
        signals.append(
            {
                "id": rule["id"],
                "title": rule["title"],
                "summary": rule["summary"],
                "basis": basis,
                "signal_type": "module_candidate",
                "signal_strength": strength,
                "candidate": True,
            }
        )
    signals.sort(key=lambda item: (-item["signal_strength"], item["title"]))
    return signals


def detect_module_kind(relative_path: str, target_path: Path, child_dirs: list[str], child_files: list[str]) -> str:
    signals = collect_module_signals(relative_path, target_path, child_dirs, child_files)
    if signals:
        return signals[0]["id"]
    return "generic_file" if target_path.is_file() else "generic_directory"


def score_entry_candidate(name: str, is_dir: bool) -> tuple[int, str, list[str]]:
    score = 1
    reasons: list[str] = []
    clean = name.rstrip("/")
    lower_name = clean.lower()

    direct = ENTRY_NAME_WEIGHTS.get(lower_name)
    if direct:
        label, delta, reason = direct
        score += delta
        reasons.append(reason)
    else:
        label = "继续核对候选"

    for token, token_label, delta, reason in ENTRY_TOKEN_HINTS:
        if token in lower_name:
            label = token_label
            score += delta
            reasons.append(reason)

    suffix = Path(clean).suffix.lower()
    if is_dir:
        score += 2
        reasons.append("这是一个子目录，通常可以继续向下核对职责分层。")
    elif suffix in CODE_LIKE_SUFFIXES:
        score += 3
        reasons.append("这是一个代码文件，适合继续确认真实实现。")
    elif suffix in MARKDOWN_SUFFIXES:
        score += 2
        reasons.append("这是一个说明文档，适合先建立上下文。")
    elif suffix in {".json", ".yaml", ".yml", ".toml"}:
        score += 2
        reasons.append("这是一个配置或结构化文本文件，适合确认工具链与参数边界。")

    if not reasons:
        reasons.append("这个条目位于当前路径的第一层，适合作为继续核对的起点。")
    return score, label, reasons


def collect_entry_candidates(relative_path: str, target_path: Path, sample_entries: list[str], readme_path: Path | None) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()

    def add_candidate(display_name: str, rel_path: str, is_dir: bool) -> None:
        clean_rel = rel_path.replace("\\", "/").strip("/")
        if not clean_rel or clean_rel in seen:
            return
        seen.add(clean_rel)
        score, label, reasons = score_entry_candidate(display_name, is_dir)
        candidates.append(
            {
                "path": clean_rel,
                "name": display_name,
                "label": label,
                "basis": reasons,
                "score": score,
                "is_dir": is_dir,
            }
        )

    if target_path.is_file():
        add_candidate(target_path.name, relative_path, False)
    else:
        if readme_path:
            readme_rel = (Path(relative_path) / readme_path.name).as_posix() if relative_path else readme_path.name
            add_candidate(readme_path.name, readme_rel, False)
        for entry in sample_entries[:8]:
            is_dir = entry.endswith("/")
            display_name = entry.rstrip("/")
            rel_path = (Path(relative_path) / display_name).as_posix() if relative_path else display_name
            add_candidate(display_name, rel_path, is_dir)

    candidates.sort(key=lambda item: (-item["score"], item["path"]))
    return candidates[:8]


def infer_relationship_hints(siblings: dict[str, str], candidate_signals: list[dict]) -> list[str]:
    hints = []
    signal_ids = {item["id"] for item in candidate_signals}
    if "source" in siblings and "docs" in siblings:
        hints.append(f"仓库同时存在 `{siblings['source']}/` 与 `{siblings['docs']}/`，当前路径可能处在“文档解释”和“真实实现”之间的某个连接点。")
    elif "source" in siblings:
        hints.append(f"仓库存在 `{siblings['source']}/`，需要时应回到那里核对真实实现与调用链。")
    if "build" in siblings and "build_like" not in signal_ids:
        hints.append(f"仓库存在 `{siblings['build']}/`，若当前路径与构建输出有关，建议核对它与源码路径是否一致。")
    if "resources" in siblings and "resource_like" not in signal_ids:
        hints.append(f"仓库存在 `{siblings['resources']}/`，若当前路径涉及素材或静态资源，应继续确认引用关系。")
    if not hints:
        hints.append("当前路径与相邻模块的关系还不稳定，建议结合上一级目录与引用链一起确认。")
    return hints


def infer_open_questions(relative_path: str, target_path: Path, candidate_signals: list[dict], readme_summary: str | None) -> list[str]:
    questions = [
        f"`{relative_path}` 在当前 summary 语义里到底属于“稳定职责边界”还是“暂时的目录组织”?",
    ]
    signal_ids = {item["id"] for item in candidate_signals}
    if target_path.is_dir():
        questions.append("这里真正的阅读起点是 README、入口文件，还是某个更深层子目录?")
    else:
        questions.append("这个文件是主入口、辅助实现，还是仅仅因为命名显眼才被看到?")
    if "doc_like" in signal_ids and "source_like" in signal_ids:
        questions.append("这里同时出现文档和实现信号，后续文档里应把它写成“说明层”还是“实现层”?")
    if "build_like" in signal_ids:
        questions.append("这里是应该长期维护的源码面，还是一次构建后生成的结果面?")
    if "config_like" in signal_ids:
        questions.append("这里影响的是整个项目、某个子模块，还是只影响局部工具链?")
    if readme_summary:
        questions.append("README 的表述和当前代码结构是否一致，是否需要由用户补充长期目标而不是只描述当前状态?")
    return questions[:6]


def infer_update_conditions(relative_path: str, target_path: Path, candidate_signals: list[dict]) -> list[str]:
    items = [
        f"`{relative_path}` 下的目录结构、入口文件或关键说明发生实质变化时。",
        "当前文档里列出的候选入口已经不再适合作为第一阅读顺序时。",
    ]
    signal_ids = {item["id"] for item in candidate_signals}
    if "doc_like" in signal_ids:
        items.append("README 或专题说明已经不能反映当前代码真相时。")
    if "config_like" in signal_ids:
        items.append("工具链、脚本命令或关键配置文件发生变化时。")
    if target_path.is_dir():
        items.append("当前路径内部职责被拆分、合并或迁移到其他目录时。")
    return items


def build_context(relative_path: str, target_path: Path, project_root: Path | None = None) -> dict:
    sample_entries = collect_sample_entries(target_path)
    child_dirs, child_files = collect_child_names(target_path)
    readme_path = find_local_readme(target_path)
    readme_summary = extract_markdown_summary(safe_read_text(readme_path) or "") if readme_path else None
    project_traits = detect_project_traits(project_root)
    candidate_signals = collect_module_signals(relative_path, target_path, child_dirs, child_files)
    return {
        "relative_path": relative_path,
        "target_path": target_path,
        "path_type": "文件" if target_path.is_file() else "目录",
        "sample_entries": sample_entries,
        "child_dirs": child_dirs,
        "child_files": child_files,
        "readme_path": readme_path,
        "readme_summary": readme_summary,
        "project_traits": project_traits,
        "kind": candidate_signals[0]["id"] if candidate_signals else detect_module_kind(relative_path, target_path, child_dirs, child_files),
        "siblings": sibling_modules(project_root, target_path),
        "path_facts": collect_path_facts(relative_path, target_path, child_dirs, child_files, sample_entries, readme_path, readme_summary),
        "candidate_signals": candidate_signals,
        "stack_hints": collect_stack_hints(project_root, target_path, project_traits),
        "entry_candidates": collect_entry_candidates(relative_path, target_path, sample_entries, readme_path),
    }


def render_signal(signal: dict) -> str:
    basis_text = "；".join(signal.get("basis", [])) if signal.get("basis") else "缺少明确依据"
    return f"`{signal['title']}`：{signal['summary']} 依据：{basis_text}"


def render_entry_candidate(entry: dict) -> str:
    basis = "；".join(entry.get("basis", []))
    display = f"`{entry['path']}`"
    return f"{display}：{entry['label']}。{basis}"


def context_positioning(context: dict) -> str:
    relative_path = context["relative_path"]
    signal_titles = [f"“{signal['title']}”" for signal in context["candidate_signals"][:2]]
    if signal_titles:
        return (
            f"`{relative_path}` 当前主要暴露出 {natural_join(signal_titles)} 等候选信号。"
            "这更像一个需要继续核对的证据入口，而不是已经被脚本确认的职责结论。"
        )
    if context["target_path"].is_file():
        return f"`{relative_path}` 当前还没有明显的类型信号，它更像一个需要结合上下文再判断的单文件入口。"
    return f"`{relative_path}` 当前还没有明显的职责信号，它更像一个需要结合上层 summary 再判断的目录容器。"


def render_module_doc(relative_path: str, target_path: Path, project_root: Path | None = None) -> str:
    context = build_context(relative_path, target_path, project_root)
    path_type = "文件" if target_path.is_file() else "目录"
    return f"""# 模块：{relative_path}

## 当前证据定位

{context_positioning(context)}

## 范围

- 路径：`{relative_path}`
- 类型：`{path_type}`

## 可直接观察到的事实

{format_bullets(context["path_facts"])}

## 技术栈线索

{format_bullets(context["stack_hints"])}

## 候选信号

{format_bullets([render_signal(item) for item in context["candidate_signals"]]) if context["candidate_signals"] else "- 暂无明显信号"}

## 优先核对的入口或条目

{format_bullets([render_entry_candidate(item) for item in context["entry_candidates"]]) if context["entry_candidates"] else "- 暂无可用入口"}

## 相邻路径提示

{format_bullets(infer_relationship_hints(context["siblings"], context["candidate_signals"]))}

## 继续确认的问题

{format_bullets(infer_open_questions(relative_path, target_path, context["candidate_signals"], context["readme_summary"]))}

## 何时更新本文件

{format_bullets(infer_update_conditions(relative_path, target_path, context["candidate_signals"]))}
"""


def format_domain_path_entry(context: dict) -> str:
    relative_path = context["relative_path"]
    statement = context_positioning(context)
    prefix = f"`{relative_path}` "
    if statement.startswith(prefix):
        statement = statement[len(prefix):]
    return f"`{relative_path}`：{statement}"


def shared_prefix_parts(paths: list[str]) -> list[str]:
    cleaned = [path.replace("\\", "/").strip("/").split("/") for path in paths if path.replace("\\", "/").strip("/")]
    if not cleaned:
        return []
    if len(cleaned) == 1:
        parts = cleaned[0]
        return parts[:-1]
    prefix: list[str] = []
    for items in zip(*cleaned):
        if len(set(items)) != 1:
            break
        prefix.append(items[0])
    return prefix


def compact_context_entries(contexts: list[dict]) -> tuple[str | None, list[tuple[str, str]]]:
    if not contexts:
        return None, []
    prefix_parts = shared_prefix_parts([context["relative_path"] for context in contexts])
    prefix_text = "/".join(prefix_parts) if prefix_parts else None
    entries = []
    for context in contexts:
        parts = context["relative_path"].replace("\\", "/").strip("/").split("/")
        suffix_parts = parts[len(prefix_parts):] if prefix_parts else parts
        suffix_text = "/".join(suffix_parts) if suffix_parts else parts[-1]
        label = path_display_name(suffix_text, context["target_path"].is_dir())
        entries.append((label, context_positioning(context).replace(f"`{context['relative_path']}` ", "", 1).strip()))
    return prefix_text, entries


def render_compact_context_section(contexts: list[dict]) -> str:
    prefix_text, entries = compact_context_entries(contexts)
    lines: list[str] = []
    if prefix_text:
        lines.extend([f"路径前缀：`{prefix_text}/`", ""])
    lines.extend([f"- `{label}`：{summary}" for label, summary in entries])
    return "\n".join(lines) if lines else "- 暂无路径"


def relative_doc_link(from_doc_rel: str, to_doc_rel: str) -> str:
    from_dir = posixpath.dirname(from_doc_rel)
    return posixpath.relpath(to_doc_rel, start=from_dir or ".")


def relative_source_link(from_doc_rel: str, source_rel: str) -> str:
    from_dir = posixpath.dirname(from_doc_rel)
    clean = source_rel.replace("\\", "/").strip("/")
    return posixpath.relpath(clean, start=from_dir or ".")


def domain_ref_for_doc(target_domain: dict, current_doc_rel: str) -> str:
    target_doc_rel = target_domain.get("doc_path", "")
    if not target_doc_rel or target_doc_rel == current_doc_rel:
        return f"`{target_domain['title']}`"
    return f"[`{target_domain['title']}`](./{relative_doc_link(current_doc_rel, target_doc_rel)})"


def describe_domain_file_role(path: Path) -> str:
    lower_name = path.name.lower()
    suffix = path.suffix.lower()
    if path.is_dir():
        return "继续下钻候选目录"
    if "readme" in lower_name:
        return "说明入口候选"
    if any(token in lower_name for token in ("index", "main", "entry", "app")):
        return "实现入口候选"
    if any(token in lower_name for token in ("config", "setting", "settings")) or suffix in {".json", ".yaml", ".yml", ".toml"}:
        return "配置锚点候选"
    if suffix in MARKDOWN_SUFFIXES:
        return "文档补充候选"
    if any(token in lower_name for token in ("test", "spec", "mock", "fixture")):
        return "测试或样例候选"
    if suffix in CODE_LIKE_SUFFIXES:
        return "继续核对的实现文件"
    return "继续核对的关键文件"


def describe_domain_source_label(source_rel: str, domain_id: str) -> str:
    del domain_id
    path = Path(source_rel)
    label = describe_domain_file_role(path)
    if label == "继续核对的关键文件":
        return path_display_name(source_rel, path.suffix == "")
    return label


def source_ref(source_rel: str, current_doc_rel: str, domain_id: str) -> str:
    label = describe_domain_source_label(source_rel, domain_id)
    target = relative_source_link(current_doc_rel, source_rel)
    return f"[`{label}`](./{target})"


def labeled_source_ref(current_doc_rel: str, source_rel: str, label: str) -> str:
    target = relative_source_link(current_doc_rel, source_rel)
    return f"[`{label}`](./{target})"


def render_local_domain_hierarchy(domain: dict, all_domains: list[dict]) -> str:
    current_doc_rel = domain.get("doc_path", "")
    domain_lookup = {item["id"]: item for item in all_domains}
    children_map = domains_by_parent(all_domains)
    parent = domain_lookup.get(domain.get("parent_id"))
    grandparent = domain_lookup.get(parent.get("parent_id")) if parent and parent.get("parent_id") else None
    current_children = children_map.get(domain["id"], [])

    def line(item: dict, *, current: bool = False) -> str:
        suffix = "（当前文档）" if current else ""
        return f"{domain_ref_for_doc(item, current_doc_rel)}：{item['summary']}{suffix}"

    if grandparent and parent:
        lines = [f"- {line(grandparent)}"]
        grandparent_children = children_map.get(grandparent["id"], [])
        for parent_index, parent_sibling in enumerate(grandparent_children):
            parent_is_last = parent_index == len(grandparent_children) - 1
            parent_branch = "└─" if parent_is_last else "├─"
            lines.append(f"  {parent_branch} {line(parent_sibling)}")
            if parent_sibling["id"] != parent["id"]:
                continue
            nested_prefix = "   " if parent_is_last else "│  "
            sibling_domains = children_map.get(parent["id"], [])
            for sibling_index, sibling in enumerate(sibling_domains):
                sibling_is_last = sibling_index == len(sibling_domains) - 1
                sibling_branch = "└─" if sibling_is_last else "├─"
                is_current = sibling["id"] == domain["id"]
                lines.append(f"  {nested_prefix}{sibling_branch} {line(sibling, current=is_current)}")
                if not is_current or not current_children:
                    continue
                child_prefix = "   " if sibling_is_last else "│  "
                for child_index, child in enumerate(current_children):
                    child_is_last = child_index == len(current_children) - 1
                    child_branch = "└─" if child_is_last else "├─"
                    lines.append(f"  {nested_prefix}{child_prefix}{child_branch} {line(child)}")
        return "\n".join(lines)

    if parent:
        lines = [f"- {line(parent)}"]
        sibling_domains = children_map.get(parent["id"], [])
        for sibling_index, sibling in enumerate(sibling_domains):
            sibling_is_last = sibling_index == len(sibling_domains) - 1
            sibling_branch = "└─" if sibling_is_last else "├─"
            is_current = sibling["id"] == domain["id"]
            lines.append(f"  {sibling_branch} {line(sibling, current=is_current)}")
            if not is_current or not current_children:
                continue
            child_prefix = "   " if sibling_is_last else "│  "
            for child_index, child in enumerate(current_children):
                child_is_last = child_index == len(current_children) - 1
                child_branch = "└─" if child_is_last else "├─"
                lines.append(f"  {child_prefix}{child_branch} {line(child)}")
        return "\n".join(lines)

    lines = [f"- {line(domain, current=True)}"]
    for child_index, child in enumerate(current_children):
        child_is_last = child_index == len(current_children) - 1
        child_branch = "└─" if child_is_last else "├─"
        lines.append(f"  {child_branch} {line(child)}")
    return "\n".join(lines)


def score_domain_file(path: Path, domain_id: str) -> int:
    del domain_id
    score = 1
    lower_name = path.name.lower()
    if "readme" in lower_name:
        score += 10
    if any(token in lower_name for token in ("index", "main", "entry", "app")):
        score += 8
    if any(token in lower_name for token in ("config", "schema", "types", "model", "router", "route", "service", "provider", "client", "bridge")):
        score += 4
    if any(token in lower_name for token in ("test", "spec", "mock", "fixture")):
        score -= 4
    if path.suffix.lower() in CODE_LIKE_SUFFIXES:
        score += 3
    elif path.suffix.lower() in MARKDOWN_SUFFIXES:
        score += 2
    elif path.suffix.lower() in {".json", ".yaml", ".yml", ".toml"}:
        score += 2
    if len(path.parts) <= 6:
        score += 1
    return score


def collect_representative_domain_files(domain: dict, project_root: Path, limit: int = 8) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for rel in domain.get("paths", []):
        target = (project_root / rel).resolve()
        if not target.exists():
            continue
        if target.is_file():
            score = score_domain_file(target, domain["id"])
            candidates.append((score, rel.replace("\\", "/")))
            continue
        for file_path in target.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in REPRESENTATIVE_SCAN_SUFFIXES:
                continue
            try:
                rel_path = file_path.relative_to(project_root).as_posix()
            except ValueError:
                continue
            if rel_path in seen:
                continue
            seen.add(rel_path)
            score = score_domain_file(file_path, domain["id"])
            if score <= 0:
                continue
            candidates.append((score, rel_path))
    ranked = sorted(candidates, key=lambda item: (-item[0], item[1]))
    return [path for _, path in ranked[:limit]]


def aggregate_context_signals(contexts: list[dict], limit: int = 8) -> list[str]:
    grouped: dict[str, dict] = {}
    for context in contexts:
        label = f"`{path_display_name(context['relative_path'], context['target_path'].is_dir())}`"
        for signal in context.get("candidate_signals", []):
            bucket = grouped.setdefault(
                signal["id"],
                {
                    "title": signal["title"],
                    "summary": signal["summary"],
                    "paths": [],
                    "basis": [],
                    "strength": 0,
                },
            )
            bucket["paths"].append(label)
            bucket["basis"].extend(signal.get("basis", []))
            bucket["strength"] = max(bucket["strength"], signal.get("signal_strength", 1))
    ranked = sorted(grouped.values(), key=lambda item: (-len(item["paths"]), -item["strength"], item["title"]))
    lines = []
    for item in ranked[:limit]:
        unique_paths = list(dict.fromkeys(item["paths"]))[:3]
        unique_basis = list(dict.fromkeys(item["basis"]))[:2]
        path_text = natural_join(unique_paths)
        basis_text = "；".join(unique_basis) if unique_basis else "暂无更具体依据"
        lines.append(f"`{item['title']}`：主要出现在 {path_text}。{item['summary']} 依据：{basis_text}")
    return lines


def collect_domain_open_questions(domain: dict, contexts: list[dict], child_domains: list[dict]) -> list[str]:
    questions = [
        f"`{domain['title']}` 这一层在用户确认后的 summary 中，究竟代表稳定功能域，还是只是当前实现阶段的临时分组?",
    ]
    if child_domains:
        questions.append("下级专题域的拆分是否真的按职责边界完成，还是只是沿着目录树继续切?")
    elif contexts:
        questions.append("这几个覆盖路径之间到底谁是主链，谁只是辅助或补充材料?")
    if any(context.get("readme_summary") for context in contexts):
        questions.append("README 里的说法是否只是当前状态描述，还是能代表项目最终希望形成的长期结构?")
    return questions[:5]


def collect_domain_reading_items(domain: dict, contexts: list[dict], child_domains: list[dict], current_doc_rel: str) -> list[str]:
    items = []
    if child_domains:
        for child in child_domains:
            items.append(f"如果问题已经缩小到“{child['summary']}”，继续进入 {domain_ref_for_doc(child, current_doc_rel)}。")
    else:
        for context in contexts[:3]:
            entries = context.get("entry_candidates", [])
            if entries:
                items.append(f"先从 `{entries[0]['path']}` 开始核对，再沿着相邻目录或调用链继续向下读。")
            else:
                items.append(f"先从 `{context['relative_path']}` 所在路径开始，再确认实际入口文件。")
    if not items:
        items.append("当前还缺少稳定阅读顺序，建议先回到 summary 和 structure 重新确认这一层的定位。")
    return items[:6]


def analyze_domain(domain: dict, all_domains: list[dict], project_root: Path) -> dict:
    title = domain["title"]
    current_doc_rel = domain.get("doc_path", "")
    parent = next((item for item in all_domains if item["id"] == domain.get("parent_id")), None)
    child_domains = [item for item in all_domains if item.get("parent_id") == domain["id"]]
    contexts = [build_context(path, (project_root / path).resolve(), project_root) for path in domain.get("paths", []) if (project_root / path).exists()]
    hierarchy_map = render_local_domain_hierarchy(domain, all_domains)
    coverage_list = render_compact_context_section(contexts)
    signal_items = aggregate_context_signals(contexts)
    analysis = {
        "id": domain["id"],
        "title": title,
        "summary": domain["summary"],
        "level": domain["level"],
        "doc_path": current_doc_rel,
        "parent_id": domain.get("parent_id"),
        "parent_title": parent["title"] if parent else None,
        "has_children": bool(child_domains),
        "hierarchy_map": hierarchy_map,
        "contexts": [
            {
                "path": context["relative_path"],
                "summary": context_positioning(context),
                "signals": [signal["title"] for signal in context.get("candidate_signals", [])[:3]],
            }
            for context in contexts
        ],
        "coverage_list": coverage_list,
        "signal_items": signal_items,
        "reading_items": collect_domain_reading_items(domain, contexts, child_domains, current_doc_rel),
        "open_questions": collect_domain_open_questions(domain, contexts, child_domains),
    }
    if child_domains:
        analysis["doc_kind"] = "root"
        analysis["implementation_views"] = [
            f"`{path_display_name(context['relative_path'], context['target_path'].is_dir())}`：{context_positioning(context)}"
            for context in contexts
        ]
        analysis["split_views"] = [f"`{child['title']}`：{child['summary']}" for child in child_domains]
        return analysis

    representative_files = collect_representative_domain_files(domain, project_root)
    related_paths = [
        f"{source_ref(context['relative_path'], current_doc_rel, domain['id'])}：{context_positioning(context)}"
        for context in contexts
    ]
    analysis["doc_kind"] = "leaf"
    analysis["evidence_chain"] = [
        f"`{domain['title']}` 当前主要由 {natural_join([f'`{path_display_name(context['relative_path'], context['target_path'].is_dir())}`' for context in contexts[:3]])} 等路径提供证据。"
        if contexts
        else f"`{domain['title']}` 当前缺少稳定的覆盖路径，需要重新扫描或补充结构。"
    ]
    analysis["related_paths"] = related_paths
    analysis["representative_files"] = [
        {
            "path": path,
            "entry": f"{source_ref(path, current_doc_rel, domain['id'])}：{describe_domain_file_role((project_root / path).resolve())}",
        }
        for path in representative_files
    ]
    analysis["entry_candidates"] = [
        render_entry_candidate(item)
        for context in contexts
        for item in context.get("entry_candidates", [])[:3]
    ][:8]
    return analysis


def render_domain_doc_from_analysis(analysis: dict) -> str:
    title = analysis["title"]
    if analysis["doc_kind"] == "root":
        return f"""# 功能域：{title}

## 定位

{analysis['summary']}

## 当前功能层级

{analysis['hierarchy_map']}

## 这一层主要承载什么

{format_bullets(analysis.get('implementation_views', []))}

## 这一层内部怎么分

{format_bullets(analysis.get('split_views', []))}

## 相关实现路径

{analysis.get('coverage_list', '- 暂无路径')}

## 这一层暴露出的候选信号

{format_bullets(analysis.get('signal_items', []))}

## 阅读建议

{format_bullets(analysis.get('reading_items', []))}

## 待确认问题

{format_bullets(analysis.get('open_questions', []))}
"""

    return f"""# 功能域：{title}

## 一句话定位

{analysis['summary']}

## 当前功能层级

{analysis['hierarchy_map']}

## 证据链概览

{format_bullets(analysis.get('evidence_chain', []))}

## 候选信号

{format_bullets(analysis.get('signal_items', []))}

## 相关实现路径

{format_bullets(analysis.get('related_paths', [])) if analysis.get('related_paths') else '- 暂无路径'}

## 优先核对文件

{format_bullets([item['entry'] for item in analysis.get('representative_files', [])]) if analysis.get('representative_files') else '- 暂无代表性文件'}

## 继续核对的入口

{format_bullets(analysis.get('entry_candidates', [])) if analysis.get('entry_candidates') else '- 暂无可用入口'}

## 待确认问题

{format_bullets(analysis.get('open_questions', []))}
"""


def render_domain_doc(domain: dict, all_domains: list[dict], project_root: Path) -> str:
    return render_domain_doc_from_analysis(analyze_domain(domain, all_domains, project_root))


def render_domain_readme(domain: dict, all_domains: list[dict], project_root: Path) -> str:
    return render_domain_doc(domain, all_domains, project_root)


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


def linked_domain_title(domain: dict, doc_rel: str, *, from_modules_root: bool = False) -> str:
    link_path = doc_link_path(doc_rel, from_modules_root=from_modules_root)
    if not link_path:
        return f"`{domain['title']}`"
    return f"[`{domain['title']}`](./{link_path})"


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
        "这里按项目的功能架构列出第一层功能域，以及已经单独拆出的第二层专题域。",
        "",
        "## 当前功能架构",
        "",
    ]
    lines.extend(architecture_lines)
    (doc_root / "modules" / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="为重要项目路径创建模块文档。")
    parser.add_argument("--project-root", required=True, help="仓库根目录。")
    parser.add_argument("--doc-root", help="文档根目录。默认使用 <project-root>/project-docs。")
    parser.add_argument("--target", action="append", required=True, help="需要生成文档的项目相对路径。")
    parser.add_argument("--force", action="store_true", help="如果模块文档已存在，则强制重写。")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    doc_root = normalize_doc_root(project_root, args.doc_root).resolve()
    index_path, index_payload = load_index(doc_root)
    ensure_workflow_state(index_payload)

    if not summary_is_confirmed(index_payload):
        print(f"[阻止] {summary_gate_message(index_payload)}")
        print("[下一步] 请先确认 `overview/project-summary.md`。")
        return 0
    if not structure_is_aligned(index_payload):
        print(f"[阻止] {structure_gate_message(index_payload)}")
        print("[下一步] 请先建立并对齐 `overview/project-structure.md`。")
        return 0

    index_payload["skill_name"] = SKILL_NAME
    index_payload["skill_version"] = SKILL_VERSION
    index_payload["doc_schema_version"] = DOC_SCHEMA_VERSION
    mark_modules_drafted(index_payload)
    module_docs = dict(index_payload.get("module_docs", {}))
    generated_docs = set(index_payload.get("generated_docs", []))
    created = []

    for target in args.target:
        rel = target.replace("\\", "/").strip("/")
        target_path = (project_root / rel).resolve()
        if not target_path.exists():
            raise FileNotFoundError(f"目标路径不存在：{target_path}")
        doc_rel = f"modules/{slugify(rel)}.md"
        doc_path = doc_root / doc_rel
        if not doc_path.exists() or args.force:
            doc_path.write_text(render_module_doc(rel, target_path, project_root), encoding="utf-8")
            created.append(doc_rel)
        module_docs[rel] = doc_rel
        generated_docs.add(doc_rel)

    index_payload["module_docs"] = dict(sorted(module_docs.items()))
    index_payload["generated_docs"] = sorted(generated_docs)
    tracked_paths = set(index_payload.get("tracked_paths", []))
    tracked_paths.update(module_docs.keys())
    index_payload["tracked_paths"] = sorted(tracked_paths)
    git_snapshot = capture_git_snapshot(project_root)
    mark_modules_aligned(index_payload, git_snapshot)
    index_payload["git_state"] = merge_git_state(index_payload.get("git_state", {}), git_snapshot, align_to_current=True)
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    update_modules_readme(doc_root, module_docs, list(index_payload.get("architecture_domains", [])))

    if created:
        print(f"[完成] 已创建模块文档：{', '.join(created)}")
    else:
        print("[跳过] 没有模块文档被重写。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
