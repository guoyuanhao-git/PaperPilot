# PaperPilot

本地个人科研工作台：论文检索与阅读、图表裁剪、问答、PDF / 讲解 PPT 导出、个性化知识图谱、热点发现和会议日程。先启动应用，再在页面配置模型；启动不需要 API Key。

**当前主开发环境为 macOS；Windows 原生适配尚未完成。Windows 上的 Codex 请先阅读 [适配交接](docs/WINDOWS_HANDOFF.md)。**

## macOS 首次使用

安装 Python 3.12 和 Node.js 22（这两版作为协作基线），在项目文件夹中运行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
npx playwright install chromium
./run.sh
```

浏览器打开 http://127.0.0.1:8765/ 。首次创建本地用户，再进入“模型设置”。后续可双击项目内 `PaperPilot.app` 或 `启动 PaperPilot.command`；用 `停止 PaperPilot.command` 停止后台服务。不要把 `.app` 单独移出项目，桌面可放替身。

PDF/PPT 导出需要 Node.js、项目依赖和 Chrome/Playwright Chromium；Linux 另需浏览器系统依赖和中文字体。`PAPERPILOT_CHROME` 可指定浏览器路径，`PAPERPILOT_PYTHON` 可指定 Python。

## 模型接入

在“模型设置”选 Codex 或 DeepSeek，点击协助接入并复制提示词。页面自动带入当前项目目录、账户和端口，提交给同一台电脑上的助手。也可展开手动配置。

- Codex：通过本机 `codex exec` 和该用户的登录调用；不是 OpenAI API Key 计费通道。
- DeepSeek：通过 API Key 调用。macOS 使用钥匙串且不降级为明文；Windows/Linux 当前使用账户目录下的本地凭据文件。不会提取或转换 dsh 登录令牌。
- 无凭据也可浏览页面、管理论文及使用无需模型的功能。真实生成另需接入和额度。
- 切换模型不改变公共业务规则，也不创建另一套用户资料或图谱。

## 主要工作流

- 论文库：在读、已读、喜欢、收藏；喜欢与收藏互斥。待读清单用于正式导入前暂存候选。
- 论文阅读：研究论文或综述，支持速览、中文精读、数学精读；可定制叙述线及参考例文，支持独立讲解 PPT。多标签页阅读，最多三个后台生成任务并行。
- 知识库：领域图谱组织收藏与喜欢；各研究主线在领域骨架上接入相关已读论文。每个账户每层只保留一份当前图谱，支持增量、重建及可选定时更新。
- 热点发现：具身日报、HF 全量列表、领域动态。具身日报为独立外部服务，地址可由 `PAPERPILOT_EMBODIED_DAILY_URL` 覆盖；外部服务不可达不影响本地阅读。当前默认仍为实验室提供的服务入口，正式发布时再替换公共域名。
- 会议日程：内置模块，从官方来源核查，保留历史，不依赖原独立站的 API 或云端定时器。

## 数据与隐私

源码不携带任何用户账户、论文、报告、记忆、密钥或参考例文。首次启动会在 `data/` 创建本机数据；设置 `PAPERPILOT_DATA` 可改用另一数据目录。账户数据位于 `data/users/<id>/`，不随 Git 同步。

这是同一台电脑上的工作区隔离，不是面向公网的多租户认证。默认只监听本机；不要直接开放到公网。模型功能会把本次所需材料发送给所选服务。备份个人资料请先停止服务再单独备份数据目录，不要上传 GitHub。

图表自动提取可能遗漏或裁剪错误，可手动校正；扫描件尚无 OCR。模型报告与图谱联系应结合原文核对。

阅读图表从 PDF 按需生成高清裁图。每个账户的可再生图片缓存（裁图与页面预览）共用 512 MiB 上限，超出时清理最久未使用的图片，再次阅读会自动重建；模型使用独立的小图临时副本。已释放 PDF 的报告图片、替换 PDF 后旧报告仍引用的图片不参与缓存清理。此额度不包含原始 PDF、保留图片及导出文件。

## 开发与测试

```sh
.venv/bin/python -m unittest discover -s tests
node --test tests/reader-split.test.cjs tests/conference-rules.test.mjs
npm run build:graph
.venv/bin/python tools/package_source.py
```

导出集成检查：` .venv/bin/python tests/verify_exports.py`（合成材料，不调用模型）。测试应在独立临时数据目录下运行，不能对日常用户数据执行清理操作。

| 路径 | 内容 |
| --- | --- |
| `paperpilot/` | Python 服务、模型适配器与公共业务规则 |
| `web/` | 工作台界面及内置会议模块 |
| `tests/` | Python 与 Node 回归测试 |
| `tools/` | 启动、图谱构建、导出、源码打包 |
| `docs/WINDOWS_HANDOFF.md` | Windows Codex 的任务入口和验收标准 |
| `docs/COLLABORATION.md` | macOS / Windows 分支协作 |
| `AGENTS.md` | 所有开发会话共同遵循的规则 |

当前私有协作阶段尚未选择开源许可证；公开发布前再完成许可与素材权利审核。
