# Windows 产品验收报告

最新真实浏览器与导出检查已通过。本文末尾的“产品验收最终结果”是当前结论；前文保留诊断过程与历史失败，不能将历史失败当作当前状态。


日期：2026-10-29。开发分支：`codex/windows-compat`。初始基线：`origin/main` 的 `6012b640a2f9db5c10c3f98d18e2fc3ce8d69448`。

## 结论与验收范围

Windows 原生 CMD 启动、后台运行、重复启动复用、停止和重启流程已通过实机测试。测试使用临时目录和合成账户，没有调用真实模型，没有使用日常用户数据。

验证包含实际执行两个供双击使用的 CMD 文件，但未通过资源管理器鼠标双击；不能把入口执行测试写成已验证资源管理器交互。浏览器由启动器调用默认浏览器打开，首页另外通过 HTTP 验证；页面视觉与完整业务功能未验收。

## 环境与准备

- Windows 版本号：10.0.26200；Python 3.11.9；Node 22.14.0；Git 2.54.0.windows.1。
- 项目基线为 Python 3.12、Node 22。测试机 Python 启动器未发现 3.12，因此本轮使用已有 3.11.9；3.12 仍待验证。
- 项目 `.venv`、`requirements.txt` 依赖、`npm.cmd ci` 和 `npx.cmd playwright install chromium` 安装成功。Playwright Chromium：151.0.7922.34。
- pip 使用本机既有配置的软件源；没有修改系统执行策略或安装全局 Python。
- npm 报告两个高危依赖漏洞，尚未调查其适用性，也未自动升级依赖。

## macOS 转 Windows 发现的问题

| 问题与证据 | 原因 | 处理与当前状态 |
| --- | --- | --- |
| `ModuleNotFoundError: fcntl` | Windows 不提供 Unix 文件锁模块 | 新增共享 file_lock；Windows 用 msvcrt 字节锁，其他平台保留 flock。跨进程争用、异常释放通过 |
| 会议注册表导入 UnicodeDecodeError | 隐式读取编码在本机为 cp1252，源文件为 UTF-8 | conferences.py 明确 UTF-8；直接导入成功，读取 13 项 |
| 打印中文启动消息时报 UnicodeEncodeError | 标准输出采用 cp1252 | 服务启动日志改为 ASCII；Windows CMD 入口及其服务子进程启用 UTF-8 |
| Windows 缺少桌面启停入口 | 既有入口是 shell、command、app | 新增 run.cmd 及两个 CMD 包装入口；中文与空格路径实测通过 |
| 包装进程与实际 Python 服务 PID 不同 | 本机虚拟环境启动层存在额外进程 | launcher 在实例标识及随机 nonce 匹配后保存健康接口的实际服务 PID；停止身份校验和实际启停通过 |
| 后台进程窗口行为不同 | Unix session 选项不能表达 Windows 控制台行为 | Windows 使用 CREATE_NO_WINDOW；Unix 保留 start_new_session |
| 部分测试清理 SQLite 报 WinError 32 | 观察到文件仍被占用；store.connect 的 SQLite 上下文只管理事务，不保证关闭连接，可能相关，尚未完整追踪 | 本轮未修复。独立测试账户启动、停止和重启通过，不代表所有文件生命周期问题解决 |

## 文件改动及控制流

- `paperpilot/file_lock.py`：新增共享上下文锁。非阻塞争用抛出 BlockingIOError，阻塞模式等待，退出释放；不删除锁文件以避免更换锁目标。
- `paperpilot/accounts.py`：实例锁改用共享实现；仅锁获取争用转换为原有单实例提示，受保护代码内的异常照常传播。
- `paperpilot/launcher.py`：桌面启动锁改用共享实现；区分 Windows 后台进程选项；日志和进程记录显式 UTF-8；保存健康响应中的实际 PID。停止仍核验项目/数据目录身份、nonce、PID，并拒绝停止有后台任务的实例。
- `paperpilot/conferences.py`、`paperpilot/server.py`：分别明确注册表读取编码、替换终端启动日志。
- `run.cmd`：切换到脚本目录，定位项目虚拟环境或显式 Python 路径，设置 UTF-8，检查 Python 与 Node 必要依赖，再调用公共 launcher。
- `启动 PaperPilot.cmd`、`停止 PaperPilot.cmd`：调用同一入口，失败时保留提示窗口；不会自行安装依赖。
- `tests/test_file_lock.py`、`tests/test_launcher.py`、`tests/test_windows_startup.py`：覆盖锁争用、PID、停止保护以及实际 CMD 启停流程。
- `README.md`：新增 Windows 安装、运行、日志和限制说明。

既有 macOS 入口保留；没有删除产品功能、业务测试或放宽业务校验。终端启动日志文字发生变化，网页业务接口没有有意变更。

## 实际验证与命令

| 命令或检查 | 结果 |
| --- | --- |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_file_lock.py` | 1 项通过，跨进程争用及异常释放 |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_launcher.py` | 3 项通过；复用/拒绝其他项目、身份和忙碌保护、保存实际服务 PID |
| `.venv\Scripts\python.exe -m unittest discover -s tests -p test_windows_startup.py -v` | 1 项通过，22.845 秒；复制源码至中文空格临时路径，以临时数据执行真实 CMD 入口 |
| 集成检查：重复启动 | 健康接口 PID 保持不变 |
| 集成检查：首页和账户 | 首页 HTTP 200，创建合成账户成功 |
| 集成检查：停止/重启/持久化 | 启动记录移除，重启后账户 ID 保留，再次停止成功 |
| 集成检查：端口冲突 | 已占用端口时返回失败和端口提示；测试监听器由测试管理 |
| 默认项目 `.venv` 检查 | 未设置 PAPERPILOT_PYTHON，run.cmd 实际启动和停止成功，健康 PID 与记录匹配，端口释放 |
| `node --test tests/reader-split.test.cjs tests/conference-rules.test.mjs` | 前轮 12 项通过；本轮未改 Node 代码，未重复执行 |
| 命令行服务诊断 | 修复后健康接口 nonce 匹配、首页 200，观察期间保持运行；随后停止并确认端口释放 |

所有测试服务均通过测试自己的进程句柄或匹配实例记录停止；临时目录由测试清理。未操作其他用户或其他应用进程。

## 未通过项、未测项与回归风险

- 适配前 Python 基线：运行 138 项、88 个错误，其中很多是注册表导入失败和 SQLite 清理占用。编码修复后的全量重跑长时间未结束，被中止且无最终计数；完整 Python 套件未通过验收。
- 真实 Codex/DeepSeek 未测；没有消耗订阅或 API 额度。Codex CMD 包装器、取消子进程树等模型适配不属于本轮已验证启动流程。
- PDF 上传/裁剪、Markdown/LaTeX、知识图谱二维/三维、会议资产、PDF/PPTX 导出、三任务并行与排队未做完整实机验收。
- 忙碌与过期身份停止保护由回归测试覆盖，未创建真实长时间生成任务。
- 未验证资源管理器鼠标双击、不同系统区域设置、Windows 商店 Python、不同浏览器和重启操作系统。
- macOS 实机回归未做。共享锁的 Unix 分支仍使用 flock，启动 session 选项保留；新增启动 PID 来源为同一健康协议，需 macOS 主开发线复核。
- Windows os.kill(SIGTERM) 是强制终止；当前沿用既有停止方式和忙碌保护，不能宣称已实现优雅关闭或消除所有进程身份检查竞态。

下一轮优先完整追踪 SQLite 连接关闭和全量测试阻塞，再完成导出及模型子进程生命周期验收。此报告证明桌面入口层的原生启停流程通过，不能替代完整 Windows 产品兼容性验收。

## 完整产品验收进展（2026-10-29，进行中）

- 本轮修复前完整 Python 回归：399 项，312 个错误，118.521 秒。
- 已修复 store.connect 生命周期：保留事务提交/回滚，并在 finally 关闭连接。新增事务提交、异常回滚、关闭后不可查询及数据库文件可删除测试，通过。
- 修复后完整 Python 回归：400 项，399 项通过、1 项错误，113.172 秒。唯一错误为 presentations.clean_master_declarations 在原 ZipFile 仍打开时替换原 PPTX，Windows 返回 WinError 5。尚未修复。
- Node 回归：12 项全部通过。
- 现有 tests/verify_exports.py：真实 PDF 导出检查通过，包含中文文本、公式与图表检查。
- 新增 tests/verify_windows_product.py：真实 Chromium 首次创建合成账户、上传两页合成 PDF，以及 library、knowledge、discover、conferences、profile、settings 页面导航通过；没有 pageerror 或本地 HTTP 4xx/5xx。仅证明这些页面的导航与资产加载，不等于各页面所有操作均经浏览器验证。
- 新脚本实际 PPTX 导出失败：同样在 clean_master_declarations 替换尚未关闭的 ZIP 文件时产生 WinError 5。模型生成以合成幻灯片数据替代，实际 Node/PptxGenJS/Chromium 渲染未模拟。未绕过失败。
- 新脚本因 PPTX 失败尚未执行后续 PDF 检查；服务在 finally 中停止。临时数据未提交，无真实模型调用。
- 先前报告中的 SQLite 与全量回归状态应以本节最新结果为准。完整产品验收仍在推进，PPTX 文件占用是当前已确认阻塞。

## 产品验收最终结果（2026-10-29）

本轮批准的离线产品验收检查全部通过。使用临时数据、合成论文和模拟模型，不调用真实付费模型。真实在线服务及真实模型响应质量不在本轮结果中冒充验证。

### 最终命令与结果

- `python -X utf8 -m unittest discover -s tests`：400 项全部通过，202.760 秒。覆盖当前仓库全部 Python 测试，包含其调用的前端逻辑检查。
- `node --test tests/reader-split.test.cjs tests/conference-rules.test.mjs`：12 项全部通过。
- `python -X utf8 -m unittest discover -s tests -p test_presentations.py -v`：11 项全部通过。
- `python -X utf8 tests/verify_windows_product.py`：真实 Chromium 账户创建、合成 PDF 上传、六个页面导航、本地资产无 HTTP 错误、无页面脚本异常；真实三页 PPTX（含公式与图表）生成，ZIP 完整、XML/关系文件可解析、媒体和讲稿备注存在；真实 PDF 导出通过。
- `python -X utf8 tests/verify_exports.py`：中文文字、公式、图表及报告内容的 PDF 导出检查通过。

### 按功能的验收证据

| 功能 | 通过的验证层级 |
| --- | --- |
| Windows 启动、重复启动、停止、重启、中文空格路径 | 真实 CMD 集成回归；默认虚拟环境及端口释放实测 |
| 账户创建、切换、隔离、迁移、持久化 | 全量账户回归；首次创建和上传另经真实 Chromium 检查 |
| 上传、PDF 解析、页面、图表裁剪与保存、删除/恢复原文 | Core、reader、caption、paper_storage 等回归；上传另经真实 Chromium 检查 |
| 阅读模式、报告、问答、引用、断点恢复 | 模拟模型业务回归；真实 PDF 导出检查 |
| Markdown/LaTeX、阅读器状态、页面切换和竞态 | 前端逻辑回归；浏览器页面加载检查；公式真实导出 |
| 三任务并行、排队、取消、晚到响应保护 | reader_pages、analysis_cancel、chat_cancel 等模拟任务回归 |
| 喜欢/收藏/阅读状态和阅读统计 | library 回归 |
| 知识图谱、主线、增量缓存、二维/三维视图逻辑 | knowledge、knowledge_sources、schedule、graph_view/navigation 回归；知识库页面真实浏览器导航检查 |
| 会议、检索、热点、来源、缓存与网络失败处理 | conferences、discovery、title_search、news、daily、hf 等合成响应回归；会议/检索页面真实浏览器导航 |
| 用户资料、记忆、参考风格与 PPT 范例 | profile、memory、style、presentation_samples 相关回归 |
| 模型设置、账户凭据、配置隔离及公共规则 | model_setup、credentials、providers 适配器模拟回归 |
| PDF / PPTX | 实际 Node、Chromium、PptxGenJS 导出；PDF 文本内容检查和 PPTX 包结构检查 |

### 本轮修复说明

- `paperpilot/store.py`：之前 SQLite 连接退出事务后仍保持打开；现在 connect 是上下文管理器，事务成功提交、异常回滚，finally 关闭连接。移除直接返回未托管连接的行为，所有已检查调用仍使用 with。数据库格式和业务 HTTP 接口未变。
- `tests/test_store_connection.py`：增加提交、回滚、关闭状态和文件删除验证。SQLite 修复后，先前大量 Windows 清理/迁移失败消失。
- `paperpilot/presentations.py`：在 ZIP 清理完成后、原子替换前关闭原 PPTX 读取句柄，避免 Windows 拒绝覆盖仍被打开的目标；没有删除幻灯片或绕过校验。
- `tests/verify_windows_product.py`：新增可重复的真实浏览器与真实导出集成检查，仅模拟幻灯片模型生成内容；临时服务在 finally 停止。

### 精确边界

上述通过结果表示现有自动化功能覆盖与新增离线集成检查通过，不保证任意输入、任意机器都无缺陷。真实模型登录/额度/在线生成和当前外部网站可达性没有实测；图谱二维/三维完整鼠标操作尚未逐项人工检查；未在 Microsoft PowerPoint 应用中打开导出的 PPTX（已验证包完整、XML、媒体与备注）；未验证 macOS、Python 3.12 或资源管理器鼠标双击。截图仅使用临时文件，没有把测试账户数据和论文提交到仓库。历史未测项中已被本节覆盖的部分以本节为准。
