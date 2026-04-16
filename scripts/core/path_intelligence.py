#!/usr/bin/env python3
"""
通用路径证据工具。

这里不负责直接替 AI 下结论，
而是把路径、文件和目录拆成：

- 事实采集
- 弱提示生成
- 面向文档/Prompt 的证据表达

兼容层中仍保留少量布尔函数，供旧调用方继续使用；
但它们的语义应理解为“弱提示”而不是最终判断。
"""

from __future__ import annotations

import re
from pathlib import Path


MARKDOWN_SUFFIXES = {".md", ".mdx", ".markdown"}
TEXT_SUFFIXES = MARKDOWN_SUFFIXES | {".txt", ".rst"}
STRUCTURED_TEXT_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}
CODE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".vue", ".py", ".go", ".java", ".rs", ".sh"}
MEANINGFUL_SUFFIXES = TEXT_SUFFIXES | STRUCTURED_TEXT_SUFFIXES | CODE_SUFFIXES
DEFAULT_OMIT_DIR_NAMES = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "out",
    ".next",
    ".cache",
    "coverage",
    "__pycache__",
    "project-docs",
}
LOW_SIGNAL_NAME_HINTS = {
    "test",
    "tests",
    "spec",
    "specs",
    "mock",
    "mocks",
    "fixture",
    "fixtures",
    "snapshot",
    "snapshots",
    "example",
    "examples",
}
LOW_SIGNAL_SUFFIX_HINTS = (
    ".test.ts",
    ".test.tsx",
    ".test.js",
    ".spec.ts",
    ".spec.tsx",
    ".spec.js",
    ".snap",
)
README_CANDIDATES = ("README.md", "README.mdx", "readme.md")
COMMON_TITLE_MAP = {
    "ai": "AI",
    "api": "API",
    "ipc": "IPC",
    "ui": "UI",
    "ux": "UX",
    "db": "DB",
}


def normalize_relpath(value: str) -> str:
    return value.replace("\\", "/").strip("/")


def split_identifier(value: str) -> list[str]:
    raw = value.replace("-", "_")
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    return [part for part in raw.split("_") if part]


def humanize_segment(name: str) -> str:
    words = []
    for part in split_identifier(name):
        lowered = part.lower()
        if lowered in COMMON_TITLE_MAP:
            words.append(COMMON_TITLE_MAP[lowered])
        elif part.isupper():
            words.append(part)
        else:
            words.append(part)
    return " ".join(words) if words else name


def infer_title_from_path(relative_path: str) -> str:
    clean = normalize_relpath(relative_path)
    last = clean.split("/")[-1] if clean else relative_path
    return humanize_segment(last)


def tokenize_path(relative_path: str) -> list[str]:
    clean = normalize_relpath(relative_path)
    tokens: list[str] = []
    for part in clean.split("/"):
        if not part:
            continue
        tokens.extend(item.lower() for item in split_identifier(part))
    return list(dict.fromkeys(tokens))


def path_depth(relative_path: str) -> int:
    clean = normalize_relpath(relative_path)
    return max(1, len([part for part in clean.split("/") if part])) if clean else 1


def is_root_text_like_path(relative_path: str) -> bool:
    clean = normalize_relpath(relative_path)
    if not clean or "/" in clean:
        return False
    suffix = Path(clean).suffix.lower()
    return suffix in TEXT_SUFFIXES or clean.lower() == "readme"


def is_root_structured_config_path(relative_path: str) -> bool:
    clean = normalize_relpath(relative_path)
    if not clean or "/" in clean:
        return False
    return Path(clean).suffix.lower() in STRUCTURED_TEXT_SUFFIXES


def is_root_context_signal_path(relative_path: str) -> bool:
    return is_root_text_like_path(relative_path) or is_root_structured_config_path(relative_path)


def is_low_semantic_risk_path(relative_path: str) -> bool:
    clean = normalize_relpath(relative_path).lower()
    tokens = set(tokenize_path(relative_path))
    return bool(tokens & LOW_SIGNAL_NAME_HINTS) or any(clean.endswith(suffix) for suffix in LOW_SIGNAL_SUFFIX_HINTS)


def safe_read_text(path: Path, max_chars: int = 3000) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return None


def count_meaningful_children(path: Path, max_scan: int = 200) -> tuple[int, int]:
    if not path.exists() or not path.is_dir():
        return 0, 0
    dir_count = 0
    file_count = 0
    scanned = 0
    for child in path.rglob("*"):
        scanned += 1
        if scanned > max_scan:
            break
        if child.is_dir():
            if child.name.lower() in DEFAULT_OMIT_DIR_NAMES or child.name.startswith("."):
                continue
            dir_count += 1
        elif child.suffix.lower() in MEANINGFUL_SUFFIXES:
            file_count += 1
    return dir_count, file_count


def collect_sample_entries(path: Path, limit: int = 8) -> list[str]:
    if path.is_file():
        return [path.name]
    entries = []
    for child in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if child.name.startswith(".") or child.name.lower() in DEFAULT_OMIT_DIR_NAMES:
            continue
        entries.append(child.name + ("/" if child.is_dir() else ""))
        if len(entries) >= limit:
            break
    return entries


def collect_readme_summary(path: Path) -> str | None:
    search_dir = path if path.is_dir() else path.parent
    for candidate_name in README_CANDIDATES:
        candidate = search_dir / candidate_name
        if not candidate.exists() or not candidate.is_file():
            continue
        text = safe_read_text(candidate, max_chars=2000) or ""
        lines = []
        in_code_block = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block or not line or line.startswith("#"):
                continue
            lines.append(line)
            if len(" ".join(lines)) >= 140:
                break
        if lines:
            return " ".join(lines)[:180]
    return None


def collect_path_facts(relative_path: str, target_path: Path, *, max_scan: int = 200, sample_limit: int = 8) -> dict:
    clean = normalize_relpath(relative_path)
    suffix = target_path.suffix.lower()
    tokens = tokenize_path(clean)
    readme_summary = collect_readme_summary(target_path)
    sample_entries = collect_sample_entries(target_path, limit=sample_limit)
    dir_count, file_count = count_meaningful_children(target_path, max_scan=max_scan) if target_path.is_dir() else (0, 0)

    return {
        "relative_path": clean,
        "title": infer_title_from_path(clean),
        "path_depth": path_depth(clean),
        "path_type": "directory" if target_path.is_dir() else "file",
        "basename": target_path.name if clean else target_path.name,
        "parent_name": target_path.parent.name if clean else "",
        "suffix": suffix,
        "tokens": tokens,
        "is_root_level": "/" not in clean,
        "looks_like_code": suffix in CODE_SUFFIXES,
        "looks_like_text": suffix in TEXT_SUFFIXES,
        "looks_like_structured_text": suffix in STRUCTURED_TEXT_SUFFIXES,
        "root_text_like": is_root_text_like_path(clean),
        "root_structured_config_like": is_root_structured_config_path(clean),
        "low_signal_name_hint": bool(set(tokens) & LOW_SIGNAL_NAME_HINTS),
        "low_signal_suffix_hint": any(clean.lower().endswith(item) for item in LOW_SIGNAL_SUFFIX_HINTS),
        "dir_count": dir_count,
        "file_count": file_count,
        "sample_entries": sample_entries,
        "readme_summary": readme_summary,
    }


def build_weak_path_hints(relative_path: str, target_path: Path, facts: dict | None = None) -> list[str]:
    info = facts or collect_path_facts(relative_path, target_path)
    hints = []
    if info["is_root_level"] and info["root_text_like"]:
        hints.append("这是根级文本文件，更适合作为项目意图或边界证据，而不是直接等价于功能域。")
    if info["is_root_level"] and info["root_structured_config_like"]:
        hints.append("这是根级结构化配置文件，更适合作为运行边界、工具链或结构约束证据。")
    if info["low_signal_name_hint"] or info["low_signal_suffix_hint"]:
        hints.append("路径名或文件名带有 test/mock/example/spec 等低主链提示，但不能仅凭命名就排除其价值。")
    if info["path_type"] == "directory" and info["dir_count"] and info["file_count"]:
        hints.append("这一层同时暴露出子主题和实现材料，可能更像候选容器，而不是单一职责点。")
    elif info["path_type"] == "directory" and info["dir_count"]:
        hints.append("这一层目前更像主题容器，仍需要继续下钻确认稳定边界。")
    elif info["path_type"] == "directory" and info["file_count"]:
        hints.append("这一层更像实现材料聚合点，是否构成功能域仍需要结合上层语义判断。")
    if info["readme_summary"]:
        hints.append("同层 README 可作为局部语境证据，但不应被直接当成最终职责定义。")
    if info["path_type"] == "file" and info["looks_like_code"]:
        hints.append("这是代码文件，可能是实现入口，也可能只是辅助实现，需要继续核对调用关系。")
    return hints


def estimate_path_evidence_richness(relative_path: str, target_path: Path, facts: dict | None = None) -> int:
    info = facts or collect_path_facts(relative_path, target_path)
    score = 0
    if info["path_type"] == "directory":
        score += 18
        score += min(20, info["dir_count"] * 2)
        score += min(16, info["file_count"])
        if info["sample_entries"]:
            score += min(6, len(info["sample_entries"]))
    else:
        score += 8
        if info["looks_like_code"]:
            score += 12
        elif info["looks_like_text"] or info["looks_like_structured_text"]:
            score += 9
        elif info["suffix"]:
            score += 5
        else:
            score += 3
    if info["readme_summary"]:
        score += 8
    return score


def summarize_path(relative_path: str, target_path: Path) -> str:
    facts = collect_path_facts(relative_path, target_path)
    title = facts["title"]
    weak_hints = build_weak_path_hints(relative_path, target_path, facts)

    if facts["path_type"] == "file":
        if facts["is_root_level"] and (facts["root_text_like"] or facts["root_structured_config_like"]):
            return f"`{title}` 当前更像帮助理解项目意图、运行边界或工具链约束的证据点。"
        if facts["looks_like_code"]:
            return f"`{title}` 当前更像一个需要结合调用关系和上层语义继续确认职责的代码证据点。"
        if facts["looks_like_text"] or facts["looks_like_structured_text"]:
            return f"`{title}` 当前更像一个帮助解释局部设计或运行边界的文件证据点。"
        return f"`{title}` 当前是一个需要继续结合上下文理解职责的文件证据点。"

    if facts["dir_count"] and facts["file_count"]:
        return f"`{title}` 当前像一个同时承载子主题和实现材料的候选容器。"
    if facts["dir_count"]:
        return f"`{title}` 当前像一个仍需继续下钻确认边界的候选主题目录。"
    if facts["file_count"]:
        return f"`{title}` 当前像一个聚合局部实现材料的候选目录。"
    if weak_hints:
        return f"`{title}` 当前证据较少，暂时更适合作为待确认路径而不是直接下语义结论。"
    return f"`{title}` 当前还缺少足够证据，暂时只能作为待确认的路径候选。"


def build_path_evidence(relative_path: str, target_path: Path) -> list[str]:
    facts = collect_path_facts(relative_path, target_path)
    evidence = [
        f"相对路径：`{facts['relative_path']}`。",
        f"路径类型：{'目录' if facts['path_type'] == 'directory' else '文件'}。",
        f"路径深度：{facts['path_depth']}。",
    ]
    if facts["path_type"] == "directory":
        evidence.append(f"可见有效子目录约 {facts['dir_count']} 个、有效文件约 {facts['file_count']} 个。")
        if facts["sample_entries"]:
            evidence.append(f"首批可见条目：{', '.join(f'`{item}`' for item in facts['sample_entries'][:6])}。")
    else:
        evidence.append(f"文件后缀：`{facts['suffix'] or '无后缀'}`。")
        evidence.append(f"所在目录：`{facts['parent_name'] or '.'}`。")
    if facts["readme_summary"]:
        evidence.append(f"同层 README 摘要：{facts['readme_summary']}")
    weak_hints = build_weak_path_hints(relative_path, target_path, facts)
    if weak_hints:
        evidence.append(f"弱提示：{'；'.join(weak_hints[:2])}")
    return evidence


def score_root_entry(entry: Path) -> int:
    facts = collect_path_facts(entry.name, entry)
    return estimate_path_evidence_richness(entry.name, entry, facts)
