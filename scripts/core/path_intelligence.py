#!/usr/bin/env python3
"""
通用路径证据工具。

这里不负责直接替 AI 下结论，
只负责把路径、文件和目录整理成更适合 prompt 判断的证据。
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
LOW_SEMANTIC_RISK_TOKENS = {
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
}
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


def is_low_semantic_risk_path(relative_path: str) -> bool:
    tokens = set(tokenize_path(relative_path))
    if tokens & LOW_SEMANTIC_RISK_TOKENS:
        return True
    lowered = normalize_relpath(relative_path).lower()
    return any(lowered.endswith(suffix) for suffix in (".test.ts", ".test.tsx", ".test.js", ".spec.ts", ".spec.tsx", ".spec.js", ".snap"))


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
    for candidate_name in ("README.md", "README.mdx", "readme.md"):
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


def summarize_path(relative_path: str, target_path: Path) -> str:
    clean = normalize_relpath(relative_path)
    title = infer_title_from_path(clean)
    if target_path.is_file():
        suffix = target_path.suffix.lower()
        if suffix in CODE_SUFFIXES:
            return f"`{title}` 当前更像一个需要结合上下文确认职责的代码证据点。"
        if suffix in TEXT_SUFFIXES:
            return f"`{title}` 当前更像一个帮助解释系统意图或局部设计的文本证据点。"
        if suffix in STRUCTURED_TEXT_SUFFIXES:
            return f"`{title}` 当前更像一个约束工具链、运行边界或结构参数的配置证据点。"
        return f"`{title}` 当前是一个需要结合上层语义判断职责的文件证据点。"
    dir_count, file_count = count_meaningful_children(target_path)
    if dir_count and file_count:
        return f"`{title}` 当前像一个同时承载子主题与实现文件的功能候选容器。"
    if dir_count:
        return f"`{title}` 当前像一个仍需继续下钻确认边界的主题候选目录。"
    if file_count:
        return f"`{title}` 当前像一个聚合实现或局部功能材料的候选目录。"
    return f"`{title}` 当前还缺少足够证据，暂时只能作为待确认的路径候选。"


def build_path_evidence(relative_path: str, target_path: Path) -> list[str]:
    clean = normalize_relpath(relative_path)
    evidence = [
        f"相对路径：`{clean}`。",
        f"路径类型：{'目录' if target_path.is_dir() else '文件'}。",
        f"路径深度：{max(1, len([part for part in clean.split('/') if part]))}。",
    ]
    if target_path.is_dir():
        dir_count, file_count = count_meaningful_children(target_path)
        evidence.append(f"可见有效子目录约 {dir_count} 个、有效文件约 {file_count} 个。")
        samples = collect_sample_entries(target_path)
        if samples:
            evidence.append(f"首批可见条目：{', '.join(f'`{item}`' for item in samples[:6])}。")
    else:
        suffix = target_path.suffix.lower() or "无后缀"
        evidence.append(f"文件后缀：`{suffix}`。")
        evidence.append(f"所在目录：`{target_path.parent.name or '.'}`。")
    readme_summary = collect_readme_summary(target_path)
    if readme_summary:
        evidence.append(f"同层 README 摘要：{readme_summary}")
    return evidence


def score_root_entry(entry: Path) -> int:
    score = 0
    if entry.is_dir():
        score += 40
        dir_count, file_count = count_meaningful_children(entry, max_scan=120)
        score += min(20, dir_count * 2)
        score += min(20, file_count)
        if collect_readme_summary(entry):
            score += 8
    else:
        suffix = entry.suffix.lower()
        if suffix in CODE_SUFFIXES:
            score += 25
        elif suffix in TEXT_SUFFIXES:
            score += 22
        elif suffix in STRUCTURED_TEXT_SUFFIXES:
            score += 18
        else:
            score += 6
    if is_root_context_signal_path(entry.name):
        score += 8
    return score

