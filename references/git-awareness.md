# Git 感知机制

这份说明定义 `auto-document` 如何利用 git 判断“文档是否已经落后于代码”，以及这种判断如何与新的人工触发工作流协同工作。

## 当前定位下的基本原则

- git 是这套 skill 的前提条件之一，不是可有可无的优化项
- git 变化只是维护输入，不自动等于“文档必须改写”
- skill 只在用户要求使用时触发，不做后台自动巡检
- git 负责判断正文是否可能落后于代码，不负责替代人类确认项目意图
- 如果变化没有使文档语义失效，可以只更新 git 基线而不改正文

## 两类基线

### 1. summary 意图基线

保存在：

`index.json -> summary_state.baseline_head_sha`

它表示：

- 当前 `project-summary.md` 成为后续基线时，参考的是哪一个代码状态
- 后续如果项目定位、服务目标或核心设计理念变化，应重新校准 summary

### 2. 文档正文对齐基线

保存在：

`index.json -> git_state.aligned_head_sha`

它表示：

- 当前整套正文文档最近一次被确认与代码对齐到哪个 commit
- 后续判断“正文是否落后”时，应以这个 commit 作为比较基线

通常在功能树映射和相关模块文档收敛完成后更新。

## skill 触发时的判断顺序

1. 检查当前项目是否存在可用 git 工作区。
2. 如果没有 git：
   - 告知用户当前不进入这套 skill 工作流
   - 建议先安装或初始化 git
3. 如果存在 git：
   - 读取 `git_state.aligned_head_sha`
   - 读取当前 `HEAD`
   - 比较当前 `HEAD` 与对齐点的关系
   - 再结合工作区是否 dirty，整理本次变化输入
4. 变化输入整理完后，不立即改文档，而是先判断：
   - 是否只需更新 git 基线
   - 是否要改最小功能模块
   - 是否要向上收敛
   - 是否必须让用户复核

## 当前 HEAD 与对齐点的关系

### `same_head_clean`

- 当前 `HEAD` 和对齐点相同
- 工作区干净

处理：

- 不需要更新正文
- 也不需要更新 git 基线

### `same_head_dirty`

- 当前 `HEAD` 和对齐点相同
- 工作区存在未提交变化

处理：

- 以工作区变化文件作为输入
- 再判断这些变化是否真的使文档语义失效

### `current_ahead`

- 当前 `HEAD` 领先于文档对齐点

处理：

- 读取 `aligned_head_sha..HEAD` 的变更文件
- 叠加当前工作区未提交变化
- 再判断是否需要正文更新，不能直接把“有变化”当成“正文必须改”

### `current_behind`

- 当前 checkout 早于文档对齐点

处理：

- 默认不自动回写文档
- 明确提示“文档对齐点”和“当前 checkout”分别是什么
- 把 `workflow_phase` 记为 `hold`
- 如果用户要按当前 checkout 重建文档，再手动执行收敛

### `diverged`

- 当前 `HEAD` 与文档对齐点已经分叉

处理：

- 找共同祖先 `merge-base`
- 读取 `merge-base..HEAD` 的变化
- 评估变化文件数、顶层路径数、已登记功能域数以及是否触及关键根级文件
- 小范围变化可以继续判断是否局部更新
- 架构变化明显时建议直接收敛
- 如果变化触及项目定位或主要功能边界，优先要求用户复核

### `no_git`

- 当前项目没有可用 git

处理：

- 当前不进入这套 skill 工作流
- 不使用 git 增量判断

## 与状态机的协同规则

- 当 `summary_state.status != confirmed` 时：
  - 仍然可以刷新 `git_state.last_checked_*`
  - 但不进入正式模块级维护规划
- 当根级入口、关键配置或新顶层路径发生变化时：
  - 可能不仅要更新模块，还要把 `summary_state.status` 标记为 `stale`
- 当功能边界或代码映射关系变化时：
  - 可能把 `structure_state.status` 标记为 `stale`
- 当变化不影响正文语义时：
  - 可以不改正文，只更新 `git_state.aligned_*`
  - 并把模块层记录为 `git_alignment_only`
- 当 summary 被重新打开审查时：
  - 下游功能树映射与模块文档默认视为需要重新对齐

## 推荐工作流

### 先建立 summary 基线

```bash
python scripts/draft_project_summary.py --project-root <repo-root>
python scripts/confirm_project_summary.py --project-root <repo-root>
```

说明：

- 显式确认命令仍可保留
- 但 `confirmed` 不应只等同于执行过这条命令

### 再建立功能树映射与模块基线

```bash
python scripts/scan_project_tree.py --project-root <repo-root>
python scripts/reconcile_project_docs.py --project-root <repo-root>
```

### 日常维护判断

```bash
python scripts/plan_doc_updates.py --project-root <repo-root>
```

如果当前 checkout 早于文档基线，脚本应默认保持文档不动。  
如果当前分支与文档基线分叉，脚本应输出“建议局部更新”、“建议收敛”或“建议用户复核”。  
如果变化已经波及项目级定位，脚本应要求重新校准 summary。  
如果变化没有使正文语义失效，脚本应允许只更新 git 基线。

