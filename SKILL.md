---
name: auto-document
description: "Initialize and maintain a lightweight AI-readable project documentation workspace. It asks for a short project purpose, records the latest git point in index.md, and guides agents to read by confirmed functional modules instead of templates."
version: "1.0.0"
user-invocable: true
---

# auto-document

`auto-document` 是一个项目文档初始化与维护 skill。

它的作用不是自动扫描代码并批量生成模板化文档，而是为 agent 建立一个轻量的项目文档工作区，并要求 agent 按功能模块逐步阅读、确认和补全文档。

## 核心作用

- 初始化项目文档工作区
- 在 `index.md` 记录最近一次 git 状态和 AI 阅读进度
- 保存一份不超过 200 字的项目用途说明
- 引导 agent 先和用户确认项目整体方向，再按功能模块深入阅读项目
- 在已有文档项目中，根据上次记录的 git 状态判断是否需要重新记录文档

## 初始化产物

初始化时只创建最小结构：

```text
project-docs/
├── index.md
├── project-description.md
└── document/
```

其中：

- `index.md` 是 AI 可读的阅读进度板，只集中记录最近 git 状态、已经做了什么、接下来要做什么
- `project-description.md` 保存用户提供的项目用途说明，不超过 200 字
- `document/` 是空文档目录，后续由 agent 按用户确认后的功能模块逐步建立内容

## 文档原则

- 不在初始化阶段生成项目规划模板
- 不把目录结构直接当成功能模块
- 不跳过用户对大功能模块划分的确认
- 不在没有阅读代码和现有文档前写正式模块文档
- 不用统一章节模板强行套所有功能模块
- `catalog.md` 只列子功能模块，不承担进度日志和任务状态机职责
- 文档按功能模块组织，必要时继续细分为子功能模块文件夹

## 参考流程

正式流程放在 `references/` 下：

- `references/workflow.md`：新项目与已有项目的完整工作流
- `references/index-format.md`：`index.md` 的写法说明

使用本 skill 时，先阅读这些参考文件，再执行初始化或维护动作。
