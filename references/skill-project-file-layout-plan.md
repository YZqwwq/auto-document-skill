# Skill 项目文件重排方案

这份文档描述的是：

- 这个 `auto-document-skill` 仓库自己的代码文件应该如何重新排布
- 哪些文件属于同一功能链
- 每个文件建议移动到哪里
- 哪些旧路径建议保留为兼容入口

这里不直接执行移动，只给出一份可操作的人工搬迁方案。

## 一、重排目标

当前仓库里已经有一定分层：

- `core/`
- `entrypoints/`
- `summary/`
- `analysis/`
- `generation/`
- `maintenance/`

但从“实现一个功能的文件应尽量靠近”的角度看，当前仍有两个问题：

1. 同一条功能链上的文件分散在多个目录里
2. 顶层兼容脚本、旧分层目录、真实实现文件混在一起，不利于审计

这次重排的目标是：

- 把“真正实现逻辑”按功能链归并到统一目录
- 把“跨流程复用能力”单独归到共享层
- 把旧路径保留成兼容壳，避免现有命令或引用立即失效

## 二、建议后的目录结构

建议把真实实现收敛到下面这套结构：

```text
scripts/
├── shared/
│   ├── git_tracking.py
│   ├── path_intelligence.py
│   └── workflow_state.py
├── features/
│   ├── bootstrap/
│   │   └── init_project_docs.py
│   ├── summary/
│   │   ├── draft_project_summary.py
│   │   └── confirm_project_summary.py
│   ├── structure/
│   │   ├── architecture_domains.py
│   │   └── scan_project_tree.py
│   ├── module_docs/
│   │   └── create_module_doc.py
│   └── maintenance/
│       ├── plan_doc_updates.py
│       └── reconcile_project_docs.py
├── architecture_domains.py
├── confirm_project_summary.py
├── create_module_doc.py
├── draft_project_summary.py
├── git_tracking.py
├── init_project_docs.py
├── plan_doc_updates.py
├── reconcile_project_docs.py
├── scan_project_tree.py
└── workflow_state.py
```

说明：

- `scripts/shared/` 放跨流程复用能力
- `scripts/features/` 按功能链放真实实现
- `scripts/*.py` 顶层脚本保留为兼容入口

如果希望进一步兼容旧 import，也可以临时保留这些目录，但里面只放转发壳：

- `scripts/core/`
- `scripts/entrypoints/`
- `scripts/summary/`
- `scripts/analysis/`
- `scripts/generation/`
- `scripts/maintenance/`

## 三、功能分类说明

### 1. 共享能力层 `scripts/shared/`

这层不是某个单独工作流阶段，而是多个功能链都会复用的基础能力。

- `git_tracking.py`
  负责 git 状态采集、变更范围分析、维护策略建议
- `path_intelligence.py`
  负责路径事实采集、弱提示生成、路径证据表达
- `workflow_state.py`
  负责状态机、阶段 gate、索引状态读写辅助

这三个文件建议放在一起，因为它们都不是“某一阶段的业务”，而是“所有阶段都可能依赖的共享能力”。

### 2. 初始化功能 `scripts/features/bootstrap/`

- `init_project_docs.py`

这是文档系统初始化入口，只负责：

- 创建骨架
- 初始化 `index.json`
- 写默认占位文档

它不属于 summary、structure、modules 或 maintenance 任一阶段，单独归到 `bootstrap/` 最清楚。

### 3. 项目级 summary 功能 `scripts/features/summary/`

- `draft_project_summary.py`
- `confirm_project_summary.py`

这两个文件属于同一条功能链：

- 一个负责生成 summary 草案
- 一个负责把 summary 登记成后续基线

它们应放在同一目录里，而不应分散到别的功能目录。

### 4. 功能树/结构映射功能 `scripts/features/structure/`

- `architecture_domains.py`
- `scan_project_tree.py`

这两个文件都在做“功能树与代码树映射”：

- `architecture_domains.py`
  从真实路径中提出功能域候选
- `scan_project_tree.py`
  建立结构文档，并把功能树映射到代码树

它们逻辑上属于同一结构分析能力，建议放在一起。

### 5. 功能域文档生成功能 `scripts/features/module_docs/`

- `create_module_doc.py`

这个文件本身承担的就是“围绕功能域生成模块文档”的功能，单独作为一类最直观。

后续如果这里继续拆，可以在这个目录下增加：

- `domain_analysis.py`
- `domain_rendering.py`
- `modules_readme.py`

但在当前规模下，先只保留一个 `create_module_doc.py` 就够了。

### 6. 文档维护功能 `scripts/features/maintenance/`

- `plan_doc_updates.py`
- `reconcile_project_docs.py`

这两个文件都属于“进入维护模式后怎么处理变化”：

- `plan_doc_updates.py`
  负责根据变化做维护规划
- `reconcile_project_docs.py`
  负责在大范围变化后重建和收敛

它们应放在同一目录中，作为维护功能链。

## 四、逐文件移动清单

下面是建议的“当前路径 -> 目标路径”清单。

### 真实实现文件

- `scripts/core/git_tracking.py`
  -> `scripts/shared/git_tracking.py`
- `scripts/core/path_intelligence.py`
  -> `scripts/shared/path_intelligence.py`
- `scripts/core/workflow_state.py`
  -> `scripts/shared/workflow_state.py`

- `scripts/entrypoints/init_project_docs.py`
  -> `scripts/features/bootstrap/init_project_docs.py`

- `scripts/summary/draft_project_summary.py`
  -> `scripts/features/summary/draft_project_summary.py`
- `scripts/summary/confirm_project_summary.py`
  -> `scripts/features/summary/confirm_project_summary.py`

- `scripts/analysis/architecture_domains.py`
  -> `scripts/features/structure/architecture_domains.py`
- `scripts/analysis/scan_project_tree.py`
  -> `scripts/features/structure/scan_project_tree.py`

- `scripts/generation/create_module_doc.py`
  -> `scripts/features/module_docs/create_module_doc.py`

- `scripts/maintenance/plan_doc_updates.py`
  -> `scripts/features/maintenance/plan_doc_updates.py`
- `scripts/maintenance/reconcile_project_docs.py`
  -> `scripts/features/maintenance/reconcile_project_docs.py`

### 顶层兼容入口

这些文件建议保留在原地，但只保留极薄的一层转发：

- `scripts/architecture_domains.py`
- `scripts/confirm_project_summary.py`
- `scripts/create_module_doc.py`
- `scripts/draft_project_summary.py`
- `scripts/git_tracking.py`
- `scripts/init_project_docs.py`
- `scripts/plan_doc_updates.py`
- `scripts/reconcile_project_docs.py`
- `scripts/scan_project_tree.py`
- `scripts/workflow_state.py`

建议它们做的事只有：

- 从新的目标模块 `import *`
- 如果有 `main()`，保留 `if __name__ == "__main__": raise SystemExit(main())`

### 旧包路径兼容壳

如果你想兼容旧 import 路径，建议这些文件也保留，但内容改成转发：

- `scripts/core/git_tracking.py`
  -> 转发到 `scripts/shared/git_tracking.py`
- `scripts/core/path_intelligence.py`
  -> 转发到 `scripts/shared/path_intelligence.py`
- `scripts/core/workflow_state.py`
  -> 转发到 `scripts/shared/workflow_state.py`

- `scripts/entrypoints/init_project_docs.py`
  -> 转发到 `scripts/features/bootstrap/init_project_docs.py`

- `scripts/summary/draft_project_summary.py`
  -> 转发到 `scripts/features/summary/draft_project_summary.py`
- `scripts/summary/confirm_project_summary.py`
  -> 转发到 `scripts/features/summary/confirm_project_summary.py`

- `scripts/analysis/architecture_domains.py`
  -> 转发到 `scripts/features/structure/architecture_domains.py`
- `scripts/analysis/scan_project_tree.py`
  -> 转发到 `scripts/features/structure/scan_project_tree.py`

- `scripts/generation/create_module_doc.py`
  -> 转发到 `scripts/features/module_docs/create_module_doc.py`

- `scripts/maintenance/plan_doc_updates.py`
  -> 转发到 `scripts/features/maintenance/plan_doc_updates.py`
- `scripts/maintenance/reconcile_project_docs.py`
  -> 转发到 `scripts/features/maintenance/reconcile_project_docs.py`

如果你不需要兼容旧 import，可以在统一改完所有引用后再删除这些壳文件。

## 五、建议的迁移顺序

为了降低风险，建议按下面顺序手动移动：

1. 先创建新目录：
   - `scripts/shared/`
   - `scripts/features/bootstrap/`
   - `scripts/features/summary/`
   - `scripts/features/structure/`
   - `scripts/features/module_docs/`
   - `scripts/features/maintenance/`

2. 先移动共享能力：
   - `git_tracking.py`
   - `path_intelligence.py`
   - `workflow_state.py`

3. 再移动功能实现：
   - `init_project_docs.py`
   - `draft_project_summary.py`
   - `confirm_project_summary.py`
   - `architecture_domains.py`
   - `scan_project_tree.py`
   - `create_module_doc.py`
   - `plan_doc_updates.py`
   - `reconcile_project_docs.py`

4. 更新真实实现之间的 import，让它们优先依赖新路径

5. 把旧位置文件改成兼容壳

6. 最后做一轮语法检查和命令回归

## 六、迁移完成后应满足的判断标准

如果重排成功，仓库应满足这些标准：

### 1. 看目录就能知道功能分组

新接手的人只看 `scripts/features/` 就能知道：

- 初始化在哪
- summary 在哪
- 结构分析在哪
- 模块文档生成在哪
- 维护逻辑在哪

### 2. 看共享目录就能知道公共能力

`scripts/shared/` 里不应出现明显的阶段业务脚本，只放：

- git 能力
- 路径能力
- 状态机能力

### 3. 顶层脚本只做兼容

`scripts/*.py` 顶层文件不应继续承载真实实现逻辑。
它们应只作为：

- CLI 兼容入口
- 旧调用路径兼容入口

### 4. 旧分层目录不再承载真实业务

如果保留：

- `core/`
- `entrypoints/`
- `summary/`
- `analysis/`
- `generation/`
- `maintenance/`

那么这些目录里应只剩兼容转发文件，而不应再是主实现落点。

## 七、配套建议

完成文件重排后，建议同步补这两件事：

1. 更新 `SKILL.md` 的资源说明  
把资源说明从“旧目录名”改成“新功能目录名”。

2. 新增或更新一份“skill 仓库自己的项目架构说明”  
建议说明：

- `shared` 是什么
- `features` 下每个子目录负责什么
- 顶层脚本为什么保留
- 旧目录为什么还存在

## 八、推荐的最终审计视角

重排完成后，审计这个 skill 仓库时，建议按下面 5 层看：

1. 产品与工作流定义
   - `SKILL.md`

2. 规范与协议
   - `references/`

3. 共享基础能力
   - `scripts/shared/`

4. 功能实现链
   - `scripts/features/`

5. 兼容入口层
   - `scripts/*.py`
   - 以及需要保留的旧目录转发壳

这会比当前“目录分层 + 兼容入口 + 旧历史结构混合”的状态更清晰。
