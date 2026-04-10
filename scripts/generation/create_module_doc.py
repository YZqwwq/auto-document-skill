#!/usr/bin/env python3
"""
创建第二轮模块文档，并将其登记到 index.json。
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
    for entry in entries[:limit]:
        sample.append(entry.name + ("/" if entry.is_dir() else ""))
    return sample


def collect_child_names(target_path: Path, limit: int = 12) -> tuple[list[str], list[str]]:
    if target_path.is_file():
        return [], []
    directories = []
    files = []
    for entry in sorted(target_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
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


def detect_module_kind(relative_path: str, target_path: Path, child_dirs: list[str], child_files: list[str]) -> str:
    normalized_path = relative_path.replace("\\", "/").strip("/").lower()
    last_name = target_path.name.lower()
    if target_path.is_file():
        if last_name in CONFIG_FILE_HINTS or target_path.suffix.lower() in {".json", ".yaml", ".yml", ".toml"}:
            return "config"
        if target_path.suffix.lower() in MARKDOWN_SUFFIXES:
            return "markdown"
        if target_path.parent.name.lower() in BUILD_DIR_HINTS:
            return "build_output_file"
        return "generic_file"

    directory_names = {item.lower() for item in child_dirs}
    markdown_count = sum(1 for name in child_files if Path(name).suffix.lower() in MARKDOWN_SUFFIXES)
    if last_name in DOC_DIR_HINTS:
        return "docs"
    if last_name in BUILD_DIR_HINTS:
        return "build_output"
    if last_name in RESOURCE_DIR_HINTS:
        return "resources"
    if last_name in TEST_DIR_HINTS:
        return "tests"
    if normalized_path.endswith("src/main") or (last_name == "main" and {"services", "protocols", "database"}.intersection(directory_names)):
        return "main_process_runtime"
    if normalized_path.endswith("src/renderer") or last_name == "renderer":
        return "ui_surface"
    if normalized_path.endswith("src/preload") or last_name == "preload":
        return "preload_bridge"
    if normalized_path.endswith("src/share") or last_name == "share":
        return "shared_contracts"
    if "aiservice" in normalized_path or last_name in {"modelconfig", "prompt-resource"}:
        return "ai_runtime"
    if normalized_path.endswith("/task") or last_name == "task":
        return "task_system"
    if {"main", "preload", "renderer"}.issubset(directory_names):
        return "electron_source"
    if last_name in SOURCE_DIR_HINTS:
        return "source"
    if markdown_count >= max(2, len(child_files) // 2) and child_files:
        return "docs"
    return "generic_directory"


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


def build_context(relative_path: str, target_path: Path, project_root: Path | None = None) -> dict:
    sample_entries = collect_sample_entries(target_path)
    child_dirs, child_files = collect_child_names(target_path)
    readme_path = find_local_readme(target_path)
    readme_summary = extract_markdown_summary(safe_read_text(readme_path) or "") if readme_path else None
    kind = detect_module_kind(relative_path, target_path, child_dirs, child_files)
    return {
        "relative_path": relative_path,
        "target_path": target_path,
        "path_type": "文件" if target_path.is_file() else "目录",
        "sample_entries": sample_entries,
        "child_dirs": child_dirs,
        "child_files": child_files,
        "readme_path": readme_path,
        "readme_summary": readme_summary,
        "project_traits": detect_project_traits(project_root),
        "kind": kind,
        "siblings": sibling_modules(project_root, target_path),
    }


def list_child_directories(path: Path, limit: int = 8) -> list[str]:
    if not path.exists() or not path.is_dir():
        return []
    result = []
    for entry in sorted(path.iterdir(), key=lambda item: item.name.lower()):
        if entry.is_dir():
            result.append(entry.name)
    return result[:limit]


def known_entry_description(entry_name: str, parent_kind: str) -> str:
    normalized = entry_name.rstrip("/")
    lower_name = normalized.lower()
    direct_map = {
        "readme.md": "当前目录的导航入口或使用说明",
        "main": "主进程、核心服务或主要运行编排位置",
        "preload": "主进程向渲染层暴露能力的桥接层",
        "renderer": "界面、视图与前端交互逻辑",
        "share": "跨层共享的数据结构、实体或契约",
        "services": "服务实现与流程编排",
        "database": "数据存取或实体持久化相关实现",
        "components": "可复用界面组件",
        "views": "页面级视图入口",
        "router": "页面路由与导航入口",
        "assets": "静态资源或样式资源",
        "index.ts": "常见的 TypeScript 入口文件",
        "index.js": "常见的 JavaScript 入口文件",
        "index.html": "前端页面入口",
        "package.json": "依赖、脚本和构建入口的声明文件",
    }
    if lower_name in direct_map:
        return direct_map[lower_name]
    if any(token in lower_name for token in ("todo", "roadmap", "milestone", "plan")):
        return "任务清单、路线说明或阶段规划文档"
    suffix = Path(normalized).suffix.lower()
    if suffix in {".ts", ".tsx", ".js", ".jsx", ".vue"}:
        return "当前模块中的实现入口或关键逻辑文件"
    if suffix in MARKDOWN_SUFFIXES:
        return "说明文档或阅读入口"
    if suffix in {".json", ".yaml", ".yml", ".toml"}:
        return "配置或结构化数据文件"
    if suffix in {".png", ".jpg", ".jpeg", ".svg", ".ico"}:
        return "静态资源文件"
    if entry_name.endswith("/"):
        if parent_kind == "docs":
            return "当前知识域下的子主题目录"
        if parent_kind in {"source", "electron_source"}:
            return "当前实现代码下的子目录"
        if parent_kind == "build_output":
            return "构建产物中的子目录"
        return "当前模块下的重要子目录"
    return "当前模块下的重要条目"


def infer_one_liner(context: dict) -> str:
    relative_path = context["relative_path"]
    kind = context["kind"]
    child_dirs = set(context["child_dirs"])
    traits = " / ".join(context["project_traits"])
    trait_prefix = f"这个 {traits} 项目" if traits else "这个项目"

    if kind == "electron_source" and {"main", "preload", "renderer"}.issubset(child_dirs):
        layers = ["主进程", "Preload 桥接", "渲染层界面"]
        if "share" in child_dirs:
            layers.append("跨层共享契约")
        return f"`{relative_path}/` 是{trait_prefix}的源码主目录，承载{'、'.join(layers)}。"
    if kind == "main_process_runtime":
        return f"`{relative_path}/` 是{trait_prefix}的主进程与运行时控制面，负责承载服务编排、协议接入和持久化入口。"
    if kind == "ui_surface":
        return f"`{relative_path}/` 是{trait_prefix}的界面与交互面，负责页面、组件、前端服务和用户可见行为。"
    if kind == "preload_bridge":
        return f"`{relative_path}/` 是{trait_prefix}的桥接层，用于把主进程能力安全地暴露给渲染层。"
    if kind == "shared_contracts":
        return f"`{relative_path}/` 是{trait_prefix}的共享契约层，负责跨前后端复用的数据结构、实体和通用工具。"
    if kind == "ai_runtime":
        return f"`{relative_path}/` 是{trait_prefix}中与 AI 主链直接相关的实现位置，承载 agent runtime、模型配置或 prompt 资源。"
    if kind == "task_system":
        return f"`{relative_path}/` 是{trait_prefix}中负责 task、execution 与队列调度的实现位置。"
    if kind == "source":
        return f"`{relative_path}/` 是{trait_prefix}的主要实现代码目录，负责承载当前运行逻辑和核心模块分层。"
    if kind == "docs":
        return f"`{relative_path}/` 是项目的说明文档与理解入口，用于帮助人和 AI 快速建立当前状态认知。"
    if kind == "build_output":
        return f"`{relative_path}/` 是构建流程生成的输出目录，用于承载从源码编译得到的可运行结果。"
    if kind == "resources":
        return f"`{relative_path}/` 是项目的静态资源目录，主要保存打包或运行时会被加载的非代码文件。"
    if kind == "tests":
        return f"`{relative_path}/` 是项目的测试相关目录，用于验证当前实现的行为和边界。"
    if kind == "config":
        return f"`{relative_path}` 是项目的重要配置入口文件，会影响依赖、脚本或构建方式。"
    if kind == "markdown":
        return f"`{relative_path}` 是项目中的说明文档文件，用于补充理解当前模块或工作流。"
    if kind == "build_output_file":
        return f"`{relative_path}` 是构建流程产出的文件，应作为生成结果理解，而不是主要维护入口。"
    if context["path_type"] == "文件":
        return f"`{relative_path}` 是项目中的一个关键文件，承担当前模块的入口、配置或说明职责。"
    return f"`{relative_path}/` 是项目中的一个工作目录，当前承担一组相关文件和子模块的聚合职责。"


def infer_questions(context: dict) -> list[str]:
    relative_path = context["relative_path"]
    kind = context["kind"]
    if kind == "docs":
        return [
            f"`{relative_path}/` 为什么存在，以及它当前主要服务哪类阅读需求",
            "这里的内容更适合作为导航、专题说明，还是当前系统真相入口",
            "第一次接手时应按什么顺序阅读这里的文档",
        ]
    if kind == "build_output":
        return [
            f"`{relative_path}/` 当前产出了哪些主要结果",
            "它与源码目录是否保持镜像或对应关系",
            "哪些内容属于生成结果，不应作为长期设计真相维护",
        ]
    if kind == "resources":
        return [
            f"`{relative_path}/` 里保存了哪些资源类型",
            "这些资源在运行时、界面或打包流程中如何被引用",
            "资源组织方式是否仍然符合当前项目边界",
        ]
    if kind == "config":
        return [
            f"`{relative_path}` 主要声明了哪些项目级配置",
            "它会影响哪些运行、构建或开发工作流",
            "当工具链变化时，这个文件应如何同步更新",
        ]
    return [
        f"`{relative_path}` 现在主要负责什么",
        "这个路径内部应优先读哪些目录或文件",
        "它与其他模块的边界在哪里",
    ]


def infer_problem_statement(context: dict) -> str:
    kind = context["kind"]
    readme_path = context["readme_path"]
    readme_hint = f"当前路径自带 `{readme_path.name}`，可作为进入该模块的第一层说明。" if readme_path else ""
    if kind == "electron_source":
        return (
            "这个模块承载应用的真实实现代码，是理解当前运行方式、运行时边界和业务入口的首要位置。"
            "对 Electron 项目而言，这里通常也是主进程、渲染层与桥接层职责分离的落点。"
            + (f" {readme_hint}" if readme_hint else "")
        )
    if kind == "source":
        return (
            "这个模块解决的是“把当前系统真实实现落在可维护的代码结构里”的问题。"
            "当需要确认当前项目到底怎么运行时，应优先回到这里核对。"
            + (f" {readme_hint}" if readme_hint else "")
        )
    if kind == "docs":
        return (
            "这个模块解决的是“在不先通读全部代码的情况下建立项目理解”的问题。"
            "它通常用于沉淀当前系统真相、专题说明或阅读入口，帮助人和 AI 先获得上下文，再回到实现核对细节。"
            + (f" {readme_hint}" if readme_hint else "")
        )
    if kind == "build_output":
        return (
            "这个模块解决的是“把源码产物落成可运行输出”的问题。"
            "它让预览、打包或发布流程有明确产物，但不应替代源码目录作为主要维护入口。"
        )
    if kind == "resources":
        return (
            "这个模块用于收纳非代码资源，避免把图片、模板或运行资源散落在实现目录中。"
            "它通常服务于界面展示、运行时加载或应用打包。"
        )
    if kind == "tests":
        return "这个模块用于验证当前实现行为是否符合预期，帮助团队在迭代时及时发现回归或边界问题。"
    if kind == "config":
        return "这个文件主要服务于工具链和工程配置，不属于项目理念、运行时职责或实现边界的主文档范围。除非用户明确要求，否则不建议把它作为项目理解主入口。"
    if kind == "markdown":
        return "这个文件用于补充说明某一模块、流程或设计决策，帮助读者在进入代码之前建立必要的理解上下文。"
    if context["path_type"] == "文件":
        return "这个文件承担某个明确的入口或说明职责，适合在理解相关工作流时作为快速切入点。"
    return (
        "这个模块用于把一组相关文件组织在同一个工作域中。"
        "虽然它未必是整个项目的主入口，但它仍然代表了一块需要独立理解的当前状态。"
        + (f" {readme_hint}" if readme_hint else "")
    )


def infer_structure(context: dict) -> str:
    child_dirs = context["child_dirs"]
    child_files = context["child_files"]
    kind = context["kind"]
    target_path = context["target_path"]
    if kind == "electron_source" and {"main", "preload", "renderer"}.issubset(set(child_dirs)):
        main_subdirs = list_child_directories(target_path / "main")
        services_subdirs = list_child_directories(target_path / "main" / "services")
        bullets = [
            "`main/`：主进程入口、服务实现和运行编排",
            "`preload/`：主进程与渲染层之间的桥接暴露层",
            "`renderer/`：页面、组件、视图与前端交互逻辑",
        ]
        if "share" in child_dirs:
            bullets.append("`share/`：跨层共享的数据结构、缓存或领域实体")
        extra = []
        if {"services", "protocols", "database"}.intersection(set(main_subdirs)):
            extra.append("`main/` 内部又进一步承载服务编排、协议接入和持久化层。")
        if services_subdirs:
            extra.append(f"`main/services/` 当前还承载 {', '.join(sorted(services_subdirs[:5]))} 等服务主题。")
        text = "这个目录当前可以按运行时职责理解为以下几层：\n\n" + format_bullets(bullets)
        if extra:
            text += "\n\n" + "\n".join(extra)
        return text
    if kind == "docs":
        bullets = []
        if context["readme_path"]:
            bullets.append(f"`{context['readme_path'].name}`：当前目录的导航入口")
        bullets.extend([f"`{name}/`：当前知识域下的子主题目录" for name in child_dirs[:5]])
        readme_name = context["readme_path"].name if context["readme_path"] else None
        bullets.extend([f"`{name}`：当前目录下的说明文档" for name in child_files[:4] if name != readme_name])
        if not bullets:
            bullets.extend([f"`{name}`：当前目录下的重要条目" for name in context["sample_entries"][:6]])
        return "这个目录当前以“导航入口 + 子主题目录 + 补充说明文件”的方式组织：\n\n" + format_bullets(bullets[:8])
    if kind == "build_output":
        bullets = [f"`{name}/`：构建产物中的子目录" for name in child_dirs[:6]]
        bullets.extend([f"`{name}`：构建生成的输出文件" for name in child_files[:4]])
        return "当前可见条目表明，这个目录主要保存以下输出结构：\n\n" + format_bullets(bullets[:8])
    if kind == "resources":
        bullets = [f"`{name}/`：资源子目录" for name in child_dirs[:6]]
        bullets.extend([f"`{name}`：静态资源文件" for name in child_files[:4]])
        if bullets:
            return "这个目录当前以资源类型或使用场景进行组织：\n\n" + format_bullets(bullets[:8])
    if context["path_type"] == "文件":
        return "这是一个单文件模块，结构重点不在内部层级，而在它与所在目录及相关工作流的连接方式。"
    bullets = []
    bullets.extend([f"`{name}/`：当前模块下的重要子目录" for name in child_dirs[:6]])
    bullets.extend([f"`{name}`：当前模块下的关键文件" for name in child_files[:4]])
    if bullets:
        return "当前这个模块主要通过以下条目组织内容：\n\n" + format_bullets(bullets[:8])
    return "当前模块规模较小，适合直接从现有条目进入阅读。"


def infer_key_entries(context: dict) -> list[str]:
    entries = context["sample_entries"]
    kind = context["kind"]
    key_entries = []
    for name in entries[:8]:
        key_entries.append(f"`{name}`：{known_entry_description(name, kind)}")
    return key_entries or ["无"]


def infer_question_routes(context: dict) -> list[str]:
    kind = context["kind"]
    child_dirs = set(context["child_dirs"])
    target_path = context["target_path"]
    items = []
    if kind == "docs":
        if child_dirs:
            items.append(f"先按子主题目录继续下钻，例如 `{child_dirs[0]}/`。")
        if context["child_files"]:
            items.append(f"说明文件通常可以从 `{context['child_files'][0]}` 开始。")
        items.append("读完文档后，如果要确认当前真实行为，回到 `src/` 核对代码链路。")
        return items
    if kind in {"electron_source", "source"}:
        if "main" in child_dirs:
            items.append("想理解主流程、服务编排或 runtime 控制面时，先读 `main/`。")
            services_subdirs = set(list_child_directories(target_path / "main" / "services"))
            if "aiservice" in services_subdirs:
                items.append("想理解主 agent、消息队列和 AI runtime 主链时，继续进入 `main/services/aiservice/`。")
            if "task" in services_subdirs:
                items.append("想理解 task、execution、notification 和子 agent 执行链时，进入 `main/services/task/`。")
            for service_name in sorted(services_subdirs - {"aiservice", "task"})[:2]:
                items.append(f"如果问题已经落到 `{service_name}` 这类具体服务主题，可以继续进入 `main/services/{service_name}/`。")
        if "renderer" in child_dirs:
            items.append("想理解界面、交互和页面组织时，先读 `renderer/`。")
        if "preload" in child_dirs:
            items.append("想核对主进程与渲染层桥接边界时，先读 `preload/`。")
        if "share" in child_dirs:
            items.append("想理解跨层共享状态、实体或契约时，进入 `share/`。")
        return items
    if kind == "build_output":
        return [
            "想确认最终构建产物是否与源码结构一致时，查看这里。",
            "如果任务是理解系统设计或修改实现，不要先从这里开始，应回到 `src/`。",
        ]
    if kind == "resources":
        return [
            "想知道有哪些静态资源时，查看这里。",
            "想知道资源是如何被使用的，应回到 `src/` 查找引用点。",
        ]
    if context["sample_entries"]:
        return [f"如果暂时没有更明确的问题入口，可以先从 `{context['sample_entries'][0]}` 开始。"]
    return ["当前模块更适合作为局部阅读入口，而不是问题分流中心。"]


def infer_maintenance_principles(context: dict) -> list[str]:
    kind = context["kind"]
    if kind == "docs":
        return [
            "导航型文档负责告诉读者怎么读，不应把所有专题细节都压进一篇文档里。",
            "解释当前系统怎么工作的文档应维护为当前真相，待办和路线文档不能替代实现结论。",
            "如果文档与代码冲突，应先以代码为运行时真相，再回头修正文档。",
        ]
    if kind in {"electron_source", "source"}:
        return [
            "优先维护模块职责、边界和关键入口，而不是逐文件复述实现细节。",
            "当目录分层或主链入口发生变化时，应整体重写本文件，而不是只补局部描述。",
            "如果解释性文档与代码冲突，应先以代码为准，再同步修正文档入口。",
        ]
    if kind == "build_output":
        return [
            "这里主要作为产物核对面，不应承载长期人工维护的系统说明。",
            "如果输出结构与源码结构长期不一致，应优先修正源码或构建说明，而不是扩写这里。",
        ]
    if kind == "resources":
        return [
            "这里关注资源类型、组织方式和引用边界，不扩写工具链细节。",
            "当资源目录重组或引用路径变化时，应同步更新本文件与相关源码文档。",
        ]
    return [
        "维护时优先说明当前职责和边界，避免把无关历史和工程细节混入正文。",
        "如果这个路径不再是主要阅读入口，应减少描述而不是继续扩写噪音。",
    ]


def infer_boundaries(context: dict) -> list[str]:
    kind = context["kind"]
    siblings = context["siblings"]
    if kind in {"electron_source", "source"}:
        items = ["这里关注当前实现代码和运行逻辑，而不是设计历史或发布产物。"]
        if "docs" in siblings:
            items.append(f"架构说明、阅读导航或专题背景主要应在 `{siblings['docs']}/` 中维护。")
        if "build" in siblings:
            items.append(f"构建后的结果属于 `{siblings['build']}/`，不应把它当成主要维护真相。")
        if "resources" in siblings:
            items.append(f"静态资源应主要在 `{siblings['resources']}/` 中维护，再由实现代码去引用。")
        return items
    if kind == "docs":
        items = ["这里负责解释当前系统结构、阅读顺序或专题说明，而不是承载运行时代码。"]
        if "source" in siblings:
            items.append(f"当文档和实现冲突时，应回到 `{siblings['source']}/` 以代码为准。")
        items.append("未来计划、待办或讨论内容不能替代当前实现真相。")
        return items
    if kind == "build_output":
        items = ["这里属于生成结果层，适合用于核对构建输出，不适合承载主要人工维护。"]
        if "source" in siblings:
            items.append(f"真正的实现边界和长期真相应回到 `{siblings['source']}/` 中理解。")
        if "resources" in siblings:
            items.append(f"如果输出中包含资源复制结果，其原始来源通常在 `{siblings['resources']}/`。")
        return items
    if kind == "resources":
        items = ["这里负责保存资源文件，不应混入过多业务逻辑实现。"]
        if "source" in siblings:
            items.append(f"资源如何被加载、消费或映射，应回到 `{siblings['source']}/` 中核对。")
        if "build" in siblings:
            items.append(f"构建后资源的最终呈现位置可能出现在 `{siblings['build']}/`。")
        return items
    if kind == "config":
        return [
            "这里主要定义工程配置和工具链约束，而不是直接承载项目理念或业务实现。",
            "需要理解系统行为时，应优先回到源码目录、设计文档和运行时入口核对真实实现。",
        ]
    return [
        "这份文档只解释当前路径本身及其直接关联的阅读入口，不尝试代替整个项目总览。",
        "当这里与相邻模块发生职责重划时，应同步更新边界描述。",
    ]


def infer_relationships(context: dict) -> list[str]:
    kind = context["kind"]
    siblings = context["siblings"]
    items = []
    if kind in {"electron_source", "source"}:
        if "docs" in siblings:
            items.append(f"与 `{siblings['docs']}/`：文档提供阅读导航，代码提供运行时真相。")
        if "build" in siblings:
            items.append(f"与 `{siblings['build']}/`：构建产物通常来源于这里的实现。")
        if "resources" in siblings:
            items.append(f"与 `{siblings['resources']}/`：实现代码会消费或打包这些资源。")
    elif kind == "docs":
        if "source" in siblings:
            items.append(f"与 `{siblings['source']}/`：这里解释结构，源码负责落实真实行为。")
        if "build" in siblings:
            items.append(f"与 `{siblings['build']}/`：发布或预览产物可以帮助验证文档描述是否仍然贴合当前实现。")
    elif kind == "build_output":
        if "source" in siblings:
            items.append(f"与 `{siblings['source']}/`：这是最主要的来源关系，输出结果应能映射回源码层级。")
        if "resources" in siblings:
            items.append(f"与 `{siblings['resources']}/`：资源文件可能被复制或打包到这里。")
    elif kind == "resources":
        if "source" in siblings:
            items.append(f"与 `{siblings['source']}/`：代码决定资源如何被引用、显示或分发。")
        if "build" in siblings:
            items.append(f"与 `{siblings['build']}/`：打包或构建后，资源通常会出现在该输出目录中。")
    elif kind == "config":
        if "source" in siblings:
            items.append(f"与 `{siblings['source']}/`：配置决定部分源码的运行、编译或加载方式。")
        if "build" in siblings:
            items.append(f"与 `{siblings['build']}/`：构建配置会直接影响输出形态。")

    if not items and context["readme_path"]:
        items.append(f"与 `{context['readme_path'].name}`：该说明文件通常是理解当前路径的第一入口。")
    if not items:
        items.append("它与相邻模块的关系需要结合当前目录树和调用链一起阅读。")
    return items


def infer_reading_advice(context: dict) -> list[str]:
    kind = context["kind"]
    readme_path = context["readme_path"]
    child_dirs = context["child_dirs"]
    sample_entries = context["sample_entries"]
    items = []
    if readme_path:
        items.append(f"第一次接手时，先读 `{readme_path.name}` 获取当前路径的导航信息。")
    if kind == "electron_source":
        if "main" in child_dirs:
            items.append("要理解主流程或主进程行为时，优先进入 `main/`。")
        if "renderer" in child_dirs:
            items.append("要理解界面、视图或交互行为时，进入 `renderer/`。")
        if "preload" in child_dirs:
            items.append("要核对前后端桥接边界时，检查 `preload/`。")
        return items
    if kind == "docs":
        if child_dirs:
            items.append(f"读完导航入口后，再按主题进入 `{child_dirs[0]}/` 等子目录。")
        items.append("读完说明文档后，应回到真实代码目录核对关键链路。")
        return items
    if kind == "build_output":
        items.append("理解业务逻辑时不要从这里开始，优先回到对应源码目录。")
        items.append("当怀疑构建结果与源码不一致时，再用这里核对最终输出。")
        return items
    if kind == "resources":
        items.append("先确认资源文件的命名和组织方式，再回到源码里查找引用点。")
        return items
    if kind == "config":
        items.append("除非任务明确要求处理工程配置，否则不要把这里当成项目理解主入口。")
        items.append("如果确实需要看配置，先确认它影响哪个源码目录，再回到实现侧继续阅读。")
        return items
    if sample_entries:
        items.append(f"如果没有更明确的入口，可以先从 `{sample_entries[0]}` 开始。")
    items.append("遇到边界不清的地方时，结合上一级目录文档和真实代码一起核对。")
    return items


def infer_update_conditions(context: dict) -> list[str]:
    relative_path = context["relative_path"]
    kind = context["kind"]
    items = [
        f"`{relative_path}` 下的任何实质性变化",
        "会影响该路径与其他模块交互边界的变化",
    ]
    if kind == "docs":
        items.append("阅读入口、目录角色或文档分层方式发生变化")
    if kind == "build_output":
        items.append("构建输出层级与源码层级的映射关系发生变化")
    if kind == "resources":
        items.append("资源组织方式、命名规则或加载路径发生变化")
    if kind == "config":
        items.append("依赖、脚本命令或构建参数发生变化")
    return items


def render_module_doc(relative_path: str, target_path: Path, project_root: Path | None = None) -> str:
    context = build_context(relative_path, target_path, project_root)
    path_type = "文件" if target_path.is_file() else "目录"
    sample_list = format_bullets(infer_key_entries(context))
    question_list = format_bullets(infer_questions(context))
    route_list = format_bullets(infer_question_routes(context))
    boundary_list = format_bullets(infer_boundaries(context))
    relationship_list = format_bullets(infer_relationships(context))
    maintenance_list = format_bullets(infer_maintenance_principles(context))
    reading_list = format_bullets(infer_reading_advice(context))
    update_list = format_bullets(infer_update_conditions(context))
    return f"""# 模块：{relative_path}

## 一句话定位

{infer_one_liner(context)}

## 范围

- 路径：`{relative_path}`
- 类型：`{path_type}`

## 这份文档回答什么问题

{question_list}

## 这个模块解决什么问题

{infer_problem_statement(context)}

## 内部结构速览

{infer_structure(context)}

## 按问题找文档或目录

{route_list}

## 关键文件或条目

{sample_list}

## 运行时边界

{boundary_list}

## 与其他模块的关系

{relationship_list}

## 当前维护原则

{maintenance_list}

## 阅读建议

{reading_list}

## 何时更新本文件

{update_list}
"""


def format_domain_path_entry(context: dict) -> str:
    relative_path = context["relative_path"]
    summary = infer_one_liner(context)
    summary = summary.replace(f"`{relative_path}/` 是", "", 1)
    summary = summary.replace(f"`{relative_path}` 是", "", 1)
    return f"`{relative_path}`：{summary.strip()}"


def path_display_name(path_text: str, is_dir: bool | None = None) -> str:
    clean = path_text.replace("\\", "/").strip("/")
    if not clean:
        return "/"
    name = clean.split("/")[-1]
    if is_dir is True and not name.endswith("/"):
        return name + "/"
    return name


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
        entries.append((label, infer_one_liner(context).replace(f"`{context['relative_path']}/` 是", "", 1).replace(f"`{context['relative_path']}` 是", "", 1).strip()))
    return prefix_text, entries


def compact_path_texts(paths: list[str]) -> tuple[str | None, list[str]]:
    if not paths:
        return None, []
    prefix_parts = shared_prefix_parts(paths)
    prefix_text = "/".join(prefix_parts) if prefix_parts else None
    items = []
    for path in paths:
        clean = path.replace("\\", "/").strip("/")
        parts = clean.split("/") if clean else []
        suffix_parts = parts[len(prefix_parts):] if prefix_parts else parts
        suffix_text = "/".join(suffix_parts) if suffix_parts else (parts[-1] if parts else clean)
        is_dir = Path(clean).suffix == ""
        items.append(path_display_name(suffix_text, is_dir))
    return prefix_text, items


def render_compact_context_section(contexts: list[dict]) -> str:
    prefix_text, entries = compact_context_entries(contexts)
    lines: list[str] = []
    if prefix_text:
        lines.extend([f"路径前缀：`{prefix_text}/`", ""])
    lines.extend([f"- `{label}`：{summary}" for label, summary in entries])
    return "\n".join(lines) if lines else "- 暂无路径"


def render_compact_key_entries(contexts: list[dict], limit_per_context: int = 4) -> str:
    if not contexts:
        return "- 暂无可用入口"
    blocks: list[str] = []
    for context in contexts:
        base = context["relative_path"].replace("\\", "/").strip("/")
        base_label = f"{base}/" if context["target_path"].is_dir() else base
        blocks.append(f"在 `{base_label}` 下优先看：")
        entries = infer_key_entries(context)[:limit_per_context]
        blocks.extend([f"- {entry}" for entry in entries])
        blocks.append("")
    return "\n".join(blocks).strip()


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


def describe_domain_source_label(source_rel: str, domain_id: str) -> str:
    del domain_id
    path = Path(source_rel)
    label = describe_domain_file_role(path)
    if label == "当前专题中的关键文件或入口":
        return path_display_name(source_rel, path.suffix == "")
    return label


def source_ref(source_rel: str, current_doc_rel: str, domain_id: str) -> str:
    label = describe_domain_source_label(source_rel, domain_id)
    target = relative_source_link(current_doc_rel, source_rel)
    return f"[`{label}`](./{target})"


def labeled_source_ref(current_doc_rel: str, source_rel: str, label: str) -> str:
    target = relative_source_link(current_doc_rel, source_rel)
    return f"[`{label}`](./{target})"


def existing_source_items(
    project_root: Path,
    current_doc_rel: str,
    items: list[tuple[str, str, str | None]],
) -> list[str]:
    rendered: list[str] = []
    for source_rel, label, description in items:
        if not (project_root / source_rel).exists():
            continue
        link = labeled_source_ref(current_doc_rel, source_rel, label)
        rendered.append(f"{link}：{description}" if description else link)
    return rendered


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


def render_domain_readme(domain: dict, all_domains: list[dict], project_root: Path) -> str:
    title = domain["title"]
    child_domains = [item for item in all_domains if item.get("parent_id") == domain["id"]]
    contexts = [build_context(path, (project_root / path).resolve(), project_root) for path in domain.get("paths", []) if (project_root / path).exists()]
    coverage_list = render_compact_context_section(contexts)
    hierarchy_map = render_local_domain_hierarchy(domain, all_domains)

    implementation_views = []
    for context in contexts:
        implementation_views.append(f"`{path_display_name(context['relative_path'], context['target_path'].is_dir())}`：{infer_problem_statement(context)}")
    split_views = [f"`{child['title']}`：{child['summary']}" for child in child_domains]
    reading_items = []
    if child_domains:
        for child in child_domains:
            reading_items.append(f"想看“{child['summary']}”相关内容时，进入 {domain_ref_for_doc(child, domain.get('doc_path', ''))}。")
    else:
        reading_items.append("这一层当前没有继续拆出的下级专题，读完这里后直接按相关实现路径回到代码。")

    return f"""# 功能域：{title}

## 定位

{domain['summary']}

## 当前功能层级

{hierarchy_map}

## 这一层主要承载什么

{format_bullets(implementation_views)}

## 这一层内部怎么分

{format_bullets(split_views if split_views else implementation_views)}

## 相关实现路径

{coverage_list}

## 阅读建议

{format_bullets(reading_items)}
"""


def summarize_statement(text: str, max_chars: int = 88) -> str:
    clean = text.replace("`", "").replace("\n", " ").strip()
    clean = clean.removeprefix("这个模块").removeprefix("这个目录").removeprefix("这个文件").strip()
    clean = clean.rstrip("。.!！?？")
    if len(clean) > max_chars:
        return clean[: max_chars - 3].rstrip() + "..."
    return clean


def join_code_refs(items: list[str]) -> str:
    cleaned = [item for item in items if item]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} 和 {cleaned[1]}"
    return f"{'、'.join(cleaned[:-1])} 以及 {cleaned[-1]}"


def infer_domain_chain(domain: dict, contexts: list[dict], parent: dict | None = None) -> list[str]:
    if not contexts:
        items = [f"`{domain['title']}` 当前还缺少足够的实现证据，建议先回到相关路径补充分析。"]
        if parent:
            items.append(f"它位于 `{parent['title']}` 之下，后续应围绕更具体的职责边界继续细化。")
        return items

    context_labels = [
        f"`{path_display_name(context['relative_path'], context['target_path'].is_dir())}`"
        for context in contexts[:3]
    ]
    problem_points = [summarize_statement(infer_problem_statement(context)) for context in contexts[:2]]
    items = [f"`{domain['title']}` 当前主要由 {join_code_refs(context_labels)} 这些实现面共同支撑。"]
    if problem_points:
        items.append(f"这一专题主要解决 {join_code_refs(problem_points)} 这一类问题。")
    if len(contexts) > 1:
        items.append("阅读时应把这些路径当成同一条专题链上的不同协作面，而不是孤立目录分别理解。")
    elif parent:
        items.append(f"它是 `{parent['title']}` 之下继续收敛出来的具体实现面。")
    return items


def score_domain_file(path: Path, domain_id: str) -> int:
    del domain_id
    name = path.name.lower()
    suffix = path.suffix.lower()
    score = 1

    if any(token in name for token in ("readme", "index", "main", "entry", "app")):
        score += 7
    if any(token in name for token in ("service", "provider", "manager", "controller", "handler")):
        score += 6
    if any(token in name for token in ("router", "client", "bridge", "adapter", "gateway", "ipc", "preload")):
        score += 5
    if any(token in name for token in ("model", "schema", "entity", "record", "type", "contract", "definition")):
        score += 5
    if any(token in name for token in ("store", "state", "cache", "repository", "repo")):
        score += 4
    if any(token in name for token in ("queue", "dispatch", "scheduler", "worker", "job", "runtime")):
        score += 4
    if any(token in name for token in ("view", "page", "component", "form", "dialog")) or suffix == ".vue":
        score += 4
    if any(token in name for token in ("prompt", "template", "config", "resource")):
        score += 3
    if any(token in name for token in ("test", "spec", "mock", "fixture")):
        score -= 6
    if suffix in {".ts", ".tsx", ".js", ".jsx", ".vue", ".py", ".go", ".java", ".rs"}:
        score += 2
    if suffix in {".md", ".mdx"} and "readme" in name:
        score += 3
    if len(path.parts) <= 6:
        score += 1
    return score


def infer_domain_call_summary(domain: dict, representative_files: list[str], contexts: list[dict], current_doc_rel: str | None = None) -> list[str]:
    del domain
    if representative_files:
        refs = [
            source_ref(path, current_doc_rel, "") if current_doc_rel else f"`{Path(path).name}`"
            for path in representative_files[:3]
        ]
        roles = [describe_domain_file_role(Path(path)) for path in representative_files[:3]]
        items = [f"{refs[0]} 往往是这条专题链最合适的切入点，通常承担{roles[0]}。"]
        if len(refs) >= 2:
            items.append(f"{refs[1]} 补充了与入口相邻的实现面，适合在读完第一处锚点后继续核对。")
        if len(refs) >= 3:
            items.append(f"{refs[2]} 往往能帮助确认这条链下游的协作方式或约束定义。")
        elif len(contexts) > 1:
            context_labels = [
                f"`{path_display_name(context['relative_path'], context['target_path'].is_dir())}`"
                for context in contexts[:3]
            ]
            items.append(f"这块能力分散在 {join_code_refs(context_labels)} 等路径中，阅读时应在入口和协作面之间来回核对。")
        else:
            items.append("如果只保留一处实现锚点，后续应沿着它所在目录继续追到相邻服务、结构定义或桥接调用。")
        return items

    if contexts:
        context_labels = [f"`{context['relative_path']}`" for context in contexts[:2]]
        return [
            f"{join_code_refs(context_labels)} 是当前专题最直接的实现入口。",
            "当前还没有足够稳定的代表性文件，建议从这些覆盖路径继续顺着入口、定义和下游协作关系往下读。",
        ]
    return ["当前专题域暂未识别出稳定的调用关系，建议先补充覆盖路径或代表文件。"]


def describe_domain_file_role(path: Path) -> str:
    name = path.name
    lower_name = name.lower()
    suffix = path.suffix.lower()

    if path.suffix == "":
        if any(token in lower_name for token in ("service", "services")):
            return "服务实现目录"
        if any(token in lower_name for token in ("view", "views", "page", "pages", "component", "components")):
            return "界面或交互目录"
        if any(token in lower_name for token in ("model", "schema", "entity", "contract", "type")):
            return "结构定义目录"
        return "当前专题下的重要目录"

    if "readme" in lower_name:
        return "当前目录的阅读入口或说明文档"
    if any(token in lower_name for token in ("index", "main", "entry", "bootstrap")):
        return "入口文件或主链切入点"
    if any(token in lower_name for token in ("service", "provider", "manager", "controller", "handler")):
        return "服务实现或能力暴露入口"
    if any(token in lower_name for token in ("router", "route", "client", "bridge", "adapter", "gateway", "ipc", "preload")):
        return "跨层调用、桥接或请求入口"
    if any(token in lower_name for token in ("model", "schema", "entity", "record", "type", "contract", "definition")):
        return "数据结构、实体或约束定义"
    if any(token in lower_name for token in ("store", "state", "cache", "repository", "repo")):
        return "状态组织、缓存或数据访问入口"
    if any(token in lower_name for token in ("queue", "dispatch", "scheduler", "worker", "job", "runtime")):
        return "调度、运行控制或异步处理入口"
    if any(token in lower_name for token in ("view", "page", "component", "form", "dialog")) or suffix == ".vue":
        return "界面、页面或交互实现入口"
    if any(token in lower_name for token in ("prompt", "template", "resource")):
        return "模板、提示词或资源素材"
    if any(token in lower_name for token in ("config", "setting", "settings")) or suffix in {".json", ".yaml", ".yml", ".toml"}:
        return "配置或结构化数据文件"
    if suffix in {".md", ".mdx"}:
        return "说明文档或专题补充材料"
    if any(token in lower_name for token in ("test", "spec", "mock", "fixture")):
        return "测试、示例或辅助验证文件"
    return "当前专题中的关键文件或入口"


def collect_representative_domain_files(domain: dict, project_root: Path, limit: int = 8) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen = set()
    for rel in domain.get("paths", []):
        target = (project_root / rel).resolve()
        if target.is_file():
            score = score_domain_file(target, domain["id"])
            candidates.append((score, rel.replace("\\", "/")))
            continue
        if not target.exists():
            continue
        for file_path in target.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in {".ts", ".tsx", ".js", ".jsx", ".md"}:
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


def analyze_domain(domain: dict, all_domains: list[dict], project_root: Path) -> dict:
    title = domain["title"]
    current_doc_rel = domain.get("doc_path", "")
    parent = next((item for item in all_domains if item["id"] == domain.get("parent_id")), None)
    child_domains = [item for item in all_domains if item.get("parent_id") == domain["id"]]
    contexts = [build_context(path, (project_root / path).resolve(), project_root) for path in domain.get("paths", []) if (project_root / path).exists()]
    hierarchy_map = render_local_domain_hierarchy(domain, all_domains)
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
                "summary": infer_one_liner(context),
                "problem": infer_problem_statement(context),
            }
            for context in contexts
        ],
    }
    if child_domains:
        analysis["doc_kind"] = "root"
        analysis["implementation_views"] = [f"`{path_display_name(context['relative_path'], context['target_path'].is_dir())}`：{infer_problem_statement(context)}" for context in contexts]
        analysis["split_views"] = [f"`{child['title']}`：{child['summary']}" for child in child_domains]
        analysis["coverage_list"] = render_compact_context_section(contexts)
        analysis["reading_items"] = (
            [f"想看“{child['summary']}”相关内容时，进入 {domain_ref_for_doc(child, current_doc_rel)}。" for child in child_domains]
            if child_domains
            else ["这一层当前没有继续拆出的下级专题，读完这里后直接按相关实现路径回到代码。"]
        )
        return analysis

    representative_files = collect_representative_domain_files(domain, project_root)
    key_entries = []
    for context in contexts:
        for entry in infer_key_entries(context)[:3]:
            key_entries.append(f"{source_ref(context['relative_path'], current_doc_rel, domain['id'])} -> {entry}")
    analysis["doc_kind"] = "leaf"
    analysis["coverage_list"] = format_bullets(
        [
            f"{source_ref(context['relative_path'], current_doc_rel, domain['id'])}：{format_domain_path_entry(context).split('：', 1)[1]}"
            for context in contexts
        ]
    )
    analysis["chain_list"] = infer_domain_chain(domain, contexts, parent)
    analysis["call_summary_list"] = infer_domain_call_summary(domain, representative_files, contexts, current_doc_rel)
    analysis["representative_files"] = [
        {
            "path": path,
            "entry": f"{source_ref(path, current_doc_rel, domain['id'])}：{describe_domain_file_role((project_root / path).resolve())}",
        }
        for path in representative_files
    ]
    analysis["key_entries"] = key_entries[:8]
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

## 阅读建议

{format_bullets(analysis.get('reading_items', []))}
"""

    return f"""# 功能域：{title}

## 一句话定位

{analysis['summary']}

## 当前功能层级

{analysis['hierarchy_map']}

## 核心作用

{format_bullets(analysis.get('chain_list', []))}

## 为什么这样实现

{format_bullets(analysis.get('call_summary_list', []))}

## 相关实现路径

{analysis.get('coverage_list', '- 暂无路径')}

## 关键文件

{format_bullets([item['entry'] for item in analysis.get('representative_files', [])]) if analysis.get('representative_files') else '- 暂无代表性文件'}

## 关键入口

{format_bullets(analysis.get('key_entries', [])) if analysis.get('key_entries') else "- 暂无可用入口"}
"""


def render_domain_doc(domain: dict, all_domains: list[dict], project_root: Path) -> str:
    return render_domain_doc_from_analysis(analyze_domain(domain, all_domains, project_root))


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
