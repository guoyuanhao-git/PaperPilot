# 会议日程

界面和届次规则移植自用户自有 embodied-deadlines 项目（2026-10-28），由 PaperPilot 本地模块提供数据。Shadow DOM 隔离样式/ID，退出页面释放计时器。关注绑定账户与会议系列；旧域名 localStorage 的关注需要重新选择。

`paperpilot/conferences.py` 管理本地目录、唯一关注和每周补查，`conference_sources.py` 只抓取官方入口及官方域内链接，`conference_update.py` 统一模型提取与官方原文证据校验。前端 GET 不触发核查；POST 启动后台任务复用应用队列及账户权限。没有原站 API 或部署身份依赖。

原站线上完整历史未迁入，原站仍保留；测试 seed 仅作规则回归，不能初始化生产日期。本地初始仅收录系列元信息，日期由官网核查获得。
