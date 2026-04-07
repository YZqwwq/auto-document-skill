#!/usr/bin/env python3
"""
推断项目的功能架构域，用于替代单纯按目录路径生成第一层模块文档。
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path


DOMAIN_TEMPLATES = [
    {
        "id": "interaction-surface",
        "title": "交互与展示层",
        "level": 1,
        "parent_id": None,
        "summary": "负责界面、路由、渲染层服务以及应用与用户之间的交互体验。",
        "question_hints": [
            "用户主要通过哪些界面和交互面进入系统",
            "前端页面、组件和桥接层如何分工",
            "当界面体验变化时应优先阅读哪些路径",
        ],
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
        "title": "后端运行时层",
        "level": 1,
        "parent_id": None,
        "summary": "负责主进程、服务编排、协议接入、数据存取和系统控制面。",
        "question_hints": [
            "系统真正的运行控制面落在哪里",
            "主进程、服务、协议与数据库如何分层",
            "当系统主链调整时应优先核对哪些路径",
        ],
        "path_candidates": [
            "src/main",
            "main",
            "server",
            "backend",
            "api",
        ],
    },
    {
        "id": "shared-contracts",
        "title": "共享契约与实体",
        "level": 1,
        "parent_id": None,
        "summary": "负责跨层共享的数据结构、实体、缓存和通用工具，减少前后端之间的重复定义。",
        "question_hints": [
            "哪些数据结构会被多个运行时面共同依赖",
            "跨层共享实体和工具被放在什么位置",
            "当共享契约变化时，会波及哪些实现面",
        ],
        "path_candidates": [
            "src/share",
            "share",
            "shared",
            "common",
            "src/common",
        ],
    },
    {
        "id": "design-knowledge",
        "title": "设计知识与说明文档",
        "level": 1,
        "parent_id": None,
        "summary": "负责沉淀当前系统真相、专题说明和阅读导航，帮助读者在进入代码前建立理解上下文。",
        "question_hints": [
            "项目有哪些解释性文档和知识入口",
            "当前系统真相、专题设计和待办路线如何区分",
            "第一次接手时应该按什么顺序阅读文档",
        ],
        "path_candidates": [
            "developmentlog",
            "docs",
            "doc",
            "design",
            "specs",
        ],
    },
    {
        "id": "ai-runtime",
        "title": "AI 能力与代理主链",
        "level": 2,
        "parent_id": "backend-runtime",
        "summary": "负责模型调用、agent 运行时、prompt 组织和 AI 主链编排。",
        "question_hints": [
            "AI 主链如何组织模型调用、agent runtime 和 prompt",
            "哪些路径承载主 agent 的核心实现",
            "如果 AI 行为变化，应先读哪一组实现或说明",
        ],
        "path_candidates": [
            "src/main/services/aiservice",
            "src/main/services/modelconfig",
            "src/main/prompt-resource",
            "prompt-resource",
            "developmentlog/AIagent-design",
        ],
    },
    {
        "id": "task-orchestration",
        "title": "任务与子 Agent 编排",
        "level": 2,
        "parent_id": "backend-runtime",
        "summary": "负责 task、execution、queue、continuation 以及子 Agent 的调度回流。",
        "question_hints": [
            "任务、执行单元和子 Agent 是如何被编排的",
            "队列、通知回流和补参链路落在哪些路径",
            "修改执行链时应先检查哪些实现面",
        ],
        "path_candidates": [
            "src/main/services/task",
            "src/main/services/aiservice/child-agent-system",
            "developmentlog/AIagent-design/task",
        ],
    },
    {
        "id": "logging-observability",
        "title": "日志与可观测性",
        "level": 2,
        "parent_id": "backend-runtime",
        "summary": "负责日志写入、日志结构、观测面与调试入口。",
        "question_hints": [
            "系统日志和调试信息是如何组织的",
            "日志结构和消费方式落在哪些路径",
            "如果排查运行问题，应先进入哪些实现或说明",
        ],
        "path_candidates": [
            "src/main/services/log",
            "developmentlog/AIlogSystem",
        ],
    },
    {
        "id": "worldbuilding-domain",
        "title": "世界观与角色编辑",
        "level": 2,
        "parent_id": "backend-runtime",
        "summary": "负责世界观、角色设定、领域数据和编辑工作流。",
        "question_hints": [
            "世界观、角色或领域编辑能力落在哪里",
            "与角色、设定和编辑器相关的实现如何分层",
            "如果领域模型变化，应先更新哪些文档",
        ],
        "path_candidates": [
            "src/main/services/worldbuilding",
            "src/main/services/avatar",
            "developmentlog/worldDesign",
        ],
    },
    {
        "id": "runtime-orchestration",
        "title": "主 Agent 运行时控制",
        "level": 3,
        "parent_id": "ai-runtime",
        "summary": "负责 main agent 的 runtime、lifecycle、notification 和主链编排控制。",
        "question_hints": [
            "main agent 的 runtime 控制链落在哪里",
            "turn、lifecycle、notification 和 orchestration 如何分工",
            "如果主链执行顺序变化，应先检查哪些实现",
        ],
        "path_candidates": [
            "src/main/services/aiservice/runtime",
        ],
    },
    {
        "id": "model-and-tools",
        "title": "模型与工具装配",
        "level": 3,
        "parent_id": "ai-runtime",
        "summary": "负责模型配置、toolkit 装配、工具契约与 AI 能力装配面。",
        "question_hints": [
            "模型配置和 toolkit 在哪里装配",
            "工具系统和模型调用如何接入 AI 主链",
            "修改工具契约时应先进入哪些路径",
        ],
        "path_candidates": [
            "src/main/services/aiservice/ai-utils",
            "src/main/services/modelconfig",
        ],
    },
    {
        "id": "prompt-and-context-assets",
        "title": "Prompt 与提示资源",
        "level": 3,
        "parent_id": "ai-runtime",
        "summary": "负责系统 prompt、角色化提示词和上下文资源，为 AI 主链提供输入素材。",
        "question_hints": [
            "prompt 结构和提示资源放在哪里",
            "系统 prompt 与角色资源如何组织",
            "如果 AI 表达和提示词变化，应先检查哪些路径",
        ],
        "path_candidates": [
            "src/main/prompt-resource",
            "src/main/services/aiservice/prompt",
        ],
    },
    {
        "id": "task-core-services",
        "title": "任务主服务",
        "level": 3,
        "parent_id": "task-orchestration",
        "summary": "负责 task、execution 和 trace 的核心服务编排。",
        "question_hints": [
            "task 和 execution 的主服务入口在哪里",
            "trace 与 inspection 如何接进任务主链",
            "修改任务核心流时应先看哪些文件",
        ],
        "path_candidates": [
            "src/main/services/task/taskService.ts",
            "src/main/services/task/taskExecutionService.ts",
            "src/main/services/task/taskTraceService.ts",
            "src/main/services/task/taskExecutionInspectionMapper.ts",
        ],
    },
    {
        "id": "queue-and-dispatch",
        "title": "队列与分发",
        "level": 3,
        "parent_id": "task-orchestration",
        "summary": "负责 execution queue、子 Agent 分发和任务下发调度。",
        "question_hints": [
            "任务队列与分发链落在哪里",
            "子 Agent 派发和排队逻辑如何协作",
            "如果队列调度变化，应先检查哪些实现",
        ],
        "path_candidates": [
            "src/main/services/task/queue",
            "src/main/services/task/subAgentDispatcherService.ts",
            "src/main/services/task/subAgentRegistry.ts",
            "src/main/services/aiservice/child-agent-system",
        ],
    },
    {
        "id": "continuation-and-notification",
        "title": "续跑与通知回流",
        "level": 3,
        "parent_id": "task-orchestration",
        "summary": "负责任务 continuation、notification 和恢复链，把子任务结果回流到主链。",
        "question_hints": [
            "任务续跑和通知回流落在哪里",
            "恢复链和通知链如何与队列协作",
            "如果补参或回流逻辑变化，应先检查哪些实现",
        ],
        "path_candidates": [
            "src/main/services/task/taskContinuationService.ts",
            "src/main/services/task/taskNotificationService.ts",
            "src/main/services/task/taskRecoveryService.ts",
            "src/main/services/aiservice/runtime/notification",
        ],
    },
    {
        "id": "domain-services",
        "title": "领域服务入口",
        "level": 3,
        "parent_id": "worldbuilding-domain",
        "summary": "负责 worldbuilding 与 avatar 的服务入口，是领域编辑能力的后端入口面。",
        "question_hints": [
            "世界观与角色编辑的主服务入口在哪里",
            "领域服务如何对外暴露",
            "修改 worldbuilding 主入口时应先看哪些文件",
        ],
        "path_candidates": [
            "src/main/services/worldbuilding/worldbuildingService.ts",
            "src/main/services/avatar/avatarProfileService.ts",
        ],
    },
    {
        "id": "shared-world-definitions",
        "title": "共享世界结构定义",
        "level": 3,
        "parent_id": "worldbuilding-domain",
        "summary": "负责 worldbuilding 相关的共享缓存、定义和数据库实体，是领域服务的共享结构面。",
        "question_hints": [
            "worldbuilding 的共享定义和实体落在哪里",
            "领域缓存与数据库记录如何对应",
            "如果世界结构变化，应先检查哪些共享文件",
        ],
        "path_candidates": [
            "src/share/cache/worldbuilding",
            "src/share/entity/database/WorldRecord.ts",
            "src/share/entity/database/WorldEntityRecord.ts",
            "src/share/entity/database/WorldEntityRelationRecord.ts",
            "src/share/entity/database/WorldEntityComponentRecord.ts",
        ],
    },
]


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
        if domain.get("level") == 1 or has_children:
            doc_path = "/".join(["modules", *chain, "README.md"])
        else:
            parent_chain = chain[:-1]
            doc_path = "/".join(["modules", *parent_chain, f"{chain[-1]}.md"])
        updated = dict(domain)
        updated["doc_path"] = doc_path
        assigned.append(updated)
    return assigned


def infer_architecture_domains(project_root: Path) -> list[dict]:
    domains = []
    existing_ids = set()

    for template in DOMAIN_TEMPLATES:
        covered_paths = collect_existing_paths(project_root, template["path_candidates"])
        if not covered_paths:
            continue
        domain = {
            "id": template["id"],
            "title": template["title"],
            "level": template["level"],
            "parent_id": template["parent_id"],
            "summary": template["summary"],
            "question_hints": list(template["question_hints"]),
            "paths": covered_paths,
        }
        domains.append(domain)
        existing_ids.add(domain["id"])

    filtered = []
    for domain in domains:
        parent_id = domain.get("parent_id")
        if parent_id and parent_id not in existing_ids:
            domain["parent_id"] = None
            domain["level"] = 1
        filtered.append(domain)

    filtered = assign_doc_paths(filtered)
    filtered.sort(key=lambda item: (item["level"], item["title"]))
    return filtered


def recommended_domain_ids(domains: list[dict]) -> list[str]:
    return [domain["id"] for domain in domains]


def domains_by_parent(domains: list[dict]) -> dict[str | None, list[dict]]:
    grouped: dict[str | None, list[dict]] = {}
    for domain in domains:
        grouped.setdefault(domain.get("parent_id"), []).append(domain)
    for items in grouped.values():
        items.sort(key=lambda item: (item["level"], item["title"]))
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
