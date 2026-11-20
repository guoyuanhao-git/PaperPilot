# 安装与使用

[← 返回项目首页](../README.md)

PaperPilot 运行在你的电脑上，通过浏览器使用。先安装并启动，再在页面接入模型；启动无需 API Key。当前仓库尚在私有协作阶段，克隆需要仓库访问权限。

```sh
git clone https://github.com/guoyuanhao-git/PaperPilot.git
cd PaperPilot
```

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

PDF 导出需要 Node.js、项目依赖和 Chrome/Playwright Chromium；Linux 另需浏览器系统依赖和中文字体。`PAPERPILOT_CHROME` 可指定浏览器路径，`PAPERPILOT_PYTHON` 可指定 Python。

## Windows 首次使用

安装 Python 3.12 和 Node.js 22（协作基线），在项目根目录的 PowerShell 中执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd ci
npx.cmd playwright install chromium
```

如果没有 `py`，使用已安装 Python 的完整路径创建 `.venv`。历史验收已包含 Python 3.12；具体系统、版本和测试范围见 [Windows 验证报告](WINDOWS_VALIDATION.md)。

完成安装后双击 `启动 PaperPilot.cmd`，浏览器将打开本地页面。重复启动会复用当前项目和数据目录的服务。双击 `停止 PaperPilot.cmd` 停止服务；有后台任务时会提示先完成任务。失败时窗口保留错误消息，按任意键关闭。保留这些入口在项目文件夹内，可创建桌面快捷方式。

终端也可运行 `run.cmd`，或 `run.cmd --stop`；使用其他端口时运行 `run.cmd --port 8766`。`PAPERPILOT_PYTHON` 可指定 Python 可执行文件的完整路径。入口自动启用 UTF-8，不需要修改系统区域或 PowerShell 执行策略。

默认数据位于项目 `data/`，日志位于 `data/desktop/service.log`；设置 `PAPERPILOT_DATA` 后日志和启动记录位于该数据目录的 `desktop/`。启动和停止须使用相同的数据目录。端口冲突时按提示处理，不会停止占用端口的其他服务。启动器不自动安装依赖。

Windows 直接运行开发测试时建议先设置 `$env:PYTHONUTF8 = '1'`。桌面启停已验证，完整 Python 回归、PDF 导出和真实模型调用的状态见验证报告。

## 模型接入

在“模型设置”选 Codex 或 DeepSeek，点击协助接入并复制提示词。页面自动带入当前项目目录、账户和端口，提交给同一台电脑上的助手。也可展开手动配置。

- Codex：通过本机 `codex exec` 和该用户的登录调用；不是 OpenAI API Key 计费通道。
- DeepSeek：通过 API Key 调用。macOS 使用钥匙串且不降级为明文；Windows/Linux 当前使用账户目录下的本地凭据文件。不会提取或转换 dsh 登录令牌。
- 无凭据也可浏览页面、管理论文及使用无需模型的功能。真实生成另需接入和额度。
- 切换模型不改变公共业务规则，也不创建另一套用户资料或图谱。

## 第一次阅读

1. 创建本地用户，进入“模型设置”接入 Codex 或 DeepSeek。
2. 在“研究档案”填写研究方向、当前课题与研究主线；留空项不会被工具自行补全。
3. 上传 PDF 或输入 arXiv 链接 / 编号，进入论文阅读。
4. 选择研究论文或综述、阅读深度，按需修改叙述线，再生成解读。
5. 保存思考，为论文填写年月与短标题，标记已读、喜欢或收藏。
6. 在知识库生成领域图谱，再选择研究主线生成主线图谱。

## 数据与隐私

源码不携带任何用户账户、论文、报告、记忆、密钥或参考例文。首次启动会在 `data/` 创建本机数据；设置 `PAPERPILOT_DATA` 可改用另一数据目录。账户数据位于 `data/users/<id>/`，不随 Git 同步。

这是同一台电脑上的工作区隔离，不是面向公网的多租户认证。默认只监听本机；不要直接开放到公网。模型功能会把本次所需材料发送给所选服务。备份个人资料请先停止服务再单独备份数据目录，不要上传 GitHub。

图表自动提取可能遗漏或裁剪错误，可手动校正；扫描件尚无 OCR。模型报告与图谱联系应结合原文核对。

阅读图表从 PDF 按需生成高清裁图。每个账户的可再生图片缓存（裁图与页面预览）共用 512 MiB 上限，超出时清理最久未使用的图片，再次阅读会自动重建；模型使用独立的小图临时副本。已释放 PDF 的报告图片、替换 PDF 后旧报告仍引用的图片不参与缓存清理。此额度不包含原始 PDF、保留图片及导出文件。

## 更新与故障排查

- 更新代码前先停止服务，单独备份 `data/`（或 `PAPERPILOT_DATA` 指定的目录）；不要把个人数据提交到仓库。
- 更新依赖时重新运行 `pip install -r requirements.txt` 和 `npm ci`。
- 页面打不开：查看启动窗口与 `data/desktop/service.log`；确认端口未被其他服务占用。
- PDF 无法导出：确认依赖和 Playwright Chromium 已安装，或用 `PAPERPILOT_CHROME` 指向可用 Chrome。
- 模型无法调用：在模型设置检查当前用户的接入；本地凭据已保存不代表远程调用成功。
- 具身日报使用公开 GitHub Pages 目录。网络失败时保留已有缓存；外部服务不可用不影响本地阅读。
