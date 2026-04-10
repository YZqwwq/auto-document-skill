# 索引结构说明

`project-docs/index.json` 是让这个 skill 可重复运行的状态文件。

在新工作流中，这个文件不再只记录“已经生成了哪些文档”，而是同时承担：

- 工作流状态机
- 人类确认过的项目意图基线
- 结构责任树与功能域索引
- git 对齐状态

## 顶层必填字段

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
  最近一次完成整体验证并收敛到当前状态的 ISO 时间戳。
- `workflow_phase`
  当前文档系统所处的主阶段。
- `analysis_round`
  与旧版本兼容的粗粒度分析轮次。
- `summary_state`
  项目级 summary 的确认状态。
- `structure_state`
  结构责任树的建立状态。
- `module_state`
  模块文档系统的生成状态。
- `generated_docs`
  已在 `project-docs/` 下生成的相对文档路径。
- `tracked_paths`
  当前被文档系统跟踪的重要项目相对路径。
- `round_two_targets`
  推荐进入模块分析的功能域目标 ID。
- `architecture_domains`
  当前推断出的功能架构域列表。
- `module_docs`
  `功能域 ID -> 模块文档路径` 的映射。
- `domain_analysis`
  按功能域 ID 保存的结构化分析结果。
- `pending_updates`
  代码变更后发现的待处理文档更新项列表。
- `history_files`
  这个系统使用的日志文件相对路径。
- `git_state`
  文档系统记录的 git 感知状态，包括当前是否可用、上次对齐到哪个 commit、最近一次检查时的工作区状态。

## `workflow_phase` 推荐值

- `initialized`
  骨架已创建，但尚未生成 summary 草案。
- `summary_draft`
  AI 正在生成或准备生成 summary 草案。
- `summary_pending_review`
  summary 草案已写完，等待用户确认。
- `summary_confirmed`
  summary 已确认，但 structure 尚未建立。
- `structure_draft`
  AI 正在建立结构责任树。
- `structure_aligned`
  structure 已建立并与当前 summary 对齐。
- `modules_draft`
  AI 正在生成模块文档。
- `modules_aligned`
  modules 已生成完成。
- `maintenance`
  已进入日常维护模式。
- `hold`
  当前 checkout 早于文档基线，默认暂停自动回写。
- `summary_reopen_required`
  项目级定位或核心设计判断已变化，需要重新确认 summary。

## `analysis_round` 兼容定义

- `0`
  仅初始化。
- `1`
  summary 已生成或确认。
- `2`
  structure 与责任树已建立。
- `3`
  modules 已生成并进入维护。

真正的流程控制以 `workflow_phase` 和子状态字段为准。

## `summary_state` 推荐结构

```json
{
  "status": "pending_review",
  "doc_path": "overview/project-summary.md",
  "source": "ai_draft",
  "confirmed_by": null,
  "confirmed_at": null,
  "baseline_branch": "main",
  "baseline_head_sha": "abc123def456",
  "intent_lock": false,
  "notes": null
}
```

主要含义：

- `status`
  可选值：
  `missing`、`drafted`、`pending_review`、`confirmed`、`stale`
- `source`
  当前版本的来源，例如 `ai_draft`、`user_rewrite`、`legacy_generated`
- `confirmed_by`
  最近一次确认该 summary 的身份标识
- `confirmed_at`
  最近一次确认时间
- `baseline_branch`
  确认 summary 时所处的分支
- `baseline_head_sha`
  确认 summary 时所见的代码基线
- `intent_lock`
  是否已被视为后续 structure 和 modules 的项目意图基线
- `notes`
  需要重新审查 summary 时，可在这里记录原因

## `structure_state` 推荐结构

```json
{
  "status": "blocked_by_summary",
  "doc_path": "overview/project-structure.md",
  "generated_at": null,
  "aligned_branch": null,
  "aligned_head_sha": null,
  "based_on_summary_confirmed_at": null
}
```

主要含义：

- `status`
  可选值：
  `missing`、`blocked_by_summary`、`drafted`、`aligned`、`stale`
- `generated_at`
  最近一次建立 structure 的时间
- `aligned_*`
  最近一次建立 structure 时对应的 git 位置
- `based_on_summary_confirmed_at`
  这份 structure 对应的是哪次 summary 确认结果

## `module_state` 推荐结构

```json
{
  "status": "blocked_by_summary",
  "generated_at": null,
  "aligned_branch": null,
  "aligned_head_sha": null,
  "based_on_summary_confirmed_at": null,
  "based_on_structure_generated_at": null
}
```

主要含义：

- `status`
  可选值：
  `missing`、`blocked_by_summary`、`blocked_by_structure`、`drafted`、`aligned`、`stale`
- `generated_at`
  最近一次生成 modules 的时间
- `aligned_*`
  最近一次生成 modules 时对应的 git 位置
- `based_on_summary_confirmed_at`
  这批 modules 基于哪次 summary 确认生成
- `based_on_structure_generated_at`
  这批 modules 基于哪次 structure 生成

## `pending_updates` 推荐结构

```json
{
  "planned_at": "2026-04-04T10:00:00Z",
  "changed_path": "src/main/runtime/queue.ts",
  "docs": [
    "modules/backend-runtime/ai-runtime/runtime-orchestration.md",
    "overview/project-structure.md"
  ],
  "reason": "匹配到已登记模块路径，并且当前结构责任树需要复查。"
}
```

## `git_state` 推荐结构

```json
{
  "mode": "git",
  "git_available": true,
  "repo_root": "/abs/repo",
  "aligned_branch": "main",
  "aligned_head_sha": "eb45779c0ea034688bb5f328d4a7054f06ec0bcb",
  "aligned_at": "2026-04-05T10:30:00Z",
  "last_checked_branch": "main",
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
  "scope_summary": "变化文件 3 个；顶层路径 1 个；已登记功能域 1 个",
  "merge_base_sha": null
}
```

主要含义：

- `aligned_head_sha`
  最近一次整套文档系统被确认与代码对齐到的 commit。
- `last_checked_*`
  最近一次触发 skill 检查时看到的 git 状态。
- `last_relation`
  当前 `HEAD` 相对文档对齐点的关系。常见值有：
  `same_head_clean`、`same_head_dirty`、`current_ahead`、`current_behind`、`diverged`、`no_git`
- `recommended_update_mode`
  最近一次 git 判断后，推荐采用的处理方式。常见值有：
  `incremental`、`reconcile`、`hold`

## `summary_state.baseline_head_sha` 与 `git_state.aligned_head_sha` 的区别

- `summary_state.baseline_head_sha`
  表示用户确认项目意图时所参考的代码基线。
- `git_state.aligned_head_sha`
  表示整个文档系统最近一次与代码完全对齐到哪个 commit。

两者不要混用：

- 前者服务于“项目意图确认”
- 后者服务于“文档系统是否落后于代码”的 git 感知判断

## 更新规则

- 初始化时创建 `workflow_phase`、`summary_state`、`structure_state`、`module_state`。
- 每次生成 summary 草案后：
  - 把 `summary_state.status` 设为 `pending_review`
  - 把 `workflow_phase` 设为 `summary_pending_review`
- 每次用户确认 summary 后：
  - 把 `summary_state.status` 设为 `confirmed`
  - 记录 `confirmed_at`、`baseline_branch`、`baseline_head_sha`
- 每次结构扫描完成后：
  - 更新 `last_scan_at`
  - 更新 `tracked_paths`、`architecture_domains`、`round_two_targets`
  - 把 `structure_state.status` 设为 `aligned`
- 每次模块生成完成后：
  - 更新 `module_docs`、`domain_analysis`
  - 把 `module_state.status` 设为 `aligned`
- 每次执行收敛后：
  - 更新 `last_reconciled_at`
  - 清空 `pending_updates`
  - 如果检测到 git，则把当前 `HEAD` 写入 `git_state.aligned_head_sha`
- 每次执行 git 感知规划后：
  - 更新 `git_state.last_checked_*` 与 `git_state.last_relation`
  - 根据变化范围更新 `recommended_update_mode` 与 `recommended_reason`
- 如果检测到项目级定位、服务目标或核心架构理念变化：
  - 把 `summary_state.status` 设为 `stale`
  - 下游 `structure_state` 和 `module_state` 默认进入 `stale`

## 为什么这个文件重要

没有 `index.json`，后续运行就无法可靠判断：

- summary 是否已经被用户确认
- structure 是否已经建立
- modules 是否允许生成
- 代码变更后应该先更新模块、structure，还是重新打开 summary 审查
- 当前整套文档系统到底对齐到了哪个 commit

把这个文件视为文档系统的控制面。
