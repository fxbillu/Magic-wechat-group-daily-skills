# 微信群日报 Skill

在自己的 Windows 电脑上，由 WorkBuddy 对话初始化、选择关注群并安排日报；本地网页按日期和群阅读结果。每位朋友或团队伙伴独立安装、使用自己的配置和数据。

当前为 **T0 开发基线，不是可交付发行版**。它保留旧版程序并建立干净源码、状态接口和合成测试；[审查报告](docs/reviews/2026-10-26-import-review.md)中列出的数据、初始化、历史查询及打包缺陷仍由 T1–T5 逐项处理。真实 Windows 取数与定时任务尚未验收。

## 导航

- [开发主计划](docs/plans/2026-10-26-development-plan.md)：需求、依赖与验收。
- [读取契约 v1](docs/contracts/read-api-v1.md)：前后端共同状态与配置发现规则，标明已实现和待实现项。
- [产品上下文](PRODUCT.md)、[现有视觉基线](DESIGN.md)：前端与 Impeccable 的共同输入。
- [技能源码](skills/wechat-group-daily/)：未来出包的来源，不包含用户配置和原始聊天。
- [合成测试](tests/)：仅测试数据，不需要旧备份、微信或 WorkBuddy。

## 本地开发

基础验证只需 Python 3.11+ 标准库；前端语法检查使用 Node。Windows 取数与旧可选能力的依赖尚待 T2/T5 整理为经验证的兼容清单，不能从这条开发要求推断解密兼容范围。

```bash
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
node --check skills/wechat-group-daily/scripts/web/app.js
python3 -B skills/wechat-group-daily/scripts/tools/serve.py --port 8765
```

然后打开 `http://127.0.0.1:8765/`。没有个人配置时，页面显示 WorkBuddy 初始化指引；业务读取接口返回明确未就绪状态，不生成配置或数据目录。服务支持 `--port 0` 自动分配端口并打印实际地址；`--open` 可启动浏览器。

配置默认位于 Windows `%LOCALAPPDATA%\WeChatGroupDaily\config.json`。开发平台默认 `${XDG_CONFIG_HOME:-~/.config}/wechat-group-daily/config.json`。`WECHAT_DAILY_CONFIG` 可指定隔离测试用的配置文件；不要把它设到源码或技能包内。旧包内配置不会自动迁入，完整初始化与迁移属于 T2。

## 并行工作边界

- 后端：Python 工具、数据层、初始化与 Skill 引导；相关测试建议使用 `tests/test_backend_*.py`。
- 前端：`scripts/web/`，前端验证使用 `tests/frontend/`。
- 发布：打包工具、清单和 `tests/test_package.py`，独立检查业务实现。
- 主控：共享契约、`tests/fixtures/`、公共测试支持、集成和验收。边界调整先由主控确认，避免两个对话覆盖同一文件。

`tests/test_readiness.py` 属于 T0 共同入口验收。每个测试会复制正式 Skill 到临时安装目录，隔离配置并启动真实服务；不导入产品私有函数来断言行为。

## 出包前仍需完成

可靠多群采集、首次完整出报、历史查询修复、宿主任务回读/实际触发、失败恢复、升级迁移与第二台 Windows 安装。当前旧打包器有已知缺陷，不能把其通过当作发布许可。

依赖与许可清单也尚未完成：内置 Vue 保留 MIT 版权头，但发行时仍需补齐许可全文；取钥相关上游代码来源与许可须在 T5 核对。最终只提交干净源码并从白名单生成 ZIP，配置、密钥、明文快照、归档、日报与日志始终保存在包外。

旧导入数据仅保留在本地被忽略的 `legacy-import/`；正式源码和测试可以在没有它的全新 checkout 中运行。
