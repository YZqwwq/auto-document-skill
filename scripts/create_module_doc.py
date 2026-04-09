#!/usr/bin/env python3
"""
创建第二轮模块文档，并将其登记到 index.json。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from architecture_domains import domains_by_parent


DEFAULT_DOC_DIR = "project-docs"
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
    if last_name in {"worldbuilding", "avatar"}:
        return "worldbuilding"
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
        "missiontodo.md": "项目级待办或路线入口",
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
    if kind == "worldbuilding":
        return f"`{relative_path}/` 是{trait_prefix}中承载世界观、角色或领域编辑能力的实现位置。"
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
    if kind == "docs" and target_path.name.lower() == "developmentlog":
        bullets = [
            "`README.md`：这个目录本身的导航入口，定义推荐阅读顺序和文档角色分层",
            "`AIagent-design/`：当前 AI agent 主链、消息队列、task、persona、tool 等核心设计知识域",
            "`AIlogSystem/`：日志系统与日志消费链专题",
            "`worldDesign/`：世界观、角色编辑和领域结构设计",
            "`font-design/`：文件存放、资源目录等支持性设计",
            "`missiontodo.md`：未来路线与 backlog，不能替代当前实现真相",
        ]
        return "这个目录不是按时间排列的日志堆，而是按“当前系统真相 / 专题设计 / 后续路线”组织的知识库：\n\n" + format_bullets(bullets)
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
        if {"aiservice", "task", "worldbuilding"}.intersection(set(services_subdirs)):
            extra.append("当前主进程服务面至少包含 AI runtime、任务系统和 worldbuilding 相关服务。")
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
        if "AIagent-design" in child_dirs:
            items.append("想理解 AI agent 主链、消息队列和 task 设计时，先进入 `AIagent-design/`。")
        if "AIlogSystem" in child_dirs:
            items.append("想理解日志系统或前后端日志消费链时，进入 `AIlogSystem/`。")
        if "worldDesign" in child_dirs:
            items.append("想理解世界观、角色编辑和领域结构设计时，进入 `worldDesign/`。")
        if "font-design" in child_dirs:
            items.append("想理解资源目录或文件存放方式时，进入 `font-design/`。")
        if "missiontodo.md" in context["child_files"]:
            items.append("想知道未来路线或 backlog 时，再读 `missiontodo.md`，但不要把它当成当前实现真相。")
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
            if "worldbuilding" in services_subdirs:
                items.append("想理解世界观编辑与领域服务时，进入 `main/services/worldbuilding/`。")
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


def render_domain_readme(domain: dict, all_domains: list[dict], project_root: Path) -> str:
    title = domain["title"]
    parent = next((item for item in all_domains if item["id"] == domain.get("parent_id")), None)
    child_domains = [item for item in all_domains if item.get("parent_id") == domain["id"]]
    contexts = [build_context(path, (project_root / path).resolve(), project_root) for path in domain.get("paths", []) if (project_root / path).exists()]
    coverage_list = render_compact_context_section(contexts)
    split_list = format_bullets(
        [
            (
                lambda prefix_text, items: f"`{item['title']}`："
                + (f"路径前缀 `{prefix_text}/`，" if prefix_text else "")
                + f"包含 `{'`、`'.join(items)}`，继续解释这一层里的具体实现面。"
            )(*compact_path_texts(item["paths"]))
            for item in child_domains
        ]
    ) if child_domains else "- 当前没有继续登记的第二层专题域。"

    implementation_views = []
    for context in contexts:
        implementation_views.append(f"`{path_display_name(context['relative_path'], context['target_path'].is_dir())}`：{infer_problem_statement(context)}")

    relationship_items = []
    sibling_titles = [item["title"] for item in all_domains if item.get("parent_id") == domain.get("parent_id") and item["id"] != domain["id"]]
    if sibling_titles:
        relationship_items.append(f"它与同层功能域 `{', '.join(sibling_titles)}` 一起构成当前层级的阅读分流入口。")
    if child_domains:
        relationship_items.append("它向下把阅读问题继续分流到下一层专题域。")
    if not relationship_items:
        relationship_items.append("它与其他功能域的关系需要结合整体目录和调用链一起理解。")

    boundary_items = [
        "这一层负责解释“整块系统怎么分层”，不直接替代具体实现说明。",
        "当下层专题已经足以承载某条链路时，这一层只保留导航和边界，不继续复述细节。",
        "如果这里的结构说明与代码冲突，应先以代码为准，再回头重写这份根文档。",
    ]

    reading_items = [
        f"第一次接手时，先通过这份 README 建立 `{title}` 的总边界，再决定进入哪一个第二层专题域。",
    ]
    if child_domains:
        reading_items.append("当问题已经明确落到某条专题链路时，优先进入对应的第二层文档，而不是在这一层继续堆细节。")
    else:
        reading_items.append("如果当前还没有第二层专题域，读完这里后直接按覆盖路径回到代码核对实现。")

    update_items = [
        f"`{title}` 的整体职责边界发生变化",
        "这一层新增、删除或重命名了下一级专题域",
        "当前导航已经不足以指导第一次接手的人或 AI 继续下钻",
    ]

    return f"""# 功能域：{title}

## 定位

{domain['summary']}

## 范围

- 功能域 ID：`{domain['id']}`
- 层级：`第 {domain['level']} 层`
- 上级功能域：`{parent['title'] if parent else '无'}`
- 覆盖路径数量：`{len(domain.get('paths', []))}`

## 文档核心内容

{format_bullets(domain.get("question_hints", []))}

## 覆盖路径

{coverage_list}

## 下一级分层

{split_list}

## 当前职责

{format_bullets(implementation_views)}

## 关键入口

{render_compact_key_entries(contexts)}

## 与其他功能域的关系

{format_bullets(relationship_items)}

## 运行时边界

{format_bullets(boundary_items)}

## 阅读建议

{format_bullets(reading_items)}

## 何时更新本文件

{format_bullets(update_items)}
"""


def infer_domain_chain(domain: dict, contexts: list[dict], parent: dict | None = None) -> list[str]:
    context_paths = [context["relative_path"] for context in contexts]
    if domain["id"] == "ai-runtime":
        return [
            "模型配置、prompt 资源和 agent runtime 一起构成 AI 主链的准备面与执行面。",
            "运行时能力主要落在 `src/main/services/aiservice/`，模型选型与配置由 `modelconfig` 补充。",
            "prompt 资源目录为主链提供系统提示词和角色化资源，最终与 runtime 共同决定 AI 行为。",
        ]
    if domain["id"] == "task-orchestration":
        return [
            "任务系统把 execution、queue 和 continuation 组织成独立的编排链。",
            "主入口位于 `src/main/services/task/`，而子 Agent 的补充实现继续下沉到 `child-agent-system/`。",
            "理解这块时，应把“入队、调度、回流”当成一条链，而不是分散看单个文件。",
        ]
    if domain["id"] == "worldbuilding-domain":
        return [
            "这一层把世界观、角色编辑和领域服务聚合到同一个专题里。",
            "世界观服务与角色能力并不是两份孤立代码，而是共同服务于领域编辑工作流。",
            "修改这块时要同时核对领域数据结构、编辑入口和与 AI 主链的协作边界。",
        ]
    if domain["id"] == "runtime-orchestration":
        return [
            "main agent 的 runtime 入口、lifecycle 控制、notification 处理和 orchestration 共同组成主链控制面。",
            "这里决定一轮 AI 交互如何进入、如何推进、以及如何接收任务通知回流。",
            "修改主链执行顺序时，应优先核对 runtime/ 下的服务与子目录协作。",
        ]
    if domain["id"] == "model-and-tools":
        return [
            "模型配置、toolkit 装配和工具契约一起决定 AI 主链可用的能力面。",
            "这里连接模型参数、工具调用接口和不同工具包的装配方式。",
            "修改工具使用规则或模型切换逻辑时，应先核对这一层。",
        ]
    if domain["id"] == "prompt-and-context-assets":
        return [
            "系统 prompt、角色化提示资源和 prompt 服务一起为 AI 主链提供输入上下文。",
            "这里不直接跑 runtime，但会显著影响 AI 的表达、策略和角色感。",
            "当提示词结构变化时，应同时检查资源目录与 prompt 服务之间的对应关系。",
        ]
    if domain["id"] == "task-core-services":
        return [
            "task、execution 和 trace 服务共同构成任务系统的主服务链。",
            "这里定义任务对象如何创建、执行、检查和记录。",
            "修改任务核心状态流转时，应优先核对这些主服务文件。",
        ]
    if domain["id"] == "queue-and-dispatch":
        return [
            "队列与分发层负责把任务放入执行队列，并把工作下发给子 Agent 或执行器。",
            "这一层连接 queue、dispatcher、registry 和 child-agent-system。",
            "如果任务积压、派发异常或子 Agent 下发变化，应优先检查这里。",
        ]
    if domain["id"] == "continuation-and-notification":
        return [
            "continuation、notification 和 recovery 共同负责把中断任务重新接回主链。",
            "这一层决定补参、等待、回流和恢复的协作方式。",
            "修改通知桥、恢复链或补参逻辑时，应优先核对这里。",
        ]
    if domain["id"] == "domain-services":
        return [
            "worldbuilding 和 avatar 服务入口共同构成领域编辑的后端入口面。",
            "这里负责对外暴露领域编辑能力，而不是定义全部共享结构。",
            "修改编辑入口或服务边界时，应优先核对这里。",
        ]
    if domain["id"] == "shared-world-definitions":
        return [
            "worldbuilding 的缓存定义、世界结构定义和数据库实体一起构成共享结构面。",
            "领域服务运行时会依赖这组共享定义来读写和表达世界结构。",
            "如果世界记录、实体关系或共享缓存变化，应优先检查这里。",
        ]
    if domain["id"] == "interaction-surface":
        return [
            "界面渲染层和 preload 桥接层一起构成用户能直接感知到的交互面。",
            "前端页面与主进程能力之间的边界，不在组件本身，而在 preload 暴露和前端服务调用链。",
        ]
    if domain["id"] == "shared-contracts":
        return [
            "这一层集中承载会被多个运行时面共同依赖的实体、缓存和工具。",
            "当主进程与渲染层需要共享结构时，应优先在这里统一定义，再由两侧去消费。",
        ]
    items = [
        f"`{domain['title']}` 当前覆盖 {', '.join(context_paths)} 这些实现面。",
        "理解这块时，应先把相关路径当成同一条阅读问题下的协作面，而不是孤立目录。",
    ]
    if parent:
        items.append(f"它是 `{parent['title']}` 之下的具体专题实现面。")
    return items


def score_domain_file(path: Path, domain_id: str) -> int:
    name = path.name.lower()
    parts = [part.lower() for part in path.parts]
    score = 0
    if name.endswith("service.ts") or name.endswith("service.js"):
        score += 6
    if "runtime" in name:
        score += 5
    if "entry" in name or "main" in name:
        score += 4
    if "queue" in name or "notification" in name:
        score += 4
    if "ipc" in name:
        score += 3
    if "prompt" in name or "tool" in name:
        score += 3
    if "record" in name or "entity" in name:
        score += 2

    if domain_id == "ai-runtime":
        if any(token in name for token in ("aiservice", "runtime", "prompt", "modelconfig", "toolkit", "tool")):
            score += 6
        if "agentrsystem" in parts or "runtime" in parts:
            score += 4
    elif domain_id == "task-orchestration":
        if any(token in name for token in ("task", "queue", "dispatcher", "continuation", "notification", "execution")):
            score += 6
    elif domain_id == "worldbuilding-domain":
        if any(token in name for token in ("world", "entity", "avatar", "editor")):
            score += 6
    return score


def select_domain_file(paths: list[str], include_tokens: tuple[str, ...], exclude_tokens: tuple[str, ...] = ()) -> str | None:
    for path in paths:
        lower_path = path.lower()
        if any(token not in lower_path for token in include_tokens):
            continue
        if any(token in lower_path for token in exclude_tokens):
            continue
        return path
    return None


def infer_domain_flow_sequence(domain: dict, representative_files: list[str], contexts: list[dict]) -> list[str]:
    if domain["id"] == "runtime-orchestration":
        entry = select_domain_file(representative_files, ("mainagententryservice",))
        run_control = select_domain_file(representative_files, ("mainagentruncontrolservice",))
        turn_service = select_domain_file(representative_files, ("mainagentturnservice",))
        lifecycle = select_domain_file(representative_files, ("lifecycle", "mainagentlifecyclecontrolservice"))
        orchestration = select_domain_file(representative_files, ("orchestration", "mainagenteventorchestration"))
        notification = select_domain_file(representative_files, ("notification", "tasknotificationconsumerservice"))
        queue = select_domain_file(representative_files, ("queue", "mainagentdispatchqueueservice"))
        return [
            f"`{entry or 'mainAgentEntryService.ts'}` 作为主 Agent 对话链的进入点，把一次请求交给 `{run_control or 'mainAgentRunControlService.ts'}` 与 `{turn_service or 'mainAgentTurnService.ts'}` 组织本轮执行。",
            f"`{lifecycle or 'mainAgentLifecycleControlService.ts'}` 负责判断当前 turn 所处的生命周期阶段，再由 `{orchestration or 'mainAgentEventOrchestration.ts'}` 串起事件编排与 effect 应用。",
            f"当任务结果或异步事件回流时，`{notification or 'taskNotificationConsumerService.ts'}` 与 `{queue or 'mainAgentDispatchQueueService.ts'}` 协作，把通知消费和派发重新接回主链。",
        ]
    if domain["id"] == "model-and-tools":
        model_config = select_domain_file(representative_files, ("modelconfigservice",))
        main_toolkit = select_domain_file(representative_files, ("mainagenttoolkit",))
        main_registry = select_domain_file(representative_files, ("mainagenttoolregistry",))
        child_registry = select_domain_file(representative_files, ("childagenttoolkitregistry",))
        concrete_tool = select_domain_file(representative_files, ("tools",), ("registry", "toolkit"))
        return [
            f"`{model_config or 'modelConfigService.ts'}` 先提供主 Agent 和子 Agent 可用的模型配置、超时和运行边界，作为工具链装配前的基础约束。",
            f"`{main_toolkit or 'mainAgentToolkit.ts'}` 与 `{main_registry or 'mainAgentToolRegistry.ts'}` 负责把可用工具组织成主 Agent 能消费的 toolkit；子 Agent 侧则由 `{child_registry or 'childAgentToolkitRegistry.ts'}` 维持自己的能力集合。",
            f"真正的工具能力继续下沉到 `{concrete_tool or 'tools/'}` 等实现目录中，最终由 toolkit 和 registry 决定哪些工具会暴露给运行时主链。",
        ]
    if domain["id"] == "prompt-and-context-assets":
        prompt_service = select_domain_file(representative_files, ("agentpromptservice",))
        system_prompt = select_domain_file(representative_files, ("systemprompt",))
        persona_state = select_domain_file(representative_files, ("persona_state",))
        utils_asset = select_domain_file(representative_files, ("utils", ".json"))
        return [
            f"`{system_prompt or 'systemprompt.md'}` 和 `{persona_state or 'persona_state.json'}` 这类资源文件先定义系统提示词、角色状态和上下文素材，是 prompt 组装前的原始输入。",
            f"`{prompt_service or 'agentPromptService.ts'}` 负责把这些静态资源转成运行时真正会消费的 prompt 结构，并把提示词组织逻辑接到 AI 主链上。",
            f"`{utils_asset or 'utils.json'}` 这类结构化资源补充 prompt 需要的辅助上下文；当表达风格、角色设定或上下文模板变化时，应先从资源文件再回到 prompt 服务核对。",
        ]
    if domain["id"] == "task-core-services":
        task_service = select_domain_file(representative_files, ("taskservice",))
        execution_service = select_domain_file(representative_files, ("taskexecutionservice",))
        trace_service = select_domain_file(representative_files, ("tasktraceservice",))
        inspection = select_domain_file(representative_files, ("inspectionmapper",))
        return [
            f"`{task_service or 'taskService.ts'}` 先负责 task 主对象的创建、读取和基础状态操作，是任务系统最上游的服务入口。",
            f"`{execution_service or 'taskExecutionService.ts'}` 在 task 之下继续管理 execution 生命周期，把一次任务拆成可调度、可恢复的执行单元。",
            f"`{trace_service or 'taskTraceService.ts'}` 与 `{inspection or 'taskExecutionInspectionMapper.ts'}` 负责补充 trace、检查结果和诊断映射，让任务主链在运行后仍可被回看和排查。",
        ]
    if domain["id"] == "queue-and-dispatch":
        dispatcher = select_domain_file(representative_files, ("subagentdispatcherservice",))
        registry = select_domain_file(representative_files, ("subagentregistry",))
        queue = select_domain_file(representative_files, ("subagentexecutionqueueservice",))
        child_runtime = select_domain_file(representative_files, ("child-agent-system",)) or select_domain_file(representative_files, ("charactereditorruntimesupport",))
        return [
            f"`{dispatcher or 'subAgentDispatcherService.ts'}` 接收待执行的子任务后，会先结合 `{registry or 'subAgentRegistry.ts'}` 判断应该下发给哪类子 Agent 或运行时支撑实现。",
            f"`{queue or 'subAgentExecutionQueueService.ts'}` 负责把 execution 放进排队链，控制出队和派发时机，避免任务直接跳过队列管理。",
            f"下发后的实际能力由 `{child_runtime or 'child-agent-system/'}` 承接；因此理解这条链时，应把 dispatcher、queue 和 child-agent runtime 当成同一条派发流程来看。",
        ]
    if domain["id"] == "continuation-and-notification":
        notification = select_domain_file(representative_files, ("tasknotificationservice",))
        continuation = select_domain_file(representative_files, ("taskcontinuationservice",))
        recovery = select_domain_file(representative_files, ("taskrecoveryservice",))
        consumer = select_domain_file(representative_files, ("notification", "tasknotificationconsumerservice"))
        return [
            f"`{notification or 'taskNotificationService.ts'}` 先把任务侧产生的通知整理成可回流的数据，再交给后续桥接链处理。",
            f"`{continuation or 'taskContinuationService.ts'}` 与 `{recovery or 'taskRecoveryService.ts'}` 决定等待中的任务如何补参、续跑或恢复，是中断后重新接回主链的核心控制点。",
            f"通知最终会被 `{consumer or 'taskNotificationConsumerService.ts'}` 这类 runtime 侧消费者重新接入 main agent 主链，因此这份文档描述的是任务系统和 AI runtime 之间的回流接口面。",
        ]
    if domain["id"] == "domain-services":
        world_service = select_domain_file(representative_files, ("worldbuildingservice",))
        avatar_service = select_domain_file(representative_files, ("avatarprofileservice",))
        return [
            f"`{world_service or 'worldbuildingService.ts'}` 是世界观编辑能力的后端主入口，负责承接对世界结构和领域内容的操作请求。",
            f"`{avatar_service or 'avatarProfileService.ts'}` 与 worldbuilding 服务并行存在，负责角色画像或角色资料编辑这一侧的入口能力。",
            "两者本身不负责定义共享结构，而是把编辑请求落到领域服务入口；真正的共享 world/entity 结构会继续下沉到兄弟文档 `共享世界结构定义` 中。",
        ]
    if domain["id"] == "shared-world-definitions":
        cache_defs = select_domain_file(representative_files, ("definitions.ts",))
        cache_state = select_domain_file(representative_files, ("worldbuilding.ts",))
        world_record = select_domain_file(representative_files, ("worldrecord",))
        entity_record = select_domain_file(representative_files, ("worldentityrecord",))
        relation_record = select_domain_file(representative_files, ("worldentityrelationrecord",))
        return [
            f"`{cache_defs or 'definitions.ts'}` 与 `{cache_state or 'worldbuilding.ts'}` 先定义 worldbuilding 在共享缓存层里的结构和读取方式，给前后端共享状态提供统一形状。",
            f"`{world_record or 'WorldRecord.ts'}`、`{entity_record or 'WorldEntityRecord.ts'}`、`{relation_record or 'WorldEntityRelationRecord.ts'}` 这一组数据库实体继续把共享结构落到持久化层。",
            "上层的 worldbuilding 服务会同时依赖缓存定义和数据库实体，因此当世界结构变化时，应先看共享定义，再回到领域服务入口确认调用方式。",
        ]

    context_paths = [context["relative_path"] for context in contexts]
    if not context_paths:
        return ["当前专题域暂未识别出稳定的实现顺序，建议直接从覆盖路径中的入口文件开始核对。"]
    return [
        f"当前专题域主要围绕 `{context_paths[0]}` 进入实现面。",
        "建议先确认上游入口，再沿着主服务和下游协作的顺序继续阅读。",
    ]


def infer_domain_call_summary(domain: dict, representative_files: list[str], contexts: list[dict]) -> list[str]:
    if domain["id"] == "runtime-orchestration":
        entry = select_domain_file(representative_files, ("mainagententryservice",))
        dispatch = select_domain_file(representative_files, ("queue", "mainagentdispatchqueueservice"))
        notification_bridge = "taskNotificationDispatchBridge.ts"
        turn_service = select_domain_file(representative_files, ("mainagentturnservice",))
        lifecycle = select_domain_file(representative_files, ("lifecycle", "mainagentlifecyclecontrolservice"))
        chat_runtime = select_domain_file(representative_files, ("mainagentchatruntimeservice",)) or "mainAgentChatRuntimeService.ts"
        effect_applier = "mainAgentEffectApplierService.ts"
        notification_consumer = "taskNotificationConsumerService.ts"
        return [
            f"`{entry or 'mainAgentEntryService.ts'}` 会先配置 `{dispatch or 'mainAgentDispatchQueueService.ts'}` 和 `{notification_bridge}`，让用户消息与任务通知都能进入同一条主 Agent 派发入口。",
            f"事件进入主链后，会由 `orchestrateMainAgentEvent` 把 turn 创建、生命周期控制、聊天运行时执行串起来，其中 `{turn_service or 'mainAgentTurnService.ts'}`、`{lifecycle or 'mainAgentLifecycleControlService.ts'}` 和 `{chat_runtime}` 是核心协作者。",
            f"主链执行后的 effect 应用与通知消费分别落到 `{effect_applier}` 和 `{notification_consumer}`，因此这条控制链同时连接了运行时执行面和任务通知回流面。",
        ]
    if domain["id"] == "model-and-tools":
        model_config = select_domain_file(representative_files, ("modelconfigservice",))
        main_toolkit = select_domain_file(representative_files, ("mainagenttoolkit",))
        main_registry = select_domain_file(representative_files, ("mainagenttoolregistry",))
        child_registry = select_domain_file(representative_files, ("childagenttoolkitregistry",))
        tool_usage_prompt = select_domain_file(representative_files, ("toolusageprompt",))
        concrete_tool = select_domain_file(representative_files, ("tools",), ("registry", "toolkit"))
        return [
            f"`{model_config or 'modelConfigService.ts'}` 先给运行时提供模型边界和超时配置，后续 toolkit 与 registry 的装配都会受这层约束影响。",
            f"`{main_toolkit or 'mainAgentToolkit.ts'}` 依赖 `{main_registry or 'mainAgentToolRegistry.ts'}` 汇总主 Agent 可见工具，而 `{child_registry or 'childAgentToolkitRegistry.ts'}` 负责把同样的装配模式扩展到子 Agent 侧。",
            f"`{tool_usage_prompt or 'toolUsagePrompt.ts'}` 与 `{concrete_tool or 'tools/'}` 把工具说明和具体实现继续往下接，使工具不仅被注册，还能真正被 prompt 和 runtime 消费。",
        ]
    if domain["id"] == "prompt-and-context-assets":
        prompt_service = select_domain_file(representative_files, ("agentpromptservice",))
        system_prompt = select_domain_file(representative_files, ("systemprompt",))
        persona_state = select_domain_file(representative_files, ("persona_state",))
        return [
            f"`{system_prompt or 'systemprompt.md'}`、`{persona_state or 'persona_state.json'}` 这类资源并不会直接参与运行，而是先作为静态 prompt 素材被读取。",
            f"`{prompt_service or 'agentPromptService.ts'}` 再把这些素材转成 AI 主链可消费的 prompt 结构，因此它是资源文件与运行时之间的关键桥梁。",
            "这意味着改动资源文件时，不能只看文案本身，还要同步核对 prompt 服务是否仍按当前资源结构进行组装。",
        ]
    if domain["id"] == "task-core-services":
        task_service = select_domain_file(representative_files, ("taskservice",))
        execution_service = select_domain_file(representative_files, ("taskexecutionservice",))
        trace_service = select_domain_file(representative_files, ("tasktraceservice",))
        inspection = select_domain_file(representative_files, ("inspectionmapper",))
        return [
            f"`{task_service or 'taskService.ts'}` 提供 task 主对象和活动任务上下文，后续 execution、continuation 和通知链都会从这里读取任务状态。",
            f"`{execution_service or 'taskExecutionService.ts'}` 在 task 之上管理执行单元，运行结果再交给 `{trace_service or 'taskTraceService.ts'}` 写入 trace，形成可回看的任务审计面。",
            f"`{inspection or 'taskExecutionInspectionMapper.ts'}` 负责把执行检查结果整理成更适合上层消费的结构，因此它常常处在主服务链和解释性输出之间。",
        ]
    if domain["id"] == "queue-and-dispatch":
        dispatcher = select_domain_file(representative_files, ("subagentdispatcherservice",))
        registry = select_domain_file(representative_files, ("subagentregistry",))
        queue = select_domain_file(representative_files, ("subagentexecutionqueueservice",))
        child_runtime = select_domain_file(representative_files, ("charactereditorruntimesupport",)) or "child-agent-system/"
        notification_bridge = "taskNotificationDispatchBridge.ts"
        return [
            f"`{queue or 'subAgentExecutionQueueService.ts'}` 负责把 execution 留在统一排队入口，而真正决定执行去向的是 `{dispatcher or 'subAgentDispatcherService.ts'}`。",
            f"`{dispatcher or 'subAgentDispatcherService.ts'}` 内部会同时协作 `{registry or 'subAgentRegistry.ts'}`、任务主服务链和 `{notification_bridge}`，因此它既关心派发对象，也关心执行结果如何回流。",
            f"最终的下游运行能力由 `{child_runtime}` 等 child-agent 运行支撑实现承接，所以这条链不能只看 queue 或 dispatcher，而要一起理解队列、派发和运行支撑之间的交接点。",
        ]
    if domain["id"] == "continuation-and-notification":
        notification = select_domain_file(representative_files, ("tasknotificationservice",))
        continuation = select_domain_file(representative_files, ("taskcontinuationservice",))
        recovery = select_domain_file(representative_files, ("taskrecoveryservice",))
        consumer = "taskNotificationConsumerService.ts"
        return [
            f"`{notification or 'taskNotificationService.ts'}` 负责把子任务执行结果落成通知记录，这一步会把任务状态推到等待主链确认的阶段。",
            f"`{continuation or 'taskContinuationService.ts'}` 会依赖任务主服务和子 Agent registry 处理补参续跑，而 `{recovery or 'taskRecoveryService.ts'}` 负责在异常或中断后把任务重新恢复到可继续推进的状态。",
            f"通知最终会被 `{consumer}` 消费并重新接回 AI runtime，所以这条链本质上是 task 子系统与 main agent 主链之间的回流接口。",
        ]
    if domain["id"] == "domain-services":
        world_service = select_domain_file(representative_files, ("worldbuildingservice",))
        avatar_service = select_domain_file(representative_files, ("avatarprofileservice",))
        return [
            f"`{world_service or 'worldbuildingService.ts'}` 会直接依赖共享 world/entity 定义与数据库实体，是领域编辑请求进入后端的主调用点。",
            f"`{avatar_service or 'avatarProfileService.ts'}` 与 worldbuilding 服务平行存在，角色资料与世界设定虽然是两条入口，但最终会共享同一套领域结构和实体定义。",
            "因此这份文档更适合回答“入口服务怎么暴露能力”，而不是“世界结构长什么样”；后者应继续去看 `共享世界结构定义`。",
        ]
    if domain["id"] == "shared-world-definitions":
        cache_defs = select_domain_file(representative_files, ("definitions.ts",))
        cache_state = select_domain_file(representative_files, ("worldbuilding.ts",))
        world_record = select_domain_file(representative_files, ("worldrecord",))
        relation_record = select_domain_file(representative_files, ("worldentityrelationrecord",))
        return [
            f"`{cache_defs or 'definitions.ts'}` 和 `{cache_state or 'worldbuilding.ts'}` 先把世界结构定义成运行时共享缓存可读的形状，供上层服务和前端状态共同消费。",
            f"`{world_record or 'WorldRecord.ts'}` 与 `{relation_record or 'WorldEntityRelationRecord.ts'}` 继续把这些共享定义落到数据库实体层，使领域服务能在持久化层复用同一套结构。",
            "上层 worldbuilding 服务读取的不是两套不同定义，而是这一层提供的共享缓存定义与实体定义，所以这里是领域结构的真正稳定面。",
        ]

    context_paths = [context["relative_path"] for context in contexts]
    if not context_paths:
        return ["当前专题域暂未识别出稳定的调用关系，建议直接从关键文件中的入口服务开始核对。"]
    return [
        f"`{context_paths[0]}` 是当前专题域最接近上游入口的实现面。",
        "建议沿着入口服务、主服务、下游协作的顺序继续核对调用关系。",
    ]


def describe_domain_file_role(path: Path, domain_id: str) -> str:
    name = path.name
    lower_name = name.lower()
    if domain_id == "runtime-orchestration":
        if "entry" in lower_name:
            return "主 Agent 对话链的入口服务"
        if "runcontrol" in lower_name or "turnservice" in lower_name:
            return "主 Agent 当前轮执行与控制流的关键服务"
        if "lifecycle" in lower_name:
            return "生命周期判断与状态推进入口"
        if "orchestration" in lower_name:
            return "事件编排与 effect 应用入口"
        if "notification" in lower_name:
            return "任务通知回流到 main agent 的消费入口"
        if "queue" in lower_name:
            return "主链异步事件或派发队列入口"
    if domain_id == "model-and-tools":
        if "modelconfig" in lower_name:
            return "模型配置与运行边界入口"
        if "toolkit" in lower_name:
            return "工具集合装配入口"
        if "registry" in lower_name:
            return "工具注册与能力清单入口"
        if "tool" in lower_name:
            return "具体工具能力的实现入口"
    if domain_id == "prompt-and-context-assets":
        if "promptservice" in lower_name:
            return "运行时 prompt 组装入口"
        if lower_name.endswith(".md") or lower_name.endswith(".json"):
            return "prompt 或上下文资源素材"
    if domain_id == "task-core-services":
        if "taskservice" in lower_name:
            return "task 主对象服务入口"
        if "executionservice" in lower_name:
            return "execution 生命周期服务入口"
        if "trace" in lower_name:
            return "任务 trace 与审计记录入口"
        if "inspection" in lower_name:
            return "execution 检查结果映射入口"
    if domain_id == "queue-and-dispatch":
        if "queue" in lower_name:
            return "子任务排队与出队控制入口"
        if "dispatcher" in lower_name:
            return "子 Agent 派发入口"
        if "registry" in lower_name:
            return "子 Agent 注册与能力选择入口"
        if "runtime" in lower_name or "execution" in lower_name:
            return "下游子 Agent 运行支撑入口"
    if domain_id == "continuation-and-notification":
        if "notification" in lower_name:
            return "任务通知生成或消费入口"
        if "continuation" in lower_name:
            return "任务续跑与补参入口"
        if "recovery" in lower_name:
            return "任务恢复链入口"
    if domain_id == "domain-services":
        if "worldbuilding" in lower_name:
            return "世界观编辑主服务入口"
        if "avatar" in lower_name:
            return "角色资料或画像编辑服务入口"
    if domain_id == "shared-world-definitions":
        if "definitions" in lower_name or "worldbuilding.ts" in lower_name:
            return "共享 worldbuilding 缓存与结构定义入口"
        if "record" in lower_name:
            return "world/entity 持久化实体定义入口"
    if domain_id == "ai-runtime":
        if "entry" in lower_name:
            return "AI 主链的进入点或启动入口"
        if "runtime" in lower_name:
            return "AI runtime 的主控制或执行环节"
        if "prompt" in lower_name:
            return "prompt 组织或提示词装配入口"
        if "model" in lower_name:
            return "模型配置或模型调用相关入口"
        if "tool" in lower_name:
            return "工具装配或工具使用规则入口"
    if domain_id == "task-orchestration":
        if "queue" in lower_name:
            return "任务或执行单元排队与调度的关键入口"
        if "dispatcher" in lower_name:
            return "任务分发或子 Agent 下发入口"
        if "continuation" in lower_name:
            return "任务续跑或补参回流的关键服务"
        if "notification" in lower_name:
            return "任务通知与回流链的关键服务"
        if "execution" in lower_name:
            return "执行单元生命周期或检查入口"
    if domain_id == "worldbuilding-domain":
        if "service" in lower_name:
            return "世界观或角色编辑能力的服务入口"
        if "entity" in lower_name or "world" in lower_name:
            return "领域实体或世界结构相关定义"
        if "avatar" in lower_name:
            return "角色或头像编辑相关入口"
    return "这一专题实现链里的关键文件或入口"


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


def infer_domain_breakdown(domain: dict, contexts: list[dict]) -> list[str]:
    if domain["id"] == "ai-runtime":
        return [
            "运行时主链：`aiservice/runtime/` 负责 main agent 的 turn、lifecycle、notification 和 orchestration。",
            "模型与工具装配：`aiservice/ai-utils/`、`modelconfig/` 负责模型参数、toolkit 和工具契约。",
            "提示词与上下文资源：`prompt-resource/` 和 `aiservice/prompt/` 共同为 AI 行为提供提示词与上下文素材。",
        ]
    if domain["id"] == "task-orchestration":
        return [
            "任务主服务：`taskService.ts`、`taskExecutionService.ts` 负责 task 与 execution 的核心编排。",
            "队列与分发：`queue/`、`subAgentDispatcherService.ts` 负责排队、派发和子 Agent 下发。",
            "续跑与通知：`taskContinuationService.ts`、`taskNotificationService.ts`、`taskRecoveryService.ts` 负责补参、回流和恢复。",
        ]
    if domain["id"] == "worldbuilding-domain":
        return [
            "领域服务：`worldbuildingService.ts` 承担世界观编辑与领域操作的主服务入口。",
            "角色相关能力：`avatar/` 目录补充角色或头像相关编辑能力。",
            "共享结构协作：这一专题通常还会依赖 `src/share/` 中的 world/entity 定义共同完成领域编辑。",
        ]
    if domain["id"] == "interaction-surface":
        return [
            "界面层：`renderer/src/views/` 和 `features/` 负责页面、功能块和用户交互。",
            "前端服务：`renderer/src/services/` 承担与主进程的请求封装。",
            "桥接层：`preload/` 负责把主进程能力安全暴露给渲染层。",
        ]
    if domain["id"] == "shared-contracts":
        return [
            "共享状态：`cache/` 承担 AI 状态、渲染状态和 worldbuilding 缓存结构。",
            "共享实体：`entity/database/` 承担跨层共用的数据库实体定义。",
            "通用工具：`utils/` 放置跨层共用的错误处理与辅助工具。",
        ]
    return [f"`{context['relative_path']}` 是这一专题当前的重要实现面。" for context in contexts]


def render_domain_doc(domain: dict, all_domains: list[dict], project_root: Path) -> str:
    title = domain["title"]
    parent = next((item for item in all_domains if item["id"] == domain.get("parent_id")), None)
    child_domains = [item for item in all_domains if item.get("parent_id") == domain["id"]]
    contexts = [build_context(path, (project_root / path).resolve(), project_root) for path in domain.get("paths", []) if (project_root / path).exists()]
    if child_domains:
        return render_domain_readme(domain, all_domains, project_root)
    coverage_list = format_bullets([format_domain_path_entry(context) for context in contexts])
    chain_list = format_bullets(infer_domain_chain(domain, contexts, parent))
    representative_files = collect_representative_domain_files(domain, project_root)
    flow_sequence_list = format_bullets(infer_domain_flow_sequence(domain, representative_files, contexts))
    call_summary_list = format_bullets(infer_domain_call_summary(domain, representative_files, contexts))
    breakdown_list = format_bullets(infer_domain_breakdown(domain, contexts))
    representative_file_list = format_bullets(
        [
            f"`{path}`：{describe_domain_file_role((project_root / path).resolve(), domain['id'])}"
            for path in representative_files
        ]
    ) if representative_files else "- 暂无代表性文件"

    domain_questions = domain.get("question_hints", []) or [
        f"{title} 当前主要覆盖哪些实现面",
        "这些实现面之间的边界如何划分",
        "当这个功能域变化时应优先更新哪些说明",
    ]
    key_entries = []
    for context in contexts:
        for entry in infer_key_entries(context)[:3]:
            key_entries.append(f"`{context['relative_path']}` -> {entry}")
    relationship_items = []
    if parent:
        relationship_items.append(f"它是 `{parent['title']}` 之下的第二层专题域，负责把上层运行时能力继续细分。")
    if child_domains:
        relationship_items.append("它本身还是上层功能域，应继续把问题分流到下一级专题域。")
    sibling_titles = [item["title"] for item in all_domains if item.get("parent_id") == domain.get("parent_id") and item["id"] != domain["id"]]
    if sibling_titles:
        relationship_items.append(f"与同层功能域 `{', '.join(sibling_titles)}` 一起构成当前项目的完整理解入口。")
    if not relationship_items:
        relationship_items.append("它与其他功能域的关系需要结合覆盖路径和调用链一起理解。")

    boundary_items = [
        "这里解释的是“功能职责和阅读入口”，不是逐文件复制实现细节。",
        "如果功能域说明与代码冲突，应先以代码为当前运行真相。",
    ]
    if parent:
        boundary_items.append(f"当需要理解更大的控制面时，回到 `{parent['title']}` 对应的上层文档。")
    if child_domains:
        boundary_items.append("当问题已经细化到某个专题链路时，应继续进入下层专题域，而不是把所有细节都压在这份文档里。")

    reading_items = [
        f"第一次接手时，先用这份文档建立 `{title}` 的整体边界，再按覆盖路径继续下沉。",
    ]
    if child_domains:
        reading_items.append("如果你要改动具体专题能力，优先进入下面列出的第二层专题域。")
    else:
        reading_items.append("如果你要核对真实行为，读完这里后直接回到覆盖路径对应的源码入口。")

    update_items = [
        f"`{title}` 覆盖路径中的任一关键链路发生重组或职责变化",
        "这一功能域与其他功能域的边界发生调整",
        "阅读入口已经不足以指导第一次接手的人或 AI 建立当前理解",
    ]

    return f"""# 功能域：{title}

## 一句话定位

{domain['summary']}

## 范围

- 功能域 ID：`{domain['id']}`
- 层级：`第 {domain['level']} 层`
- 上级功能域：`{parent['title'] if parent else '无'}`

## 这份文档回答什么问题

{format_bullets(domain_questions)}

## 当前结论

这个专题域已经进入具体实现层。读者不应该再把它理解成“目录集合”，而应把它看成一条需要被单独解释的实现链路。

## 覆盖路径

{coverage_list}

## 关键链路

{chain_list}

## 实现顺序摘要

{flow_sequence_list}

## 关键调用链摘要

{call_summary_list}

## 当前实现拆分

{breakdown_list}

## 关键文件

{representative_file_list}

## 关键入口

{format_bullets(key_entries[:8]) if key_entries else "- 暂无可用入口"}

## 与其他功能域的关系

{format_bullets(relationship_items)}

## 运行时边界

{format_bullets(boundary_items)}

## 阅读建议

{format_bullets(reading_items)}

## 何时更新本文件

{format_bullets(update_items)}
"""


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
            lines.append("  └─ 当前没有单独拆出的第二层专题域，直接进入这一层 README 查看边界、关键入口和阅读建议。")

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
        "这里按当前项目的功能架构列出第一层功能域，以及已经单独拆出的第二层专题域。",
        "第一次接手时，先在这里判断问题落在哪一层，再进入对应 README 继续下钻。",
        "",
        "## 这份文档怎么用",
        "",
        "- 先按第一层功能域判断问题落在交互面、共享契约还是后端运行时。",
        "- 如果某个功能域已经拆出了第二层专题域，优先继续进入对应专题。",
        "- 如果某个功能域还没有继续下钻，直接进入这一层 README 查看边界、关键入口和阅读建议。",
        "",
        "## 当前功能架构",
        "",
    ]
    lines.extend(architecture_lines)
    lines.extend(
        [
            "",
            "## 继续下钻时的原则",
            "",
            "- 这份索引只负责回答“先从哪一块进入”，不重复堆具体实现细节。",
            "- 当问题已经明确落到某条专题链路时，直接进入对应专题 README 或叶子文档。",
            "- 如果结构说明和代码冲突，以代码为准，再回头更新文档。",
        ]
    )
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
    index_payload["analysis_round"] = max(int(index_payload.get("analysis_round", 0)), 2)
    tracked_paths = set(index_payload.get("tracked_paths", []))
    tracked_paths.update(module_docs.keys())
    index_payload["tracked_paths"] = sorted(tracked_paths)
    index_path.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    update_modules_readme(doc_root, module_docs)

    if created:
        print(f"[完成] 已创建模块文档：{', '.join(created)}")
    else:
        print("[跳过] 没有模块文档被重写。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
