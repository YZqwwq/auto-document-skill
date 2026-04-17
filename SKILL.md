---
name: auto-document
description: "面向主分支或即将合并到主分支环境的仓库文档工作流 skill。先由人校准项目级 summary，再由当前会话中的 Codex 按功能树而不是目录树手动推断并维护文档，脚本只负责准备证据、协议与状态。"
---

# 自动文档

初始化并维护一个面向软件仓库的分层文档系统。
这个 skill 不是“扫描代码后直接批量生成文档”的通用工具，而是一个带工作流约束的仓库文档协作系统：

- 先由人校准项目当前状态与未来方向
- 再由当前会话中的 Codex 按功能树而不是目录树手动推断并建立文档
- 在用户再次触发时，结合 git 变化对最小受影响功能模块进行谨慎维护

这里的脚本职责是准备证据包、推断协议、占位结构和状态记录，不负责在脚本内部自动完成语义判断。

## 适用前提

只有满足以下条件时，才应进入这套 skill 工作流：

- 目标仓库存在可用 git 环境
- 当前环境面向主分支，或即将合并到主分支的代码状态
- 当前不是多人同时并发维护同一套项目文档的高冲突场景
- 用户明确要求使用这个 skill

不满足以上条件时：

- 没有 git 时，不进入这套 skill 工作流
- 并发协作风险很高时，不默认改写这套文档系统
- 用户没有触发时，不做自动巡检或自动维护

## 核心理念

- 代码是当前实现真相
- 用户调整后的 `project-summary.md` 是项目意图基线
- 当前会话中的 Codex 可以协助判断用户是否已经完成确认，但不能跳过人工校准这个过程
- 功能树是真正的文档主骨架，代码树只是功能树在代码中的映射
- 文档应按功能拆解，而不是按目录自动拆解
- git 只负责判断文档与代码是否对齐，不负责替代人类确认项目方向
- 如果代码变化没有改变文档语义，就不应为了“代码变了”而强行重写文档
- 脚本只负责整理事实、生成协议和维护状态；功能域判断、summary 理解和维护层级判断由当前会话中的 Codex 完成

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

这里的文件和目录是工作流占位，不是不可变化的固定真相。
它们的职责应该稳定，但具体内容和下钻方式可以随着功能树、代码树和项目状态继续调整。

## 文档职责

- `overview/project-summary.md`
  项目级意图基线。优先回答“这个项目现在是什么、未来准备往哪里演进、哪些设计已经稳定、哪些仍在变化”。
- `overview/project-structure.md`
  功能树到代码树的映射工具。优先回答“某一层功能在代码中落在哪些路径和文件、应该从哪里进入代码阅读”。
- `modules/`
  功能域文档集合。优先回答“这个功能域解决什么问题、它在功能树中的位置是什么、关键入口在哪里、应如何继续下钻”。
- `index.json`
  文档系统控制面。记录阶段状态、功能域索引、git 对齐点和待处理更新项。

## 工作流

### 1. 初始化文档系统

在创建任何内容前，先检查 `project-docs/index.json` 是否已经存在。

- 如果存在且 `initialized` 为 `true`，复用已有文档根目录
- 如果不存在，初始化默认骨架并记录当前 git 对齐点

使用：

```bash
python -m scripts.features.bootstrap.init_project_docs --project-root <repo-root>
```

重要规则：

- 如果目标仓库没有可用 git 环境，则不应继续使用这套 skill
- 初始化生成的文件是占位骨架，不代表已经形成可信项目理解

### 2. 第一阶段：生成并校准项目 summary

这一阶段只生成 `overview/project-summary.md`，不生成正式 `modules/`。

目标：

- 基于当前代码、README 和关键入口文件，生成一份项目级 summary 草案
- 把当前会话中的 Codex 对项目当前状态的理解先写出来
- 明确哪些内容需要用户补充、修正和校准
- 让用户补上项目未来方向、设计理念和架构意图

使用：

```bash
python -m scripts.features.summary.draft_project_summary --project-root <repo-root>
```

重要规则：

- 这一阶段的目标不是让脚本自动定义项目最终真相，而是由当前会话中的 Codex 提供一份待用户校准的理解草案
- summary 写完后应立即停下，不继续生成正式功能树和模块文档
- 用户可以直接修改 `project-summary.md`，也可以通过对话要求 Codex 修订

### 3. 第二阶段：确认 summary 已可作为基线

只有当用户已经对 summary 做出足够校准后，后续结构分析和模块生成才有资格继续。

使用：

```bash
python -m scripts.features.summary.confirm_project_summary --project-root <repo-root>
```

确认语义：

- 用户直接修改了 `project-summary.md`
- 用户明确表示这份 summary 可以作为后续基线
- 用户要求继续进入下一阶段，且上下文已足以让当前会话中的 Codex 判断 summary 已被接受

重要规则：

- 这里是“人工校准 + Codex 协助判断”的确认语义，而不是严格审批流
- 当 `summary_state.status != confirmed` 时，不进入正式功能树建立，也不生成正式 `modules/`

### 4. 第三阶段：建立功能树与代码树映射

只有在 `project-summary.md` 已被用户确认后，才进入结构分析阶段。

目标：

- 先由脚本整理全仓证据、推断协议和占位结构，再由当前会话中的 Codex 识别项目的主要功能域
- 再按功能而不是按目录进行树级拆解
- 把这棵功能树逐层向下拆，直到落到已经不需要继续依赖下级功能解释的最小功能单元
- 为这棵功能树建立对应的代码树映射关系

使用：

```bash
python -m scripts.features.structure.scan_project_tree --project-root <repo-root>
```

重要规则：

- `project-structure.md` 的核心职责不是单纯解释技术栈目录语义，而是作为“功能树到代码树”的映射工具
- 功能树的最小粒度是最小功能单元，不是文件
- 代码树的最小粒度才是文件
- 脚本可以准备功能域推断协议和占位结果，但不应把占位结构写成“脚本已经完成语义判断”
- 如果顶层功能边界变化很大，优先重建功能树与代码树映射，再考虑下级模块文档

### 5. 第四阶段：生成功能域文档

只有在以下条件同时满足时，才生成正式 `modules/`：

- `summary_state.status = confirmed`
- `structure_state.status = aligned`

目标：

- 围绕功能域、职责边界、上下级关系、关键入口和阅读顺序生成模块文档
- 让模块文档按功能层级组织，而不是按目录层级组织
- 明确每个功能域在代码中落在哪些路径和文件

使用：

```bash
python -m scripts.features.module_docs.create_module_doc --project-root <repo-root> --target <domain-id-or-path>
```

重要规则：

- 模块文档不得只复述目录树
- 模块文档必须优先解释功能职责、上下级关系、代码入口和阅读顺序
- 模块文档的最小组织单位优先按功能域，而不是按路径或单文件
- 若 summary 与当前代码存在张力，应明确区分当前实现与长期方向

### 6. 第五阶段：进入人工触发的维护模式

当 summary 已确认、功能树已建立、modules 已生成后，文档系统进入维护模式。

维护不是自动巡检触发，而是在用户要求使用 skill 时触发。

使用：

```bash
python -m scripts.features.maintenance.plan_doc_updates --project-root <repo-root>
```

这个模式会：

- 读取 `git_state.aligned_head_sha`
- 对比当前 `HEAD` 与上次记录点
- 找出发生变化的文件
- 结合功能树、代码树和搜索工具定位最小受影响功能模块
- 判断应局部更新、向上收敛，还是仅更新 git 对齐点

维护规则：

- 先改最小受影响功能模块
- 如果影响已经扩散到多个兄弟节点，则向上层功能域收敛
- 如果新增或删除了文件，则功能树、代码树和相关文档都应同步调整
- 如果变化没有影响原有文档语义，则不重写正文，只更新 git 指向到最新
- 如果变化触及项目定位、核心设计理念或主要功能边界，则必须让用户复核

### 7. 第六阶段：大范围变化时的收敛

当项目发生大规模重构、路径迁移、功能域重划时，不要只做局部补丁，而要执行收敛。

使用：

```bash
python -m scripts.features.maintenance.reconcile_project_docs --project-root <repo-root>
```

推荐流程：

1. 先判断 summary 是否仍然成立
2. 如果 summary 已不成立：
   - 重新进入 `summary_pending_review`
   - 停止自动生成正式 modules
3. 如果 summary 仍成立：
   - 重建功能树与代码树映射
   - 再重建相关模块文档

大范围收敛后：

- 更新 `last_reconciled_at`
- 清空失效的 `pending_updates`
- 将 `git_state.aligned_head_sha` 对齐到当前 `HEAD`

### 8. 第七阶段：处理人工要求的功能分支调整

用户可能会要求：

- 删除某个功能分支
- 增加某个功能分支
- 保留一部分暂时与代码树不一致的功能文档

处理规则：

- 先确认该功能分支在功能层级中的位置是否合理
- 再理解它与现有代码树、功能树之间的关系
- 如果用户维护的功能分支与当前代码树不一致，不应直接覆盖用户意图，而应先询问该差异是否代表有效设计

## 写作指导

### summary

优先写清楚：

- 项目现在是什么
- 当前阶段最重要的目标是什么
- 项目未来准备往哪里演进
- 哪些设计原则已经稳定
- 哪些部分仍在变化

### structure

优先写清楚：

- 项目的主要功能域是什么
- 每一层功能在代码中落在哪些路径和文件
- 功能树和代码树分别承担什么角色
- 推荐从哪里进入代码阅读

### modules

优先写清楚：

- 功能域边界
- 在功能树中的位置
- 关键入口
- 与上下级功能的关系
- 当前实现真相
- 何时应更新本文件

## 资源说明

### `scripts/`

- `init_project_docs.py`
  初始化文档骨架和 `index.json`，并记录 git 基线。
- `draft_project_summary.py`
  生成项目级 summary 草案，并把系统推进到等待用户校准的状态。
- `confirm_project_summary.py`
  把已被用户接受的 summary 正式登记为后续功能树和模块文档的认知基线。
- `scan_project_tree.py`
  在 summary 已确认后准备功能树与代码树映射所需的证据、协议和占位结构。
- `create_module_doc.py`
  基于已确认 summary、功能域结果和证据上下文生成功能域文档。
- `plan_doc_updates.py`
  在用户触发时，利用 git 感知与证据摘要规划最小受影响功能模块的文档更新。
- `reconcile_project_docs.py`
  在大范围变化后重建证据协议、功能映射与相关模块文档，并同步索引状态。

### `references/`

- `document-architecture.md`
  文档系统的职责划分与分层原则。
- `document-writing.md`
  文档写作规范。
- `git-awareness.md`
  git 对齐点与增量维护规则。
- `index-schema.md`
  `index.json` 的字段定义与状态机说明。
- `update-workflow.md`
  日常维护与收敛时的更新规则。
- `codex-skill-boundary.md`
  明确这是 Codex 专用 skill，不承担脚本内 AI 调用。
