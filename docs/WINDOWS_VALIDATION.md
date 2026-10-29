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

## 真实 Codex 订阅验收进展（2026-10-29）

- PR #1 已确认仍是 open draft、未合并；继续 codex/windows-compat，保留日常服务和数据。
- CLI 0.149.1，实际命中 codex.exe；项目 Python 3.11.9，普通终端 Python 3.12.7（缺项目 PDF 依赖），Node 22.14.0。
- 修复 Windows 接入命令：显式使用服务解释器、PowerShell LiteralPath/调用运算符及 UTF-8，避免裸 python 命中错误环境。命令真实执行通过，不需要激活 venv。中文/空格/单引号路径引用回归 1 项通过；model_setup 模拟回归 10 项通过。
- 测试账户原无登录，通过官方 Codex CLI 浏览器流程完成隔离登录，未复制凭据、未更改全局登录、未使用 API Key。
- 当前底层真实请求计数 6/20：连接测试 1，速览流程 1（本地保存 checkpoint 失败），两条图片/上下文问答 2，运行中取消 1，取消后恢复问答 1。CLI 内部请求和流重试在验收服务中设为 0；计数在实际适配器子进程入口执行，重试同样计入。
- 实际后台连接任务 completed，模型 gpt-6.1-sol，适配器耗时 15.73 秒，任务耗时 16.53 秒。
- 合成 PDF 两页，包含中英文、公式和嵌入的彩色图像，上传识别出一张图。速览 failed：checkpoint 临时文件路径超过 Windows 常见 MAX_PATH 限制，FileNotFoundError；这是本地路径错误，不是权限、额度或网络失败。报告尚未成功生成。
- 图片问答 completed，模型正确回答图中橙色圆形 5 个、蓝色方形 2 个；答案没有写入论文正文。第二条依赖上下文，正确给出合计 7 个并复述 AX7。两条回复已通过重新读取 bootstrap 核对保存。适配器耗时 10.31 / 11.45 秒，后台任务耗时 11.38 / 12.39 秒。
- 真实 Chromium 正确账户阅读页点击停止：任务 cancelled；五秒后原对话及原报告状态不变；观察到的 1 个本次模型子进程已退出。取消后真实追问 completed。当前实际为原生 exe，没有 cmd 包装器；尚未验证 cmd 包装器及更深子进程树回收，不声称已通过。
- 模拟三任务并行、第四任务排队及任务账户隔离：reader_pages 3 项通过。未用真实模型测试并发。
- usage 提供 reasoning_effort、transport 和 elapsed_seconds；CLI 当前适配器不提供可核算 token 数，未推算 token 或费用。
- 本次隔离测试服务已停止；日常服务保留。隔离登录数据仅保留在本机临时测试目录，未复制/输出 auth.json 或令牌，不提交合成论文和账户数据。
- 本轮暂不测试 DeepSeek。剩余：修复 checkpoint 路径、真实速览结构化报告保存重开；cmd 包装器和超时/子进程树专项；中文空格项目路径的真实 PowerShell 命令检查。达到 20 次前停止新的真实请求并总结。

## 真实 Codex 订阅验收最终结果（2026-10-29）

本节覆盖上一节的进行中状态。使用 ChatGPT 订阅和隔离合成账户，未使用 OpenAI API Key，未测试 DeepSeek，未修改日常数据或全局登录。

### 四项结论

| 项目 | 实际结果 |
| --- | --- |
| 接入 | 通过。页面生成的命令在普通 Windows PowerShell、无 venv 激活、含中文/空格/单引号的项目目录下执行成功；官方隔离登录 ready；两次实际适配器后台连接任务完成，均为原配置默认 gpt-6.1-sol |
| 报告生成 | 通过。两页中英文/公式/彩色图表合成 PDF；速览生成 6 章节，vision=true，经过公共结构校验、保存、服务重启及真实 Chromium 重开 |
| 图片与连续对话 | 通过。正文没有给出计数答案，实际图像问题正确回答橙圆5、蓝方2；第二条沿用上下文得出7并复述 AX7；重启后回复仍保存 |
| 取消及恢复 | 通过。真实 Chromium 阅读页点击停止，运行任务 cancelled，五秒后旧对话及原报告状态未被晚到结果覆盖，观察到的本次模型进程退出；随后真实追问完成 |

### 请求预算、耗时与 usage

底层 CLI exec 入口总计 **16/20 次**，包括取消。验收服务在实际 cancellation.run_process 入口计数并持久化，拒绝第21次；同时对该服务调用显式关闭 CLI 请求/流内部重试。没有单独终端 exec 冒充应用测试。

| 批次 | 底层次数 | 结果及耗时 |
| --- | --- | --- |
| 初次应用连接任务 | 1 | completed；适配器15.73秒，后台任务16.53秒 |
| 修复前速览 | 1 | 模型阶段返回后，checkpoint 保存因本地路径268字符而失败；不是网络/额度/权限失败；该阶段独立耗时未保留 |
| 两条图片及连续问答 | 2 | completed；适配器10.31/11.45秒，后台任务11.38/12.39秒 |
| 运行中停止 | 1 | cancelled；真实点击停止，未保留准确运行耗时，不虚构数值 |
| 停止后恢复问答 | 1 | completed；独立耗时未保留 |
| 修复后完整速览 | 9 | completed；后台任务155.83秒 |
| 更新后 Windows 运行时再连接 | 1 | completed；后台任务10.27秒，服务已加载新包装器解析及进程管理代码 |

速览九阶段适配器耗时：框架24.16秒、逐图18.02秒、图表取舍14.80秒、动机17.53秒、方法20.61秒、实验20.98秒、结论13.25秒、阅读建议14.89秒、作者整理8.52秒。usage 提供模型、思考等级、HTTPS transport 和 elapsed_seconds；当前 CLI 适配器未提供可核算的真实 token 数。报告内 completion_tokens=0 是应用聚合缺省值，不能解释为实际免费或零 token。没有估算费用。

### 新发现及修复

- model_setup.py：Windows 原命令裸 python 在普通终端命中了缺项目依赖的3.12.7，而服务使用3.11.9。现在显式引用服务解释器，使用 PowerShell LiteralPath、调用运算符和 -X utf8；实际命令检查及中文/空格/单引号路径回归通过。
- reading_checkpoint.py：临时名附加完整缓存键和 UUID，路径268字符；现在同目录使用独立 UUID 临时名，171字符，最终缓存文件仍236字符。缓存键、最终文件和原子替换保持不变，真实速览由失败转为成功。并非全局解决任意长路径；更深目录仍受系统限制。
- codex_runtime.py：新增 Windows npm CMD/BAT 解析：直接使用同名原生 exe 或对应官方 npm Node 入口，未知包装器明确拒绝，绝不使用 shell=True。当前机器安装的是 exe；CMD 官方目录布局用模拟包装器和真实 Node 验证，未声称测试过真实 npm 安装。
- codex_account.py、providers.py、model_setup.py：登录状态、官方登录与实际生成共用包装器解析；清除 API Key 的原有隔离语义保留，macOS 原生可执行路径保持原样。
- cancellation.py：后台 Windows 进程以 Job Object 绑定本次进程树，任务成功、取消或超时退出时关闭对象回收后代；标准流显式 UTF-8。无按进程名批量清理，非 Windows 和同步调用保留既有路径。模拟实际 Node 父子进程的取消与超时回归通过；真实取消观察到的是原生 exe 任务，不冒充真实 CMD 多层树测试。
- tests/test_codex_windows.py：增加接入命令引用、短 checkpoint 临时名、特殊字符参数保真、取消和超时子进程树回收回归。
- tests/verify_codex_subscription.py：隔离测试服务、合成账户准备及20次请求预算保护入口。执行 --prepare 后按页面官方流程登录；后台服务实际请求由计数器约束。验收图片和人工浏览器检查使用临时合成材料，不提交论文或账户。

### 回归与收尾

- checkpoint专项7项通过；接入命令专项10项通过；Windows Codex专项4项通过；取消专项4项通过。
- 三任务并行、第四任务排队及账户任务隔离继续使用模拟模型，reader_pages 3项通过。
- 已停止本次隔离服务，保留机主日常服务及其他进程；隔离登录仅留本机临时测试目录，未复制/输出令牌或 auth.json，未提交个人路径和登录状态文件。
- 真实请求在16次停止，余4次未用。真实DeepSeek、真实npm安装包装器、多种Codex版本和macOS实机未测。网络、额度及模型权限本轮均未触发已确认失败；唯一真实流程失败是已修复的本地checkpoint路径。

最终完整回归：`python -X utf8 -m unittest discover -s tests`，**404项全部通过，147.918秒**。本轮新增4项Windows Codex回归包含在该总数内。最新真实测试与回归均完成后不再追加订阅调用。

## DeepSeek 真实业务验收最终结果（2026-10-29）

本节更新此前“DeepSeek未测试”的历史状态。本轮实际使用当前账户已配置的 DeepSeek API，保持 https://api.deepseek.com 和 deepseek-flash；可能产生API费用。没有使用 .claude 的其他服务凭据，没有更改日常账户设置或发送日常材料。

### 结果

| 功能 | 结果与证据 |
| --- | --- |
| 应用后台连接 | completed，任务2.17秒；API1.61秒，23 tokens |
| 上传与速览 | 两页中英文、公式和嵌入彩色图像的合成PDF，识别出1张图；真实速览completed，70.51秒，保存6章节，经过现有公共结构校验 |
| 图像理解 | 实际请求包含image_url；模型正确识别橙色圆形5个、蓝色方形2个。正文不包含计数答案。问答任务3.22秒 |
| 连续对话 | 第二条正确沿用上一条计数得出7，并复述标记DS7，任务5.36秒；回复已保存 |
| 真实页面停止 | Chromium点击停止，运行任务cancelled；等待5秒后旧报告与旧消息均保持不变，没有晚到覆盖 |
| 取消后恢复 | 新追问completed，2.77秒 |
| 保存与重新读取 | 再次通过bootstrap读取，报告内容保持一致、对话6条；本轮没有额外重启测试服务，不能把重新读取写成重启测试 |

### 预算与用量

本轮新增实际HTTP请求 **14/20次**，在 providers._post_json 实际网络入口以锁保护计数，包括图像请求、重试及取消；达到20次拒绝新请求。13次请求返回有效响应，1次取消。没有自动改模型或绕过公共业务校验。

- 连接1次；速览9次；图像问答1次；上下文问答1次；取消1次；恢复问答1次。
- 已返回usage的13次请求：输入14723、输出8833、合计 **23556 tokens**，以服务实际返回统计，不估算价格。
- 取消请求没有返回可用usage，可能仍产生服务端费用，不能视为零token或上述合计覆盖全部计费。
- 速览九阶段API耗时依次15.14、4.31、4.91、7.91、8.17、8.78、9.16、7.53、2.42秒；图片问答2.84秒、连续追问4.62秒、取消请求1.66秒、恢复问答2.00秒。
- 速览图像阶段及三次普通问答、一次取消问答均实际携带图像；没有把仅有图注的请求冒充视觉验证。

### 脚本、隔离与回归

新增 `tests/verify_deepseek_subscription.py`。需显式 `python -X utf8 tests/verify_deepseek_subscription.py --real` 才可消耗API；默认从8766当前账户读取既有配置及授权密钥到进程内存，为临时合成账户设置会话密钥，不把密钥写到临时credentials文件。临时服务使用空闲端口。测试结束停止临时服务、清除本进程会话密钥并清理临时数据，日常服务保留。

脚本输出仅包含脱敏结果、合成回答、模型、计数、耗时和usage，不输出token/API Key。该脚本每次 --real 都是新的最多20次真实测试；不要将它混入日常离线回归。

本轮没有发现需要修改生产代码的新问题。真实流程通过后，脚本补充明确的结果断言和异常路径的任务取消收尾；未为此重复付费测试。`--help`入口检查通过；现有chat_cancel四项模拟回归通过。上一轮完整404项回归通过，生产代码本轮未变。

当前结论：在本机和当前deepseek-flash配置下，真实接入、合成报告、图片理解、连续问答及取消恢复均通过。本轮未覆盖所有DeepSeek型号、所有论文输入或网络故障状态；取消不能承诺撤销服务端已经发生的计费。上述结果与前轮Codex真实验收分别记录，不混用额度或usage。

## macOS 合并验证（2026-10-29）

将 Windows 分支截至 `ac376e5` 的改动与 macOS 的报告公式修复、高清裁图和每账户 512 MiB 可再生图片缓存合并，未发生文本冲突。以下结果来自 macOS、Python 3.12.14；没有调用真实模型，没有使用个人论文或修改账户资料。

- 修正 Windows 接入命令测试的模拟范围：只替换 model_setup 的平台视图，不再全局改变 os.name，避免 macOS 上 pathlib 错误构造 WindowsPath。保留该项测试及其中文/空格/单引号命令校验。
- 离线产品集成脚本支持已有的 PAPERPILOT_CHROME 浏览器路径选项。本机使用已安装 Chrome，未要求额外下载 Playwright Chromium；Windows 未设置此变量时仍使用原默认行为。
- 完整 Python 回归：414 项，412 项通过，2 项 Windows 专用测试跳过（CMD 启停与 Job Object 子进程树）。没有失败。
- Node 回归：12 项全部通过；前端语法及 Git diff 格式检查通过。
- 实际浏览器：合成账户、PDF 上传、六个页面导航、无页面脚本或本地 HTTP 错误；实际三页 PPTX 包结构/公式图片/备注及 PDF 导出通过。独立 PDF 导出检查通过中文、公式、图表和报告内容校验。
- 打包白名单已加入 run.cmd、启动 PaperPilot.cmd、停止 PaperPilot.cmd，并新增打包回归，避免源码 ZIP 缺少 Windows 入口。

上述合并验证不代替 Windows 实机复核。同步合并版本后，Windows 应再运行离线回归，重点检查新增图片缓存的清理/重建、释放 PDF 后保留图表、模型临时图片清理及导出；没有新失败时无需重复此前的付费模型全流程。复杂图谱完整鼠标交互与 Microsoft PowerPoint 内打开仍按前述未测范围保留。
