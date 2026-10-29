# Windows 合并后复核 · 2026-10-29

## 可直接交给 Windows Codex 的提示词

请在当前 PaperPilot 项目完成本轮 Windows 原生兼容复核。先阅读 AGENTS.md、本文件、docs/WINDOWS_HANDOFF.md，以及 docs/WINDOWS_VALIDATION.md 中已有的实测结果。macOS 决定产品行为；这轮只适配与验证，不重新设计功能。

先检查工作区与 Git 状态，保留未提交工作。获取最新 origin/main，从它创建 codex/windows-postmerge-check 分支；如果同名分支已有本轮工作，先检查再续用或选择新的 codex/ 分支。不要 reset --hard、强推或在旧 windows-compat 分支上重新实现已经合并的功能。旧 Windows 分支截至 ac376e5 已在主线中保留合并历史。

本轮重点：PPT 生成功能已正式删除，不要恢复，也不再测试它。阅读报告、PDF 导出、模型调用与 Windows 启停保持支持。新增批量释放 PDF、批量删除报告和高清图片缓存，按下方清单检查。

使用临时测试目录、合成账户与合成 PDF，不读取真实论文、私人资料或其他应用凭据；不要删除现有用户文件。此前 Codex 和 DeepSeek 已有真实业务验收，本轮默认只做离线模拟与文件/浏览器实测，不运行任何 --real 脚本，不消耗模型额度；如发现只有真实调用才能定位的问题，先报告原因并另行取得授权。此前测试授权不作为本轮新增调用授权。

尽量自主完成排查和最小兼容修复，仅在确实需要系统安装权限、产品决定或无法安全保存本机未提交工作时请求协助。更新 docs/WINDOWS_VALIDATION.md，记录主线基线提交、环境、命令、结果和未测项。允许提交并推送本轮 codex/ 分支、创建以 main 为目标的草稿 PR，不直接推送或合并 main。若只有验证记录变化，也可提交文档 PR。最终返回结果和 PR 链接。

## 本轮已在 macOS 完成的变化

- 合并 Windows 启停、文件锁、SQLite 句柄、Codex 进程与模型接入兼容修复。
- 修复报告行内公式；阅读图片按需高清渲染，每账户可再生图片缓存上限 512 MiB。提供模型的图片不随阅读窗缩放增大。
- 移除 PPT 生成、范例入口及 pptxgenjs 依赖；历史用户文件保留，阅读报告与 PDF 导出继续使用。
- 阅读页“⋯”支持释放原文、删除报告、移除论文；只有移除论文的菜单项显示红色。
- 论文库批量管理提供两种操作，作用于当前分类，每次最多 100 篇。切换操作清空勾选；预览后才执行；逐篇返回成功和失败。
- 删除报告保留原文、摘要、思考、对话、阅读状态与已导出文件。只清理报告专用图片；报告版本在确认期间变化时跳过，避免删除新报告。知识图谱根据材料指纹判断待更新，旧图谱保留。
- 释放原文保留报告及其中的图片、正文文字和阅读成果；可自动恢复或手动上传，手动选择优先。

## 准备和命令

复用本机现有 Python 3.12 与 Node 环境。停止本次项目服务前确认没有运行任务，不停止机主其他进程。依赖有变化，更新源码后执行 npm.cmd ci；它会移除过期的 PPT 依赖。不要使用旧 node_modules 的残留包掩盖漏声明依赖。

PowerShell 在项目根目录运行（若 .venv 不存在，按通用交接说明创建）：

```powershell
npm.cmd ci
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONUTF8 = '1'
$env:PAPERPILOT_DATA = Join-Path $env:TEMP ("paperpilot-review-" + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
node --test tests/reader-split.test.cjs tests/conference-rules.test.mjs
.\.venv\Scripts\python.exe -X utf8 tests/verify_windows_product.py
.\.venv\Scripts\python.exe -X utf8 tests/verify_exports.py
```

浏览器缺失时用已有 Chrome/Edge 的实际路径设置 PAPERPILOT_CHROME，或安装 Playwright Chromium；不要写入机器专用路径到源码。产品集成脚本会自行建立并清理临时服务和合成资料；名称中的 Windows 不代表其他平台运行一次就完成 Windows 验收。

## 实机重点

1. 双击启动/停止、重复启动与后台任务停止保护；中文、空格路径正常。
2. 阅读报告和数学范文入口正常，PPT 控件消失。实际 PDF 导出包含中文、公式和图表。
3. 打开批量管理，切换两种操作、全选/取消、预览后取消均不修改论文；没有报告或没有 PDF 时空列表正常。执行后留在当前分类和位置。
4. 批量删除报告后，摘要、思考、阅读状态、原文及导出 PDF 保留；预览后报告变更的跳过保护、部分失败与跨账户隔离由临时数据测试验证。
5. 释放 PDF 后报告图片仍可显示和导出；自动/手动恢复路径正常，手动恢复优先。观察 Windows 文件占用错误，不用忽略异常掩盖。
6. 图片缓存清理不删原文、已导出文件或不可再生的报告图片；高清图片被清理后能按需重建。512 MiB 边界用测试的临时限额/合成文件验证，不必实际填满磁盘。
7. 运行测试，记录失败原始原因；不删除测试、放宽校验或改产品规则求通过。测试数随功能移除变化，不能拿旧数量要求恢复 PPT 测试。

本轮没有要求重复付费模型全流程，也没有要求重新做知识图谱生成。复杂图谱交互若未实测需保留未测说明。只清理本次创建的测试数据、服务与环境变量，不处理机主其他文件或进程。
