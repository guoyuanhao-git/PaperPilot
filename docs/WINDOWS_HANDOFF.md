# Windows 适配交接：给 Windows 上的 Codex

## 任务与边界

用户已授权在本机为 PaperPilot 做 Windows 原生兼容适配与验证。macOS 是产品主开发线；保留现有页面、功能、模型规则、隐私边界与业务测试。本机为借用的测试电脑，尽量自主完成，仅在系统安装授权、账号登录或必要产品决策时请求用户协助。不能承诺零交互：系统权限与登录必须由机主/用户完成。

先读根目录 AGENTS.md、README.md 及本文件。无需原会话、个人资料或论文。不要寻找原作者的 memory/、参考例文或旧机器目录；不把本机的 Codex/dsh 私有凭据复制进应用。

在开始前检查工作区、Git 状态、当前分支和环境，保留已有改动。基于最新 origin/main 新建 `codex/windows-compat`（已存在则检查并续用合适的分支）。实现、验证后提交并推送该分支，创建草稿 PR，目标 main；不要直接推送或合并 main。此交接包含提交、推送及创建草稿 PR 的授权，不包含发布版本、开放公网或修改产品规则。

## 实施顺序

1. 记录 Windows / Python / Node / 浏览器版本，使用 Python 3.12、Node 22 作为基线。优先复用已有运行时；项目内建 .venv。缺依赖时尽量通过已安装工具或官方包源安装；不全局放宽 PowerShell 执行策略，不关闭安全软件，不修改其他项目。
2. 先复现启动阻塞，再集中实现跨平台文件锁及进程管理。不要仅通过 WSL 宣称原生 Windows 完成。
3. 提供 Windows 双击启动/停止入口及清楚的首次安装说明；重复启动复用原服务，路径包含中文、空格也可用。
4. 核查 Codex 可执行文件探测（包括 .cmd 包装器）、参数转义、登录作用域、子进程与取消；DeepSeek 保留现有 API 调用与用户隔离。共用 `paperpilot.model_setup`，不复制一套业务逻辑。
5. 验证网页、上传/裁剪、数学公式、图谱、PDF/PPT 导出，以及重启后数据保留。
6. 增加必要跨平台回归测试，整理实际结果、截图及操作说明，提交草稿 PR，由 macOS 端复核后合并。

## 已知入口与风险（源码检查，不代替实机结果）

| 入口 | 核查点 |
| --- | --- |
| paperpilot/accounts.py: instance_lock | fcntl 在 Windows 不存在；保持同数据目录单实例互斥与异常释放语义 |
| paperpilot/launcher.py | 启动锁、后台进程、停止与 PID 复用防护；不得误杀其他进程；有生成任务时不能直接停服 |
| run.sh、tools/open-app.sh、.command、.app | macOS/Unix 入口，添加 Windows 入口并保留它们 |
| paperpilot/model_setup.py、providers.py | CLI 查找、账户隔离、CODEX_HOME、参数包含空格、取消与超时 |
| paperpilot/credentials.py | macOS 钥匙串保持原行为，Windows 现行磁盘存储不可回显；不要为适配改成共享全局密钥 |
| tools/export.mjs、presentation-export.mjs | Playwright Chromium、中文字体、路径/file URL、临时文件释放 |
| paperpilot/store.py、documents.py | SQLite 并发、文件占用、恢复/删除 PDF、原子替换在 Windows 的行为 |
| paperpilot/conference_registry.json、web/conferences/logic.mjs | 运行所需文件，不得在打包时遗漏 |

## 安装与离线验证起点

以下是开发准备命令，不代表当前版本已经能完整启动 Windows 服务。PowerShell 中在项目根目录运行；若 `py` 不存在先定位现有 Python。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci
npx.cmd playwright install chromium
$env:PAPERPILOT_DATA = Join-Path $env:TEMP ("paperpilot-win-" + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests/reader-split.test.cjs tests/conference-rules.test.mjs
```

修复启动问题后，用上述临时数据目录创建测试用户；不得从 GitHub/Mac 拷贝用户数据。测试 PDF 用 reportlab 合成，模型响应用模拟。`python -m paperpilot.server --port 8766` 可用于调试；最终必须验证新双击入口。运行 `python tests/verify_exports.py` 验证 PDF，并补测 PPTX 导出与浏览器显示。

真实模型测试单独进行：本任务不自动授权消耗订阅或 API 额度。未获授权就记录“真实 Codex/DeepSeek 未测”；本地配置检查通过不得写成模型连接成功。模型设置里的协助接入提示词必须使用 Windows 实际项目目录、当前账户和端口。

## 验收清单

- [ ] 干净克隆与依赖安装成功；启动前无需 API Key。
- [ ] 中文/空格路径、双击启动、重复启动、端口冲突提示、停止与重启。
- [ ] 未误杀其他进程；后台任务存在时停止保护有效；任务取消能回收子进程。
- [ ] 首次创建账户、切换、数据隔离及重启持久化（仅测试账户）。
- [ ] PDF 上传、摘要、页面渲染、图表裁剪/取消/保存原地更新。
- [ ] 合成报告与问答的 Markdown/LaTeX 渲染，PDF 中文/公式/图片导出，PPTX 生成及可打开。
- [ ] 知识图谱二维/三维、会议列表、静态资产无 404；外部服务失败可用提示、不阻塞本地工作。
- [ ] 模拟调用验证三后台任务并行、其余排队、取消；实际网络/模型测试另列。
- [ ] Python/Node 测试通过，未通过项解释根因，不删除测试掩盖失败。
- [ ] git diff 无 data/、凭据、论文、个人路径、绝对 Chrome 路径和测试机隐私。

在 `docs/WINDOWS_VALIDATION.md` 记录日期、版本、运行命令、结果、已知限制、未测项、macOS 回归风险。不要写密钥、用户名或朋友电脑细节。检查结束停止自己启动的测试服务；不要动朋友其他进程。不要求朋友理解项目架构，只留下能操作的启动/停止入口和简短说明。

如 GitHub 权限暂不可用，保留本地提交并说明精确阻塞，不改用其他 GitHub 账户，也不索取明文 Token。完成后在当前会话返回分支和 PR 链接；不主动向其他聊天发消息。
