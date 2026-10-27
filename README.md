# Magic 微信群日报 Skill

当前版本：**1.3.0-rc.2，Windows / WorkBuddy 测试候选**。

在保存微信记录的 Windows 电脑上，由 WorkBuddy 对话带你确认账号、包外数据目录、关注群和每日时间；每个群每天独立出报，本地网页按日期和群回看。朋友和团队伙伴各自安装、各自使用自己的数据。

## Windows 开始测试

1. 下载本仓库候选 Release 中的 `Magic-wechat-group-daily-1.3.0-rc.2.zip`，在 WorkBuddy 导入 Skill。
2. 在对话中说：**请使用微信群日报 Skill，带我完成首次初始化，选群并生成昨天的一份日报。**
3. 首报可读后，按 [每日任务说明](skills/wechat-group-daily/references/scheduling.md) 创建或更新已有的 WorkBuddy 本地定时任务。
4. 将失败步骤、脱敏错误码和结果反馈给维护者。详见 [Windows 试用说明](skills/wechat-group-daily/references/windows-acceptance.md)。

电脑需开机、不休眠且 WorkBuddy 运行。配置、密钥、聊天和日报保存在包外；升级前先备份自己的配置和数据。已有可用任务先核对、复用，避免重复创建。

本候选已完成开发侧本地验证，Windows 真实取数、模型产稿、PNG 与实际到点运行等待用户本机测试。WAL 只作待核实诊断，不作为尝试原已验证路径的额外门槛。

## 桌面入口

Windows 初始化保存配置时，自动创建带报纸图标的 **Magic 群日报** 桌面快捷方式。重复初始化只更新这一个快捷方式，不生成副本；双击自动启动或复用本地服务，优先以 Edge/Chrome 独立阅读窗口打开。也可在 WorkBuddy 运行 `tools/desktop.py install` 重建。图标和快捷方式均留在包外用户目录。

仓库：[Magic-wechat-group-daily-skills](https://github.com/fxbillu/Magic-wechat-group-daily-skills)，公开源码；内部 Skill ID 和用户数据位置保持兼容。

## 开发与验证

正式源码在 `skills/wechat-group-daily/`。根测试仅使用合成数据，不依赖旧备份。

```bash
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
node --check skills/wechat-group-daily/scripts/web/app.js
python3 -B skills/wechat-group-daily/scripts/tools/package.py
```

- [读取契约](docs/contracts/read-api-v1.md)、[开发记录](docs/dev-log.md)、[开发主计划](docs/plans/2026-10-26-development-plan.md)
- [产品上下文](PRODUCT.md)、[视觉基线](DESIGN.md)
- [依赖能力](skills/wechat-group-daily/references/dependencies.md)、[第三方来源与许可](skills/wechat-group-daily/references/third-party.md)

原始导入仅保存在本地忽略目录 `legacy-import/`，不提交或进入 Skill ZIP。完整前端和所需程序按显式清单打包，未知文件与个人状态阻断出包。
