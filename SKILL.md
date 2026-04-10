---
name: auto-document
description: "为软件仓库创建并维护分层项目文档。先由 AI 生成并由用户确认项目级 summary，再基于技术栈与真实代码建立结构责任树，最后生成模块文档，并在代码变更后利用 git 感知进行增量维护。"
---

# 自动文档

初始化并维护一个面向项目的分层文档系统。这个 skill 不再把“第一次扫描代码后直接生成 modules”作为默认工作流，而是先建立一份由人类确认过的项目级 summary，把它作为后续结构分析和模块文档生成的认知基线。

## 核心理念

- 代码是当前运行时真相。
- 用户确认过的 `project-summary.md` 是项目意图真相。
- 模块文档必须同时服从：
  - 当前代码事实
  - 已确认的项目 summary
- 在 summary 未确认前，不自动生成 `modules/` 主体内容。
- `project-structure.md` 负责解释：
  - 这个项目使用了什么技术栈
  - 默认框架目录意味着什么
  - 项目自己在这些目录之上叠加了什么责任树
- `modules/` 只在 `summary + structure` 都已经建立后生成。
- git 感知仍然保留，但 git 只负责判断文档是否落后于代码，不负责替代人类确认项目意图。

## 默认目录结构

除非仓库已经使用其他文档根目录，否则创建并维护：

```text
project-docs/
├── index.json
├── README.md
├── overview/
│   ├── project-summary.md
│   └── project-structure.md
├── modules/
│   └── README.md
└── history/
    ├── analysis-log.md
    └── change-log.md
```

## 文档职责

- `overview/project-summary.md`
  项目级意图基线。优先回答“这个项目是什么、服务谁、当前阶段目标是什么、技术栈和长期设计方向是什么”。
- `overview/project-structure.md`
  结构责任树。优先回答“技术栈默认排布是什么、项目当前真实目录如何映射到功能责任树、哪些路径值得继续下钻”。
- `modules/`
  功能域文档。只在 summary 已确认、structure 已建立后生成，负责从浅入深解释功能域边界、关键入口和阅读路径。
- `index.json`
  文档系统控制面。记录阶段状态、已确认的人类基线、功能域索引、git 对齐点和待处理更新项。

## 工作流

### 1. 初始化文档系统

在创建任何内容前，先检查 `project-docs/index.json` 是否已经存在。

- 如果存在且 `initialized` 为 `true`，复用已有文档根目录。
- 如果不存在，初始化默认骨架：

```bash
python scripts/init_project_docs.py --project-root <repo-root>
```

初始化后，文档系统进入 `initialized` 阶段。

### 2. 第一阶段：生成并确认项目 summary

这一阶段只生成 `overview/project-summary.md`，不生成 `modules/`。

目标：

- 基于当前代码、README 和关键入口文件，生成一份项目级 summary 草案。
- 把项目的当前状态和预期方向明确区分。
- 明确技术栈、服务目标、架构理念和当前稳定边界。
- 写完后立即停止，让用户审阅或重写这份 summary。

使用：

```bash
python scripts/draft_project_summary.py --project-root <repo-root>
```

summary 草案写完后，skill 必须停下来，不继续生成 `project-structure.md` 和 `modules/`。

当用户确认这份 summary 后，使用：

```bash
python scripts/confirm_project_summary.py --project-root <repo-root>
```

重要规则：

- 当 `summary_state.status != confirmed` 时，不进入 `project-structure.md` 的正式责任树建立，也不生成 `modules/`。
- 这一阶段的 AI 目标不是定义项目最终真相，而是提供一份待用户确认的理解草案。
- 用户可以直接修改 `project-summary.md`，也可以告诉 AI 如何修订；最终以用户确认版本为准。

### 3. 第二阶段：建立结构责任树

只有在 `project-summary.md` 已被用户确认后，才进入结构分析阶段。

目标：

- 先识别技术栈默认目录语义。
- 再识别项目在默认目录之上叠加的功能责任。
- 最终在 `project-structure.md` 中建立“路径 -> 功能责任 -> 推荐阅读入口”的结构树。

使用：

```bash
python scripts/scan_project_tree.py --project-root <repo-root>
```

重要规则：

- 结构文档必须以已确认 summary 为认知基线。
- 结构文档不只是目录树快照，而要明确解释：
  - 默认框架排布意味着什么
  - 项目自定义模块为什么落在这些路径
- 如果顶层结构变化很大，优先重建 structure，再考虑 modules。

### 4. 第三阶段：生成 modules

只有在以下条件同时满足时，才生成 `modules/`：

- `summary_state.status = confirmed`
- `structure_state.status = aligned`

目标：

- 结合 summary 和 structure，从浅入深生成功能域文档。
- 让每份模块文档回答：
  - 这个功能域解决什么问题
  - 为什么这组路径应被一起理解
  - 关键入口在哪里
  - 运行时边界在哪里
  - 应先读哪里，再读哪里

使用：

```bash
python scripts/create_module_doc.py --project-root <repo-root> --target <domain-id-or-path>
```

重要规则：

- 模块文档不得只复述目录树。
- 模块文档必须优先解释职责、边界、入口和阅读顺序。
- 若 summary 与当前代码存在张力，应明确区分：
  - 当前实现
  - 长期目标
- 未确认的项目意图不得被 AI 擅自固化为稳定模块边界。

### 5. 第四阶段：进入维护模式

当 summary 已确认、structure 已建立、modules 已生成后，文档系统进入维护模式。

默认采用 git 感知的增量维护：

```bash
python scripts/plan_doc_updates.py --project-root <repo-root>
```

这个模式会：

- 读取 `git_state.aligned_head_sha`
- 对比当前 `HEAD`
- 判断是 `same_head_clean`、`same_head_dirty`、`current_ahead`、`current_behind` 还是 `diverged`
- 再决定推荐：
  - `incremental`
  - `reconcile`
  - `hold`

维护规则：

- 代码局部变化：
  优先更新受影响的模块文档。
- 顶层结构变化：
  优先更新 `project-structure.md`。
- 项目定位、服务目标、核心架构理念变化：
  必须回到 `project-summary.md`，并重新要求用户确认。
- 如果 summary 被重新打开审查，则下游 structure 和 modules 默认进入 `stale` 状态。

### 6. 大范围变化时的收敛

当项目发生大规模重构、路径迁移、功能域重划时，不要只做局部补丁，而要执行收敛。

使用：

```bash
python scripts/reconcile_project_docs.py --project-root <repo-root>
```

推荐流程：

1. 先判断 summary 是否仍然成立。
2. 如果 summary 已不成立：
   - 重新进入 `summary_pending_review`
   - 停止自动生成 modules
3. 如果 summary 仍成立：
   - 重建 structure
   - 再重建 modules

大范围收敛后：

- 更新 `last_reconciled_at`
- 清空失效的 `pending_updates`
- 将 `git_state.aligned_head_sha` 对齐到当前 `HEAD`

## 写作指导

### summary

优先写清楚：

- 项目是什么
- 当前阶段目标是什么
- 目标用户或使用场景是什么
- 技术栈与运行形态是什么
- 哪些设计原则已经稳定
- 哪些部分仍在演进

### structure

优先写清楚：

- 技术栈默认目录排布
- 项目如何在这些目录上叠加功能责任
- 哪些路径负责框架壳层
- 哪些路径负责项目核心能力
- 推荐从哪里开始阅读

### modules

优先写清楚：

- 功能域边界
- 关键入口
- 与相邻模块的关系
- 当前实现真相
- 何时应更新本文件

## 资源说明

### `scripts/`

- `init_project_docs.py`
  初始化文档骨架和 `index.json`。
- `draft_project_summary.py`
  生成项目级 summary 草案，并把系统推进到等待用户确认的状态。
- `confirm_project_summary.py`
  把用户确认的 summary 正式登记为后续 structure 和 modules 的认知基线。
- `scan_project_tree.py`
  在 summary 已确认后建立结构责任树。
- `create_module_doc.py`
  基于 summary 与 structure 生成功能域文档。
- `plan_doc_updates.py`
  利用 git 感知规划文档增量更新。
- `reconcile_project_docs.py`
  在大范围变化后重建 structure 与 modules，并同步索引状态。

### `references/`

- `document-architecture.md`
  文档系统的职责划分与分层原则。
- `document-writing.md`
  面向人和 AI 的文档写作规范。
- `git-awareness.md`
  git 对齐点与增量维护规则。
- `index-schema.md`
  `index.json` 的字段定义与状态机说明。
- `update-workflow.md`
  日常维护与收敛时的更新规则。
