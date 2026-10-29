# Windows 验证记录

日期：2026-10-29。基线：origin/main 6012b640a2f9db5c10c3f98d18e2fc3ce8d69448。
环境：Windows 10.0.26200，Python 3.11.9（项目基线为 3.12，本机启动器未发现 3.12），Node 22.14.0，Playwright Chromium 151.0.7922.34。

## 适配前基线

- Python 依赖、npm ci 和 Playwright Chromium 安装完成；npm 报告两个高危依赖漏洞，影响尚未调查。
- `node --test tests/reader-split.test.cjs tests/conference-rules.test.mjs`：12 项通过。
- 使用独立临时数据目录运行 `.venv\Scripts\python.exe -m unittest discover -s tests`：138 项中 88 项错误。多项导入时会议注册表使用系统默认编码读取 UTF-8，产生 UnicodeDecodeError；部分临时 SQLite 文件清理时产生 WinError 32。其他错误尚待分类。
- Windows 无 `fcntl`；账号实例锁和桌面启动锁依赖它。尚未验证完整启动及锁行为。
- 使用临时数据；未调用真实付费模型。产品功能、导出和 macOS 回归尚未验证。

## 锁适配与启动诊断

- 新增跨平台文件锁，Windows 使用 msvcrt，其他平台使用 fcntl；账号实例锁与桌面启动锁共用该实现。
- `.venv\Scripts\python.exe -m unittest discover -s tests -p test_file_lock.py`：1 项通过，覆盖跨进程争用和异常释放。
- 临时数据目录下运行 `python -m paperpilot.server --port 8766`：未能持续启动。服务执行到输出启动信息时，进程标准输出采用 cp1252，中文输出触发 UnicodeEncodeError。尚未修复，其他启动路径仍待验证。
- 注册表显式 UTF-8 读取后直接导入成功；Node 测试 12 项再次通过。Python 全量测试重跑长时间未结束，被中止，无法报告结果。

## 命令行启动验证（2026-10-29）

- server.py 的终端启动消息改为 ASCII，避免 cp1252 标准输出无法编码中文时导致服务退出。
- 独立临时目录、随机桌面实例标识、端口 8766：健康接口返回 PaperPilot 且标识匹配；首页 HTTP 200，正文 14483 字节；额外观察两秒进程仍在运行。
- 本次创建的启动进程已停止，随后检查 8766 无监听进程。未调用模型。
- 发现 Windows 虚拟环境启动进程 PID 与服务实际 PID 不同；现有 launcher 保存 Popen PID，而停止时要求它与健康接口 PID 相同，可能导致桌面停止被拒绝。仅观察到 PID 差异，尚未完成桌面入口复现及修复。
- 当前只证明命令行服务能启动及首页可取得，未验证网页视觉、上传、生成、导出、双击入口、重启持久化或完整回归。真实 Codex/DeepSeek 未测。
- git diff --check 通过。macOS 文件锁仍走 fcntl 分支，但未在 macOS 实机回归；新增 Windows 锁仅在本机验证。
