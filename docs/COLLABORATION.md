# 协作约定

main 是共享产品基线。macOS 负责产品行为，Windows 负责适配及实机证据，两端共用一份源码。Windows 从最新 main 建适配分支、提交草稿 PR；macOS 检查差异并运行回归后合并。后续 Windows 继续前先同步已合并的 main，不长期维护独立产品副本。

不要跨电脑同步 data/、账户登录或 API Key。GitHub 登录/仓库权限与 PaperPilot 的模型接入是两件事；同一个 Codex 账号不保证本机 Git 已有写权限。

给 Windows Codex 的启动任务：

> 请阅读根目录 AGENTS.md 和 docs/WINDOWS_HANDOFF.md，按交接文档自主完成 Windows 原生兼容适配与实机验证，保留现有产品功能。请使用独立分支，完成后提交、推送并创建草稿 PR，不合并 main。只在系统授权、登录或不可自行决定的事项上询问我；使用临时数据和合成材料，不调用真实付费模型。

macOS 后续接手时：检查 Windows PR 的实际验证报告，关注文件锁、子进程取消、启动停止和导出改动，跑 macOS 回归。合并后仅拉取代码，不覆盖正在使用的数据或模型设置。
