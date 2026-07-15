# index.md 写法说明

`index.md` 是 auto-document 的 AI 可读阅读索引。

它不是机器状态文件，也不是完整项目理解。它只承担三件事：

- 记录最近一次 git 位置
- 用白话说明 AI 已经读了什么、判断了什么
- 写清楚下一步还要读什么

## 最小结构

初始化后应生成：

```md
# 项目文档索引

## 项目用途

见 `project-description.md`。

## 最近 git 记录

- git 可用：
- 仓库：
- 分支：
- 提交：
- 工作区：
- 记录时间：

## 当前阅读进度

已经完成：
- 已初始化文档工作区。

接下来：
- 浅层阅读项目，提出大功能模块并请求用户确认。

## 大功能模块

- 待确认

## 阅读记录

### 初始化

已经干了什么：
- 创建 `index.md`、`project-description.md` 和空的 `document/`。

还要干什么：
- 阅读项目入口，提出大功能模块。
```

## git 信息

`index.md` 可以用普通文本记录 git 信息。

如果需要保留原始 git 快照，可以放一个小的 fenced block：

```json
{
  "available": true,
  "branch": "master",
  "head_sha": "abcdef",
  "working_tree_dirty": false
}
```

这只是为了方便 AI 继续判断，不应扩展成完整机器状态机。

## 大功能模块

用户确认大功能模块后，在 `index.md` 的“大功能模块”区用白话列表记录：

```md
## 大功能模块

- 编辑模块：已确认，目录 `document/editor/catalog.md`
- AI Agent 模块：已确认，目录 `document/ai-agent/catalog.md`
- 文件系统模块：已确认，目录 `document/file-system/catalog.md`
```

不要在这里写复杂 JSON，不要记录多层状态字段。

## 阅读进度

阅读进度只写一层，不拆散到各个模块文件里。

推荐写法：

```md
## 阅读记录

### 2026-07-15 编辑模块 initial-scan

已经干了什么：
- 读了 `src/editor` 和 `src/ui/editor-panel`。
- 初步判断编辑模块可能包含文件加载、编辑状态、保存、渲染同步。

还要干什么：
- 继续确认保存能力属于编辑模块还是文件系统模块。
- 阅读编辑状态和渲染同步之间的调用链。

当前判断：
- `src/file` 可能是跨模块能力，不应直接归入编辑模块。
```

## catalog.md

`catalog.md` 只列子功能模块。

推荐写法：

```md
# 编辑模块

## 子功能模块

- 文件加载：`file-loading.md`
- 编辑状态：`edit-state.md`
- 渲染同步：`render-sync/catalog.md`
```

不要在 `catalog.md` 里写阅读任务、阅读日志、状态字段或长篇解释。
