# 索引结构说明

`project-docs/index.json` 是让这个 skill 可重复运行的状态文件。

## 必填字段

- `skill_name`
  固定为 `auto-document`。
- `skill_version`
  初始化或更新文档时使用的 skill 逻辑版本。
- `doc_schema_version`
  `project-docs/` 目录布局和索引结构的版本。
- `project_root`
  仓库根目录的绝对路径。
- `doc_root`
  文档根目录的绝对路径。
- `initialized`
  布尔值，用于跳过默认骨架的重复初始化。
- `initialized_at`
  第一次成功初始化时的 ISO 时间戳。
- `last_scan_at`
  最近一次结构扫描的 ISO 时间戳。首次扫描前保持为 `null`。
- `last_reconciled_at`
  最近一次完成整体验证并收敛到当前状态的 ISO 时间戳。首次收敛前可以不存在或为 `null`。
- `analysis_round`
  `0` 表示尚未分析，`1` 表示已完成总览分析，`2` 表示已经存在第二轮模块文档。
- `generated_docs`
  已在 `project-docs/` 下生成的相对文档路径。
- `tracked_paths`
  当前被文档系统跟踪的重要项目相对路径。
- `round_two_targets`
  推荐进入第二轮功能域分析的目标 ID。
- `architecture_domains`
  当前推断出的功能架构域列表。每个功能域记录标题、层级、上级域、覆盖路径与文档路径。
- `module_docs`
  `功能域 ID -> 模块文档路径` 的映射。
- `pending_updates`
  代码变更后发现的待处理文档更新项列表。
- `history_files`
  这个系统使用的日志文件相对路径。
- `git_state`
  文档系统记录的 git 感知状态，包括当前是否可用、上次对齐到哪个 commit、最近一次检查时的工作区状态。

## `pending_updates` 推荐结构

在 `pending_updates` 内部使用如下结构：

```json
{
  "planned_at": "2026-04-04T10:00:00Z",
  "changed_path": "src/main/runtime/queue.ts",
  "docs": [
    "modules/src__main.md",
    "overview/project-summary.md"
  ],
  "reason": "匹配到已登记模块路径，并且可能影响运行时总览。"
}
```

## `git_state` 推荐结构

在 `git_state` 内部使用如下结构：

```json
{
  "mode": "git",
  "git_available": true,
  "repo_root": "/abs/repo",
  "aligned_branch": "master",
  "aligned_head_sha": "eb45779c0ea034688bb5f328d4a7054f06ec0bcb",
  "aligned_at": "2026-04-05T10:30:00Z",
  "last_checked_branch": "master",
  "last_checked_head_sha": "eb45779c0ea034688bb5f328d4a7054f06ec0bcb",
  "last_checked_at": "2026-04-05T10:35:00Z",
  "working_tree_dirty": true,
  "status_porcelain": [
    " M src/main/index.ts",
    "?? project-docs/"
  ],
  "last_relation": "same_head_dirty",
  "recommended_update_mode": "incremental",
  "recommended_reason": "变化仍集中在有限路径内，适合先走增量更新。",
  "scope_summary": "变化文件 3 个；顶层路径 1 个；已登记模块 1 个",
  "merge_base_sha": null
}
```

主要含义：

- `mode`
  当前文档系统使用 `git` 感知，还是只能依赖 `full_scan_only`。
- `aligned_branch`
  最近一次文档被确认对齐到的分支名。
- `aligned_head_sha`
  最近一次文档被确认对齐到的 commit SHA。
- `aligned_at`
  最近一次建立对齐点的时间。
- `last_checked_*`
  最近一次触发 skill 检查时看到的 git 状态。
- `last_relation`
  最近一次检查时，当前 HEAD 相对文档对齐点的关系。常见值有：
  `same_head_clean`、`same_head_dirty`、`current_ahead`、`current_behind`、`diverged`、`no_git`。
- `recommended_update_mode`
  最近一次 git 判断后，推荐采用的处理方式。常见值有：
  `incremental`、`reconcile`、`hold`。
- `recommended_reason`
  为什么给出这个建议。
- `scope_summary`
  最近一次比较得到的变化范围摘要，便于快速判断是否需要全量收敛。
- `merge_base_sha`
  如果当前分支与文档基线分叉，则记录最近一次比较得到的共同祖先 commit。

## 更新规则

- 每次结构扫描后更新 `last_scan_at`。
- 完成第一轮总览工作后，把 `analysis_round` 提升到 `1`。
- 一旦登记了至少一个模块文档，把 `analysis_round` 提升到 `2`。
- 对 `generated_docs` 做追加，而不是整体替换。
- 优先保持 `architecture_domains` 的功能域 ID 稳定，再围绕这些 ID 更新文档路径。
- 每次规划运行后，用最新结果替换 `pending_updates`。
- 每次执行收敛后，更新 `last_reconciled_at` 并清空 `pending_updates`。
- 每次执行收敛后，让 `generated_docs` 与当前实际仍有效的文档保持一致。
- 每次执行收敛后，如果检测到 git，则把当前 HEAD 写入 `git_state.aligned_head_sha`。
- 每次执行 git 感知规划后，更新 `git_state.last_checked_*` 与 `git_state.last_relation`。
- 每次执行 git 感知规划后，根据变化范围更新 `recommended_update_mode` 与 `recommended_reason`。
- 如果项目没有 git，`git_state.mode` 应保持为 `full_scan_only`，并提示使用全量阅读/收敛流程。

## 为什么这个文件重要

没有 `index.json`，后续运行就无法可靠判断：

- 默认骨架是否已经创建
- 哪些模块文档负责哪些路径
- 代码变更后还有哪些文档需要更新
- 文档当前到底对齐到了哪个 commit

把这个文件视为文档系统的控制面。
