#!/usr/bin/env python3
"""
基于真实目录结构收集功能责任候选信号。
"""

from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path


ROOT_SIGNAL_RULES = [
    {
        "id": "interaction-surface",
        "title": "交互与展示相关路径",
        "summary": "这些路径的名称和位置提示它们可能与界面、交互或展示有关，仍需结合已确认 summary 和真实代码确认。",
        "signal_type": "root_runtime_hint",
        "path_candidates": [
            "src/renderer",
            "renderer",
            "client",
            "frontend",
            "web",
            "app",
            "src/preload",
            "preload",
        ],
    },
    {
        "id": "backend-runtime",
        "title": "运行时与服务相关路径",
        "summary": "这些路径可能承载主流程、服务编排、运行控制或数据接入，但具体边界仍需结合代码核对。",
        "signal_type": "root_runtime_hint",
        "path_candidates": [
            "src/main",
            "main",
            "server",
            "backend",
            "api",
            "runtime",
        ],
    },
    {
        "id": "shared-contracts",
        "title": "共享能力相关路径",
        "summary": "这些路径可能保存跨层共享的数据结构、公共工具或通用约束，但不应仅凭目录名直接下结论。",
        "signal_type": "shared_path_hint",
        "path_candidates": [
            "src/share",
            "share",
            "shared",
            "common",
            "src/common",
            "core",
            "libs",
            "lib",
        ],
    },
    {
        "id": "design-knowledge",
        "title": "文档与设计知识相关路径",
        "summary": "这些路径更像说明文档、专题设计或导航入口，但它们是否属于当前真相文档仍需继续判断。",
        "signal_type": "knowledge_path_hint",
        "path_candidates": [
            "developmentlog",
            "docs",
            "doc",
            "design",
            "spec",
            "specs",
        ],
    },
]

DOMAIN_PATH_OMIT_NAMES = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "out",
    "coverage",
    ".next",
    ".cache",
    "tmp",
    "temp",
    "project-docs",
    "public",
    "assets",
    "resources",
    "static",
}
UNWRAP_CONTAINER_NAMES = {"services", "service", "src"}
SECOND_LEVEL_OMIT_NAMES = {
    "__tests__",
    "tests",
    "test",
    "fixtures",
    "mock",
    "mocks",
    "example",
    "examples",
}
MEANINGFUL_DIR_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".vue", ".py", ".go", ".java", ".rs", ".md"}
COMMON_TITLE_MAP = {
    "ai": "AI",
    "api": "API",
    "ipc": "IPC",
    "ui": "UI",
    "ux": "UX",
    "db": "DB",
    "runtime": "runtime",
    "prompt": "prompt",
    "task": "task",
    "queue": "queue",
    "service": "service",
    "services": "services",
    "model": "model",
    "models": "models",
    "cache": "cache",
    "entity": "entity",
    "entities": "entities",
    "protocol": "protocol",
    "protocols": "protocols",
}


def slugify(value: str) -> str:
    return value.replace("\\", "/").strip("/").replace("/", "__").replace(":", "").replace(".", "_")


def git_ignore_enabled(project_root: Path) -> bool:
    return (project_root / ".gitignore").exists()


@lru_cache(maxsize=32)
def declared_gitignore_entries(project_root_str: str) -> tuple[str, ...]:
    gitignore_path = Path(project_root_str) / ".gitignore"
    if not gitignore_path.exists():
        return ()
    entries = []
    for raw_line in gitignore_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        entries.append(line)
    return tuple(entries)


def matches_declared_gitignore(project_root: Path, relative_path: str) -> bool:
    clean = relative_path.replace("\\", "/").strip("/")
    if not clean:
        return False
    for pattern in declared_gitignore_entries(str(project_root)):
        normalized = pattern.replace("\\", "/").strip()
        if not normalized:
            continue
        if normalized.endswith("/"):
            normalized = normalized.rstrip("/")
        if any(token in normalized for token in ("*", "?", "[")):
            continue
        if normalized.startswith("/"):
            prefix = normalized.strip("/")
            if clean == prefix or clean.startswith(prefix + "/"):
                return True
            continue
        if "/" not in normalized:
            if clean == normalized or clean.startswith(normalized + "/"):
                return True
    return False


@lru_cache(maxsize=4096)
def is_git_ignored(project_root_str: str, relative_path: str) -> bool:
    if not relative_path:
        return False
    if matches_declared_gitignore(Path(project_root_str), relative_path):
        return True
    try:
        result = subprocess.run(
            ["git", "-C", project_root_str, "check-ignore", "-q", relative_path],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def visible_path_exists(project_root: Path, relative_path: str) -> bool:
    clean = relative_path.replace("\\", "/").strip("/")
    if not clean:
        return False
    path = project_root / clean
    if not path.exists():
        return False
    if git_ignore_enabled(project_root) and is_git_ignored(str(project_root), clean):
        return False
    return True


def collect_existing_paths(project_root: Path, candidates: list[str]) -> list[str]:
    existing = []
    seen = set()
    for candidate in candidates:
        clean = candidate.replace("\\", "/").strip("/")
        if clean and clean not in seen and visible_path_exists(project_root, clean):
            existing.append(clean)
            seen.add(clean)
    return existing


def split_identifier(value: str) -> list[str]:
    raw = value.replace("-", "_")
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    return [part for part in raw.split("_") if part]


def humanize_segment(name: str) -> str:
    words = []
    for part in split_identifier(name):
        lowered = part.lower()
        mapped = COMMON_TITLE_MAP.get(lowered)
        if mapped:
            words.append(mapped)
        elif part.isupper():
            words.append(part)
        else:
            words.append(part)
    return " ".join(words) if words else name


def infer_title_from_path(relative_path: str) -> str:
    clean = relative_path.replace("\\", "/").strip("/")
    last = clean.split("/")[-1] if clean else relative_path
    return humanize_segment(last)


def infer_summary_from_path(relative_path: str) -> str:
    clean = relative_path.replace("\\", "/").strip("/")
    last = clean.split("/")[-1].lower() if clean else ""
    if last in {"database", "db"}:
        return "名称暗示它可能与数据库接入、实体持久化或存取有关，仍需结合代码确认。"
    if last in {"protocol", "protocols", "ipc"}:
        return "名称暗示它可能与协议接入、桥接边界或进程间通信有关，仍需结合代码确认。"
    if last in {"cache", "state", "store"}:
        return "名称暗示它可能与缓存、状态组织或共享状态结构有关，仍需结合代码确认。"
    if last in {"views", "pages", "screens"}:
        return "名称暗示它可能更接近页面级视图或主要交互入口。"
    if last in {"components", "widgets"}:
        return "名称暗示它可能更接近可复用界面单元或局部交互实现。"
    if last in {"services", "service"}:
        return "名称暗示它可能更接近服务实现、业务编排或能力暴露。"
    if last in {"utils", "helpers"}:
        return "名称暗示它可能保存通用工具、辅助函数或支撑性实现。"
    if last in {"config", "configs"}:
        return "名称暗示它可能更接近配置组织、运行边界或工程参数。"
    return f"`{clean}` 可能覆盖一组相关实现面、关键入口或协作路径，具体职责仍需继续核对。"


def infer_question_hints(title: str, relative_path: str) -> list[str]:
    return [
        f"`{relative_path}` 在当前项目里实际承担什么职责",
        f"`{relative_path}` 这条路径里的关键入口和协作关系是什么",
        f"{title} 只是候选信号还是已经能形成稳定功能域",
    ]


def direct_meaningful_file_count(path: Path, limit: int = 40) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    count = 0
    for child in path.iterdir():
        if child.is_file() and child.suffix.lower() in MEANINGFUL_DIR_SUFFIXES:
            count += 1
            if count >= limit:
                break
    return count


def is_meaningful_topic_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    lower_name = path.name.lower()
    if lower_name.startswith("."):
        return False
    if lower_name in DOMAIN_PATH_OMIT_NAMES or lower_name in SECOND_LEVEL_OMIT_NAMES:
        return False
    if lower_name in {"node_modules", "__pycache__"}:
        return False
    try:
        next(path.iterdir())
    except StopIteration:
        return False
    return True


def contains_meaningful_files(path: Path, max_scan: int = 200) -> bool:
    scanned = 0
    for child in path.rglob("*"):
        scanned += 1
        if scanned > max_scan:
            break
        if child.is_file() and child.suffix.lower() in MEANINGFUL_DIR_SUFFIXES:
            return True
    return False


def unwrap_topic_roots(path: Path) -> list[Path]:
    if not path.exists() or not path.is_dir():
        return []
    lower_name = path.name.lower()
    direct_files = direct_meaningful_file_count(path)
    if lower_name in {"renderer", "client", "frontend", "web", "app"}:
        src_dir = path / "src"
        if src_dir.is_dir() and direct_files <= 3:
            return [src_dir]
    if lower_name in {"main", "server", "backend", "api"}:
        roots = [path]
        services_dir = path / "services"
        if services_dir.is_dir() and direct_files <= 8:
            roots.append(services_dir)
        return roots
    return [path]


def discover_child_topic_paths(project_root: Path, parent_domain: dict, max_children: int = 6) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen = set()
    for rel in parent_domain.get("paths", []):
        target = project_root / rel
        if not target.exists() or not target.is_dir():
            continue
        for root in unwrap_topic_roots(target):
            for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
                if not is_meaningful_topic_dir(child):
                    continue
                if child.name.lower() in UNWRAP_CONTAINER_NAMES:
                    for nested in sorted(child.iterdir(), key=lambda item: item.name.lower()):
                        if not is_meaningful_topic_dir(nested):
                            continue
                        if not contains_meaningful_files(nested):
                            continue
                        child_rel = nested.relative_to(project_root).as_posix()
                        if child_rel in seen:
                            continue
                        score = len(list(nested.iterdir()))
                        candidates.append((score, child_rel))
                        seen.add(child_rel)
                    continue
                if not contains_meaningful_files(child):
                    continue
                child_rel = child.relative_to(project_root).as_posix()
                if child_rel in seen:
                    continue
                score = len(list(child.iterdir()))
                candidates.append((score, child_rel))
                seen.add(child_rel)
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in candidates[:max_children]]


def build_dynamic_domains(project_root: Path, parent_domain: dict, *, max_depth: int = 3) -> list[dict]:
    if parent_domain.get("level", 1) >= max_depth:
        return []
    level = int(parent_domain.get("level", 1)) + 1
    rel_paths = discover_child_topic_paths(project_root, parent_domain)
    domains = []
    for rel_path in rel_paths:
        title = infer_title_from_path(rel_path)
        domain = {
            "id": f"{parent_domain['id']}__{slugify(rel_path)}",
            "title": title,
            "level": level,
            "parent_id": parent_domain["id"],
            "always_directory": False,
            "summary": infer_summary_from_path(rel_path),
            "question_hints": infer_question_hints(title, rel_path),
            "signal_type": "path_cluster_hint",
            "signal_strength": "medium",
            "signal_basis": [f"derived_from_parent:{parent_domain['id']}", f"path:{rel_path}"],
            "candidate": True,
            "paths": [rel_path],
        }
        domains.append(domain)
    return domains


def domain_chain(domain: dict, domain_lookup: dict[str, dict]) -> list[str]:
    chain = [slugify(domain["id"])]
    current = domain
    while current.get("parent_id"):
        parent = domain_lookup.get(current["parent_id"])
        if not parent:
            break
        chain.append(slugify(parent["id"]))
        current = parent
    chain.reverse()
    return chain


def assign_doc_paths(domains: list[dict]) -> list[dict]:
    domain_lookup = {domain["id"]: domain for domain in domains}
    children_map: dict[str, list[dict]] = {}
    for domain in domains:
        parent_id = domain.get("parent_id")
        if parent_id:
            children_map.setdefault(parent_id, []).append(domain)

    assigned = []
    for domain in domains:
        chain = domain_chain(domain, domain_lookup)
        has_children = bool(children_map.get(domain["id"]))
        if domain.get("level") == 1 or has_children or domain.get("always_directory"):
            doc_path = "/".join(["modules", *chain, "README.md"])
        else:
            parent_chain = chain[:-1]
            doc_path = "/".join(["modules", *parent_chain, f"{chain[-1]}.md"])
        updated = dict(domain)
        updated["doc_path"] = doc_path
        assigned.append(updated)
    return assigned


def infer_architecture_signals(project_root: Path) -> list[dict]:
    level_one_domains = []
    for rule in ROOT_SIGNAL_RULES:
        covered_paths = collect_existing_paths(project_root, rule["path_candidates"])
        if not covered_paths:
            continue
        level_one_domains.append(
            {
                "id": rule["id"],
                "title": rule["title"],
                "level": 1,
                "parent_id": None,
                "always_directory": True,
                "summary": rule["summary"],
                "question_hints": infer_question_hints(rule["title"], covered_paths[0]),
                "signal_type": rule.get("signal_type", "root_path_hint"),
                "signal_strength": "medium" if len(covered_paths) == 1 else "high",
                "signal_basis": [f"matched:{path}" for path in covered_paths],
                "candidate": True,
                "paths": covered_paths,
            }
        )

    dynamic_domains = []
    frontier = list(level_one_domains)
    visited = set()
    while frontier:
        parent = frontier.pop(0)
        if parent["id"] in visited:
            continue
        visited.add(parent["id"])
        children = build_dynamic_domains(project_root, parent, max_depth=3)
        dynamic_domains.extend(children)
        frontier.extend(children)

    domains = assign_doc_paths(level_one_domains + dynamic_domains)
    domains.sort(key=lambda item: (item["level"], item["title"], item["id"]))
    return domains


def infer_architecture_domains(project_root: Path) -> list[dict]:
    return infer_architecture_signals(project_root)


def recommended_domain_ids(domains: list[dict]) -> list[str]:
    return [domain["id"] for domain in domains]


def domains_by_parent(domains: list[dict]) -> dict[str | None, list[dict]]:
    grouped: dict[str | None, list[dict]] = {}
    for domain in domains:
        grouped.setdefault(domain.get("parent_id"), []).append(domain)
    for items in grouped.values():
        items.sort(key=lambda item: (item["level"], item["title"], item["id"]))
    return grouped


def tracked_top_level_paths(domains: list[dict]) -> list[str]:
    paths = []
    seen = set()
    for domain in domains:
        for rel in domain.get("paths", []):
            top = rel.split("/", 1)[0]
            if top not in seen:
                paths.append(top)
                seen.add(top)
    return paths
