# 源码移交基线 · 2026-10-29

本轮在 macOS、Python 3.12、Node 24 环境验证。首次在受限环境运行时，13 个临时 HTTP 服务测试因无法绑定本机端口失败；允许本机端口后发现一个旧前端测试夹具缺失浏览器定时器和当日略过日期。修正夹具后，396 个 Python 测试全部通过；独立 Node 测试 12 个全部通过。

本轮没有调用真实 Codex/DeepSeek 模型，没有在 Windows 或 Linux 上运行。Windows 适配状态仍为未完成，不能将本机测试结果当作 Windows 验收。

源码使用白名单打包，补齐会议来源目录 JSON、会议逻辑 MJS、Node 测试及 ICO。私有数据路径与已知个人标识/密钥模式检查通过；未打包 data/、memory/、个人参考例文、依赖目录、运行日志和本地 Codex 工作流。旧 README 与本机指令保留于忽略的 output/local-before-github/，不上传。

运行时代码仅将档案输入框的特定机构示例改为通用示例；本轮未修改模型规则与用户实际档案。Windows 交接见 WINDOWS_HANDOFF.md。

另外在干净解压目录执行 `npm ci --offline --ignore-scripts`（复用 npm 本机缓存，未共享 node_modules），安装锁文件中的 62 个包，再次通过 396 个 Python 测试与 12 个 Node 测试。初次未安装 npm 依赖时数学渲染测试按预期缺少 KaTeX；安装后通过。会议测试所需 JSON 夹具也纳入源码白名单。
