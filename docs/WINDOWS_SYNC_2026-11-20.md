# Windows 更新复核 · 2026-11-20

给 Windows 上的 Codex：请先阅读 AGENTS.md 和 docs/WINDOWS_HANDOFF.md，获取最新 origin/main，在干净的独立 codex/ 分支复核本轮改动。保留本机已有工作，不直接推送或合并 main。

本轮主要更新：移除公众号动态；具身日报改读公开 GitHub Pages catalog；新增图表删除、图注编号修正与阅读中就地调整；修复数学表格分列；会议并列显示 CCF/TH 分类并淡化已截止卡片；更新 GitHub 首页与安装指南。不要恢复 PPT 生成或公众号模块。

## 本轮重点

1. 使用临时数据、合成 PDF 与模拟模型运行 Python 全套测试，以及 reader-split 和 conference-rules 的 Node 测试。
2. 运行 `python tests/verify_windows_product.py`，检查下滑后的图表入口、取消及保存后的滚动位置、删除图表后的报告图片保留，以及数学表格显示。
3. 检查会议两套分类、方向标签、已截止样式与展开详情。
4. 联网读取具身日报目录并打开一篇已有讲解，确认日期筛选、待读清单与 HF 全量列表正常。网站访问失败单独记录，不据此改业务规则。
5. 检查 README 图片与安装指南链接、源码打包包含必要资源。启动、导出与文件操作若有 Windows 回归，仅在兼容层修复。

本轮不调用真实模型，不消耗 Codex/DeepSeek 额度；不读取或提交个人账户资料、密钥和论文。macOS 当前 Python 418 项中 416 项通过、2 项跳过，Node 12 项通过；这些不是本轮 Windows 实机结果。

将环境、命令、通过/失败/未测项补到 docs/WINDOWS_VALIDATION.md。无产品代码问题时只提交验证记录；推送独立分支并创建草稿 PR，交 macOS 端复核。结束时停止自己启动的测试服务，不影响已有应用与其他进程。
