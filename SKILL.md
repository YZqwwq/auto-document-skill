---
name: auto-document
description: "为软件仓库创建并维护分层项目文档。适用于 Codex 需要初始化可复用的 `project-docs` 目录、生成第一轮功能架构分析、创建按功能域组织的第二轮文档、维护机器可读的文档索引，或在代码变更后规划文档更新时。"
---

# 自动文档

初始化并维护一个面向项目的分层文档系统。把文档当成项目基础设施来建设：提供稳定入口，记录机器可读状态，从整体到细节分析仓库，并让文档持续和真实代码保持一致。

## 核心规则

- 当文档与代码冲突时，以代码作为运行时真相。
- 当 `project-docs/index.json` 已存在且 `initialized` 为 `true` 时，复用已有文档根目录。
- 每个项目默认只维护一个稳定的文档根目录，除非用户明确要求使用其他位置。
- 明确区分文档职责：
  - 总览文档负责从全局角度解释项目
  - 模块文档负责解释第一层功能域和第二层专题域
  - 历史文档负责记录分析和更新过程
  - `index.json` 负责保存供后续运行使用的机器可读状态
- 初始化完成后，优先做增量更新，而不是整套重写。
- 文档默认聚焦项目理念、运行时实现、模块边界和阅读入口；`package.json`、`tsconfig*`、构建与 lint 配置默认不进入主文档视野。

## 默认目录结构

除非仓库已经在使用其他文档根目录，否则创建并维护：

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

需要了解 `index.json` 各字段的精确定义时，读取 [references/index-schema.md](references/index-schema.md)。

## 工作流

### 1. 初始化文档系统

在创建任何内容前，先检查 `project-docs/index.json` 是否已经存在。

- 如果它存在且 `initialized` 为 `true`，不要重新创建默认骨架。
- 如果它不存在，使用下面的命令初始化文档根目录：

```bash
python scripts/init_project_docs.py --project-root <repo-root>
```

当你需要决定一个新仓库的文档应如何组织时，读取 [references/document-architecture.md](references/document-architecture.md)。

### 2. 执行第一轮分析

第一轮分析用于建立广义导航和功能架构上下文。

目标：

- 写出一份简要的项目用途说明
- 抓取顶层目录树和重要目录
- 找出最值得进入第二轮功能域分析的目标
- 默认忽略只服务于工具链的根级配置文件，减少文档审计范围

推荐顺序：

1. 检查仓库根目录和关键清单文件
2. 运行：

```bash
python scripts/scan_project_tree.py --project-root <repo-root>
```

3. 更新：
   - `project-docs/overview/project-summary.md`
   - `project-docs/overview/project-structure.md`
4. 向 `project-docs/history/analysis-log.md` 追加一条简短记录

生成的结构文档只是起点，不是最终真相。读过真实代码后再继续修正它。

### 3. 执行第二轮模块分析

第二轮分析不再直接镜像目录树，而是把实现路径重组成功能域。

从第一轮扫描结果中优先生成功能域，例如：

- 第一层：`交互与展示层`、`后端运行时层`、`共享契约与实体`
- 第二层：`AI 能力与代理主链`、`任务与子 Agent 编排`、`日志与可观测性`
- 任何更能回答“这一组路径共同解决什么问题”的功能域

收敛脚本会根据第一轮分析自动生成这批功能域文档。生成结果应补齐：

- 功能域覆盖哪些实现路径
- 这一功能域解决什么阅读问题
- 第一层与第二层如何继续下沉
- 关键入口、边界和阅读建议

更新 `project-docs/modules/README.md`，让它持续作为功能域导航页。

### 4. 在代码变更后规划增量更新

当代码发生变更时，除非影响了项目级架构，否则只更新受影响的文档。

使用：

```bash
python scripts/plan_doc_updates.py --project-root <repo-root> --changed <path> [--changed <path> ...]
```

如果你希望 skill 直接根据 `index.json` 记录的对齐 commit 与当前 git 状态自动判断是否需要更新，使用：

```bash
python scripts/plan_doc_updates.py --project-root <repo-root>
```

这个模式会：

- 读取 `git_state.aligned_head_sha`
- 对比当前 `HEAD`
- 判断当前代码是与文档对齐、领先、落后还是已经分叉
- 再决定是否规划文档更新

如果仓库已经使用 git 进行跟踪，也可以使用：

```bash
python scripts/plan_doc_updates.py --project-root <repo-root> --git-status
```

这个脚本会把待处理文档工作写入 `index.json`。它适合处理中小规模变更时的“先判断该改哪里”。

当你需要判断应更新总览文档、模块文档，还是两者都更新时，读取 [references/update-workflow.md](references/update-workflow.md)。
当你需要理解 git 对齐点、分支前后关系和无 git 时的回退策略，读取 [references/git-awareness.md](references/git-awareness.md)。

### 5. 在大范围调整后收敛到当前状态

当项目经历大规模重构、目录迁移、模块删除、架构审查后的统一改写时，不要只做局部补丁，而要把文档系统整体收敛到项目当前状态。

使用：

```bash
python scripts/reconcile_project_docs.py --project-root <repo-root>
```

这个脚本会：

- 重扫顶层结构并重写 `overview/project-structure.md`
- 重写当前功能域文档，并基于路径、目录结构和常见模块模式自动补写一版初始正文
- 删除已经失效的模块文档
- 更新 `modules/README.md`
- 清空 `index.json` 中已失效的 `pending_updates`
- 把 `index.json` 同步到当前项目状态

如果你希望本轮收敛只保留最新推荐的功能域目标，可以使用：

```bash
python scripts/reconcile_project_docs.py --project-root <repo-root> --use-recommended-only
```

如果你希望严格清理已经失效的旧文档与空目录，可以使用：

```bash
python scripts/reconcile_project_docs.py --project-root <repo-root> --use-recommended-only --prune-mode strict
```

如果你希望显式指定本轮要保留的功能域 ID，可以使用：

```bash
python scripts/reconcile_project_docs.py --project-root <repo-root> --target interaction-surface --target backend-runtime
```

## 写作指导

在编辑生成后的文档时：

- 先写目的和范围，再进入细节
- 把“当前真相”和“未来设想”明确分开
- 如果发生大范围架构变化，优先执行收敛脚本，再继续人工细化正文
- 总览文档是为了导航，不是为了堆满所有实现细节
- 模块文档应围绕功能域边界和职责来写，而不是逐文件复述
- 尽量写明具体路径，方便未来的 Codex 重新把文档和代码对上
- 需要设计一份更适合人和 AI 阅读的正文结构时，读取 [references/document-writing.md](references/document-writing.md)
- 技术栈可以轻量说明，例如 `Electron`、`Vue 3`，但不要让工程配置成为正文主体

## 资源说明

### `scripts/`

- `init_project_docs.py`
  初始化默认的 `project-docs/` 骨架并创建 `index.json`。
- `scan_project_tree.py`
  生成第一轮结构快照，并推荐第二轮功能域目标。
- `create_module_doc.py`
  提供功能域正文渲染能力，并自动补写一版初始正文。
- `plan_doc_updates.py`
  将代码变更映射到文档更新项，并记录待处理工作。
- `reconcile_project_docs.py`
  在大范围调整后，把结构文档、模块文档正文和索引收敛到当前项目状态。

### `references/`

- [references/document-architecture.md](references/document-architecture.md)
  从分层项目知识库中抽象出来的通用文档架构原则。
- [references/document-writing.md](references/document-writing.md)
  面向人和 AI 的项目文档分块写作规范。
- [references/git-awareness.md](references/git-awareness.md)
  文档系统如何利用 git 感知代码变化，以及无 git 时如何回退。
- [references/index-schema.md](references/index-schema.md)
  `project-docs/index.json` 的逐字段说明。
- [references/update-workflow.md](references/update-workflow.md)
  真实代码变更后如何做文档增量更新的规则。
