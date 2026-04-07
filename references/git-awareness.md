# Git 感知机制

这份说明定义 `auto-document` 如何利用 git 判断“文档是否已经落后于代码”。

## 核心目标

- 为 `project-docs/` 记录一个明确的对齐 commit。
- 在 skill 触发时，不只看当前工作区，还比较“文档对齐点”和“当前 HEAD”的关系。
- 当项目没有 git 时，明确退化为全量阅读/收敛工作流，而不是假装自己能做增量判断。

## 对齐点是什么

文档系统的对齐点保存在 `index.json -> git_state.aligned_head_sha`。

它表示：

- 当前 `project-docs/` 最近一次被确认对齐到哪个 commit
- 后续判断“文档是否落后”时，应以这个 commit 作为基线

通常在执行 `reconcile_project_docs.py` 成功后更新。

## skill 触发时的判断顺序

1. 检查当前项目是否存在可用 git 工作区。
2. 如果没有 git：
   - 告知用户当前无法进行 git 感知
   - 建议安装/初始化 git
   - 或者下沉到全量阅读项目，再执行 `reconcile_project_docs.py`
3. 如果存在 git：
   - 读取 `index.json` 中记录的 `aligned_head_sha`
   - 读取当前 `HEAD`
   - 比较当前 `HEAD` 与对齐点的关系
   - 再结合当前工作区是否 dirty，决定是否需要规划文档更新

## 当前 HEAD 与对齐点的关系

### `same_head_clean`

- 当前 `HEAD` 和对齐点相同
- 工作区干净

处理：

- 不需要更新文档

### `same_head_dirty`

- 当前 `HEAD` 和对齐点相同
- 工作区存在未提交变化

处理：

- 只根据工作区变化文件规划增量更新

### `current_ahead`

- 当前 `HEAD` 领先于文档对齐点

处理：

- 读取 `aligned_head_sha..HEAD` 的变更文件
- 再叠加当前工作区未提交变化
- 根据这些路径规划文档更新

### `current_behind`

- 当前 checkout 早于文档对齐点

处理：

- 默认不自动回写文档
- 明确提示“文档对齐点”和“当前 checkout”分别是什么
- 如果需要按当前 checkout 重建文档，再手动执行收敛
- 在 `git_state` 中把建议模式记为 `hold`

### `diverged`

- 当前 `HEAD` 与文档对齐点已经分叉

处理：

- 找共同祖先 `merge-base`
- 读取 `merge-base..HEAD` 的变化
- 评估变化文件数、顶层路径数、已登记模块数以及是否触及关键根级配置文件
- 小范围变化建议走增量更新
- 架构变化明显时，建议直接收敛
- 把建议模式写入 `git_state.recommended_update_mode`

### `no_git`

- 当前项目没有可用 git

处理：

- 告知需要 git 或下沉到全量阅读项目
- 不使用 git 增量判断

## 推荐工作流

### 先建立对齐点

```bash
python scripts/reconcile_project_docs.py --project-root <repo-root>
```

### 日常增量判断

```bash
python scripts/plan_doc_updates.py --project-root <repo-root>
```

不传额外参数时，脚本默认使用 git 感知模式。

如果当前 checkout 早于文档基线，脚本会默认保持文档不动。
如果当前分支与文档基线分叉，脚本会自动输出“建议增量”还是“建议收敛”。

### 没有 git 时

```bash
python scripts/reconcile_project_docs.py --project-root <repo-root>
```

这代表回退到“直接把文档系统同步到当前文件系统状态”的工作流。
