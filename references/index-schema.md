# 索引结构说明

`project-docs/index.json` 是这个 skill 的机器可读状态文件。
在当前定位下，它的首要职责不是存放所有分析结果，而是承担两件事：

- 记录工作流是否可以继续推进
- 记录后续运行必须复用的基线

因此，这份索引应按两层理解：

- 最小核心字段
  负责工作流控制、人工校准基线和 git 对齐基线
- 分析缓存字段
  负责保存可复用但可再生成的分析结果、映射和待办规划

## 设计原则

- 顶层优先放“不能丢”的控制面，而不是“可以重算”的分析结果
- 能从现有文档或代码再次推导出的数据，不应优先占用顶层核心语义
- 一轮分析中的推荐目标、临时结果和局部缓存，不应被描述成核心状态
- `index.json` 首先是状态文件，其次才是分析缓存文件

## 一、最小核心字段

这些字段直接决定 skill 下次运行时能否继续、从哪里继续，以及当前文档是否仍有可信基线。
它们应被视为 `index.json` 的核心控制面。

### 顶层核心字段

- `skill_name`
  固定为 `auto-document`。
- `skill_version`
  当前写入索引时使用的 skill 逻辑版本。
- `doc_schema_version`
  当前 `project-docs/` 目录布局和索引结构版本。
- `project_root`
  仓库根目录绝对路径。
- `doc_root`
  文档根目录绝对路径。
- `initialized`
  是否已经完成基础骨架初始化。
- `initialized_at`
  第一次初始化成功的时间。
- `workflow_phase`
  当前文档系统所处的主阶段。

### 状态基线字段

- `summary_state`
  项目级 summary 的校准状态。
- `structure_state`
  功能树与代码树映射的状态。
- `module_state`
  功能域文档系统的状态。
- `git_state`
  当前文档系统记录的 git 基线、最近一次检查状态和推荐维护策略。

## `workflow_phase` 推荐值

当前实现仍保留旧阶段名以兼容脚本，但它们的语义已经更新：

- `initialized`
  基础骨架已创建，但尚未形成可信项目理解。
- `summary_pending_review`
  summary 草案已生成，等待用户补充、修正和校准。
- `summary_confirmed`
  summary 已被视为后续功能树分析基线，但功能树与代码树映射尚未建立。
- `structure_draft`
  AI 正在建立功能树与代码树映射。
- `structure_aligned`
  功能树与代码树映射已建立并与当前 summary 对齐。
- `modules_draft`
  AI 正在生成功能域文档。
- `maintenance`
  已进入人工触发的维护模式。
- `hold`
  当前 checkout 早于文档基线，默认暂停回写。
- `summary_reopen_required`
  项目级定位、核心设计理念或主要功能边界已变化，需要重新校准 summary。

说明：

- `structure_*` 这些名称是兼容旧实现保留的字段名。
- 在当前语义里，它代表的是“功能树 + 代码树映射”，不再只是目录结构快照。

## `summary_state` 推荐结构

```json
{
  "status": "pending_review",
  "doc_path": "overview/project-summary.md",
  "source": "ai_draft",
  "draft_generated_at": "2026-04-14T10:00:00Z",
  "confirmed_by": null,
  "confirmed_at": null,
  "confirmation_mode": null,
  "baseline_branch": "main",
  "baseline_head_sha": "abc123def456",
  "intent_lock": false,
  "requires_human_review": true,
  "notes": null
}
```

主要含义：

- `status`
  可选值：
  `missing`、`drafted`、`pending_review`、`confirmed`、`stale`
- `source`
  当前版本来源，例如 `ai_draft`、`user_rewrite`、`legacy_generated`
- `draft_generated_at`
  最近一次写出 summary 草案的时间
- `confirmed_by`
  最近一次将该 summary 视为基线的操作者标识
- `confirmed_at`
  最近一次确认时间
- `confirmation_mode`
  推荐值：
  `human_explicit`、`ai_assisted`、`legacy`
- `baseline_branch`
  summary 成为基线时所处的分支
- `baseline_head_sha`
  summary 成为基线时所对应的代码状态
- `intent_lock`
  是否已被视为后续功能树分析基线
- `requires_human_review`
  当前是否需要人工再次复核
- `notes`
  需要重新审查 summary 时记录原因

重要语义：

- `confirmed` 不必强绑定到某个显式命令
- 只要用户已对 summary 做出足够校准，AI 就可以把它视为可继续的基线

## `structure_state` 推荐结构

```json
{
  "status": "blocked_by_summary",
  "doc_path": "overview/project-structure.md",
  "generated_at": null,
  "aligned_branch": null,
  "aligned_head_sha": null,
  "based_on_summary_confirmed_at": null,
  "mapping_scope": "function_to_code",
  "tree_kind": "function_map",
  "requires_human_review": false,
  "notes": null
}
```

主要含义：

- `status`
  可选值：
  `missing`、`blocked_by_summary`、`drafted`、`aligned`、`stale`
- `mapping_scope`
  当前结构文档服务的映射类型，默认应为 `function_to_code`
- `tree_kind`
  当前树模型类型，默认应为 `function_map`
- `requires_human_review`
  当前功能树与代码树映射是否需要人工复核
- `notes`
  当前映射失效或待重建的原因

重要语义：

- `structure` 在当前项目里代表的是功能树与代码树映射状态
- 不是简单的目录树状态

## `module_state` 推荐结构

```json
{
  "status": "blocked_by_summary",
  "generated_at": null,
  "aligned_branch": null,
  "aligned_head_sha": null,
  "based_on_summary_confirmed_at": null,
  "based_on_structure_generated_at": null,
  "last_update_strategy": null,
  "git_alignment_only_pending": false,
  "requires_human_review": false,
  "notes": null
}
```

主要含义：

- `status`
  可选值：
  `missing`、`blocked_by_summary`、`blocked_by_structure`、`drafted`、`aligned`、`stale`
- `last_update_strategy`
  最近一次更新采用的策略，例如：
  `content_update`、`reconcile`、`git_alignment_only`
- `git_alignment_only_pending`
  当前是否只需要更新 git 基线，而不必改写正文
- `requires_human_review`
  当前功能域文档是否需要人工复核
- `notes`
  当前模块文档失效或待重建的原因

## `git_state` 推荐结构

```json
{
  "mode": "git",
  "git_available": true,
  "repo_root": "/abs/repo",
  "aligned_branch": "main",
  "aligned_head_sha": "eb45779c0ea034688bb5f328d4a7054f06ec0bcb",
  "aligned_at": "2026-04-14T10:35:00Z",
  "last_checked_branch": "main",
  "last_checked_head_sha": "eb45779c0ea034688bb5f328d4a7054f06ec0bcb",
  "last_checked_at": "2026-04-14T10:40:00Z",
  "working_tree_dirty": true,
  "status_porcelain": [
    " M src/main/index.ts"
  ],
  "last_relation": "same_head_dirty",
  "recommended_update_mode": "incremental",
  "recommended_reason": "变化仍集中在有限功能域内。",
  "scope_summary": "变化文件 3 个；顶层路径 1 个；已登记功能域 1 个",
  "scope_judgment_prompt": "请基于当前变化路径、变化广度、是否触及根级上下文证据、以及是否仍落在现有功能域映射内，判断这次维护应该走哪一种维护策略。",
  "merge_base_sha": null
}
```

主要含义：

- `aligned_head_sha`
  当前整套文档系统最近一次与代码正文对齐到的 commit
- `last_checked_*`
  最近一次触发 skill 时看到的 git 状态
- `last_relation`
  当前 `HEAD` 相对文档对齐点的关系
- `recommended_update_mode`
  最近一次判断后推荐采用的维护方式，例如：
  `incremental`、`reconcile`、`hold`、`git_alignment_only`
- `scope_judgment_prompt`
  最近一次范围判断时写入的判断提示，用于说明这轮维护为什么需要复核、上卷或局部更新

## 二、分析缓存字段

这些字段有价值，但不属于“最小核心字段”。
它们主要服务于复用分析结果、减少重复扫描、保存维护规划。
即使丢失，理论上也可以通过再次扫描代码和文档重新生成。

### 推荐保留的缓存字段

- `generated_docs`
  当前已写出的文档路径集合。
- `architecture_domains`
  当前推断出的功能域及其层级信息。
- `module_docs`
  `功能域 ID -> 模块文档路径` 的映射。兼容旧数据时，也可能仍存在少量 `路径 -> 文档路径` 记录。
- `domain_analysis`
  按功能域 ID 保存的结构化分析结果。
- `summary_analysis`
  按项目级 summary 保存的结构化证据包、判断提示和草案缓存。
- `tracked_paths`
  当前功能树与代码树映射所覆盖的重要路径集合。
- `pending_updates`
  用户触发维护后规划出的待处理文档更新项。
- `history_files`
  日志文件相对路径集合。

### 兼容字段

- `last_scan_at`
  最近一次建立功能树与代码树映射的时间。
- `last_reconciled_at`
  最近一次完成整体收敛的时间。
- `analysis_round`
  兼容旧实现保留的粗粒度阶段编号。
- `round_two_targets`
  旧工作流遗留的推荐目标字段。当前定位下不再建议把它视为核心字段，可逐步淘汰或迁移到更明确的分析缓存结构中。

## `pending_updates` 推荐结构

```json
{
  "planned_at": "2026-04-14T10:30:00Z",
  "changed_path": "main/services/queue/index.ts",
  "changed_paths": [
    "main/services/queue/index.ts"
  ],
  "docs": [
    "modules/backend-runtime/README.md"
  ],
  "reason": "变化触及现有功能域中的入口或边界文件，建议最小范围更新对应功能域文档。最小受影响功能域为 `运行编排与后台服务`。",
  "update_strategy": "content_update",
  "scope_level": "module",
  "requires_human_review": false,
  "impacted_domain_ids": [
    "backend-runtime"
  ],
  "impacted_domain_titles": [
    "运行编排与后台服务"
  ],
  "evidence_summary": [
    "本轮实际变化路径包括 `main/services/queue/index.ts`。",
    "变化已覆盖 1 个顶层路径：`main`。",
    "当前变化已命中已有功能域映射：`运行编排与后台服务`。"
  ],
  "judgment_prompt": "请基于当前变化路径、变化广度、是否触及根级上下文证据、以及是否仍落在现有功能域映射内，判断这次维护应该走 `git_alignment_only`、`content_update`、`reconcile` 还是 `user_review_required`。",
  "scope_snapshot": {
    "changed_paths_count": 1,
    "top_level_paths": [
      "main"
    ],
    "impacted_modules": [
      "backend-runtime"
    ],
    "new_top_levels": [],
    "critical_root_files": [],
    "uncovered_paths": [],
    "boundary_sensitive_paths": [
      "main/services/queue/index.ts"
    ],
    "low_semantic_risk_paths": []
  }
}
```

字段说明：

- `changed_path`
  兼容旧数据保留的单路径字段；当一次计划只对应一个变更路径时写入，否则可为 `null`。
- `changed_paths`
  本次计划所依据的完整变化路径集合。
- `docs`
  当前计划直接指向的文档集合。  
  当策略是模块级更新时，通常只包含最小受影响功能域文档；当策略上卷到结构层或 summary 层时，这里会改为对应的上层文档。
- `reason`
  当前策略判断依据，应能回答“为什么不是更小”或“为什么需要上卷/人工复核”。
- `update_strategy`
  当前计划的维护策略。
- `scope_level`
  当前计划主要作用于哪一层。推荐值：
  `git`、`module`、`structure`、`summary`
- `requires_human_review`
  当前计划是否要求人工先复核，再继续正文维护。
- `impacted_domain_ids`
  当前判断命中的功能域 ID 列表。
- `impacted_domain_titles`
  对应的人类可读功能域名称列表。
- `evidence_summary`
  当前计划保留下来的证据摘要，帮助后续维护理解“为什么得到这个计划”。
- `judgment_prompt`
  当前计划对应的判断提示，用来明确 AI 应如何基于证据复核本次维护层级。
- `scope_snapshot`
  当前变更范围的结构化快照，属于可复用分析缓存，不应被视为新的核心状态字段。

推荐的 `update_strategy` 取值：

- `content_update`
  需要实际改写正文
- `reconcile`
  需要向上收敛或整体重建
- `git_alignment_only`
  仅更新 git 基线，不需要改正文
- `user_review_required`
  需要用户先复核

重要语义补充：

- `pending_updates` 保存的是“仍待执行的正文维护计划”。
- 如果本轮变化被判定为 `git_alignment_only`：
  - 通常不会把结果保留在 `pending_updates`
  - 会直接清空 `pending_updates`
  - 通过 `module_state.last_update_strategy = git_alignment_only`、`git_state.aligned_*` 和 `history/change-log.md` 体现这次维护已经完成
- 如果本轮变化被判定为 `user_review_required`：
  - `pending_updates` 应直接收敛为 summary 或 structure 层的上卷计划
  - 不应继续保留一组看似可直接执行的模块级正文待办

## `summary_state.baseline_head_sha` 与 `git_state.aligned_head_sha` 的区别

- `summary_state.baseline_head_sha`
  表示项目意图基线对应的是哪个代码状态
- `git_state.aligned_head_sha`
  表示整套文档系统最近一次与代码正文完全对齐到哪个 commit

两者不要混用：

- 前者服务于“项目意图是否仍成立”
- 后者服务于“文档正文是否落后于代码”

## 更新规则

- 初始化时创建最小核心字段
- 初始化写出的占位文件，不应仅凭 `generated_docs` 被自动视为“summary 已生成草案”
- 每次生成 summary 草案后：
  - 把 `summary_state.status` 设为 `pending_review`
  - 记录 `draft_generated_at`
  - 把 `requires_human_review` 设为 `true`
  - 刷新 `summary_analysis`，把项目级证据包和判断提示缓存下来
- 每次把 summary 视为可继续基线后：
  - 把 `summary_state.status` 设为 `confirmed`
  - 记录 `confirmed_at`、`baseline_branch`、`baseline_head_sha`
  - 把 `confirmation_mode` 设为 `human_explicit` 或 `ai_assisted`
- 每次建立功能树与代码树映射后：
  - 更新 `structure_state`
  - 视需要刷新分析缓存字段，例如 `architecture_domains`、`tracked_paths`
- 每次生成功能域文档后：
  - 更新 `module_state`
  - 视需要刷新分析缓存字段，例如 `module_docs`、`generated_docs`
- 每次维护时：
  - 先判断是否需要正文改写
  - 如果不需要正文改写，只更新 git 基线，并把 `last_update_strategy` 记为 `git_alignment_only`
  - 如果需要模块级更新，把 `pending_updates` 写成最小受影响功能域计划
  - 如果需要上卷到结构层或 summary 层，把 `pending_updates` 写成上卷后的单层计划，而不是简单堆叠所有可能受影响文档
- 当项目定位、核心设计理念或主要功能边界变化时：
  - 把 `summary_state.status` 设为 `stale`
  - 默认让下游 `structure_state` 和 `module_state` 进入 `stale`

## 建议的长期结构方向

如果后续继续精简 `index.json`，建议逐步把缓存结果收敛到单独的分析区块中，例如：

```json
{
  "analysis": {
    "generated_docs": [],
    "architecture_domains": [],
    "module_docs": {},
    "domain_analysis": {},
    "summary_analysis": {},
    "tracked_paths": [],
    "pending_updates": []
  }
}
```

当前阶段为了兼容现有脚本，可以先保留这些字段在顶层。
但语义上应明确：

- 它们是分析缓存字段
- 不是最小核心字段
