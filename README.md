<p align="center">
  <img src="assets/readme/hero.svg" width="100%" alt="微信群日报：由 Windows 上的 WorkBuddy 整理关注群，每群独立成篇，按日期与群回看。">
</p>

# Magic 微信群日报

把关注群，读成一份日报。

选择多个微信群，由你 Windows 电脑上的 WorkBuddy 每天整理成独立日报；按日期看多群，按群看历史，也能组合搜索。配置、密钥和归档文件保存在本机的包外目录。

**Windows · WorkBuddy · 1.3.0-rc.2 测试候选**

[复制安装提示词](#安装与更新) · [下载候选 ZIP](https://github.com/fxbillu/Magic-wechat-group-daily-skills/releases/tag/v1.3.0-rc.2) · [Windows 试用说明](skills/wechat-group-daily/references/windows-acceptance.md)

## 界面示例

<a href="assets/readme/daily-overview.png"><img src="assets/readme/daily-overview.png" width="100%" alt="本地阅读器的多群日报列表：分别展示采集结果、可读日报与旧稿待更新状态。截图全部使用合成数据。"></a>

*截图来自程序的合成数据浏览检查，用于展示界面；不是真实微信群或 Windows 运行证明。可点击查看原图。*

| 日常要做的事 | 在这里怎么完成 |
| --- | --- |
| 只关注重要的群 | 在 WorkBuddy 对话里确认账号与群；同名群按稳定身份区分 |
| 读完昨天的讨论 | 每群每天独立成篇，先核对引文和发言人，再生成 HTML／可选 PNG |
| 找回某天、某群的内容 | 按日期、群和关键词回看；重采后仍保留可读旧稿 |

## 安装与更新

打开 Windows 上的 WorkBuddy，复制下面这段即可。安装、加载与更新的执行细节已[内置到 Skill](skills/wechat-group-daily/references/install-and-update.md)。

```text
请安装并使用这个项目：
https://github.com/fxbillu/Magic-wechat-group-daily-skills

按照仓库说明加载微信群日报 Skill，带我完成初始化、生成首份日报，并配置每日任务。已有安装则更新，保留原配置和历史。
```

也可以下载 [候选 ZIP](https://github.com/fxbillu/Magic-wechat-group-daily-skills/releases/tag/v1.3.0-rc.2) 导入 WorkBuddy。

## 桌面快捷方式

Windows 初始化保存配置时，会创建带报纸图标的 **Magic 群日报** 桌面快捷方式。重复初始化或恢复会更新同一个入口，不生成副本。双击自动启动或复用本地阅读服务，优先以 Edge/Chrome 独立窗口打开。

如需重建，在 WorkBuddy 使用同一 Python 执行 `tools/desktop.py install`。快捷方式和图标保存在本机包外目录，不上传到 GitHub；未初始化也可打开阅读指引。

## 第一次跑通，看这三件事

1. **确认用对数据。** 本人账号、关注群、时区和包外目录正确；首次建议先试 1—2 个群。
2. **打开一份实际日报。** 先生成昨天的 HTML，核对话题、引文和署名。无消息、素材不足与失败分别说明。
3. **核对每天的任务。** 首报可读后，再按 [配置与复建指引](skills/wechat-group-daily/references/scheduling.md) 创建或更新 WorkBuddy 本地任务。

任务运行时电脑需开机、不休眠，WorkBuddy 保持运行；微信数据应能按本机现有流程读取。手动试跑和真正到点执行是两项结果。

## 以后怎么更新

对 WorkBuddy 说 **“更新 Magic 微信群日报”**。Skill 按本机安装记录更新程序，保留个人配置、历史和已有任务。

## 当前验证范围

开发侧已完成必要修复与前后端联调。候选版的 59 项公共检查中，58 项通过、1 项可选 Pillow 检查跳过；真实 Python API 到页面的关键流程通过合成输入验证。

**Windows 真实微信取数、模型首报、PNG 和实际到点执行，仍由使用者在本机反馈。** WAL 仅记录诊断并沿用原路径，不一刀切阻断；窄窗口里的 HTML 报纸可能需要横向滚动，可单独打开阅读。

## 开发与文档

正式 Skill：[`skills/wechat-group-daily/`](skills/wechat-group-daily/)；测试仅使用合成数据。

```bash
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
node --check skills/wechat-group-daily/scripts/web/app.js
python3 -B skills/wechat-group-daily/scripts/tools/package.py
```

[产品上下文](PRODUCT.md) · [视觉基线](DESIGN.md) · [读取契约](docs/contracts/read-api-v1.md) · [开发记录](docs/dev-log.md) · [依赖能力](skills/wechat-group-daily/references/dependencies.md) · [第三方来源与许可](skills/wechat-group-daily/references/third-party.md)

个人配置、密钥、聊天、日报及本地导入备份均不进入 Skill ZIP；程序和完整前端按显式清单出包。每位使用者使用自己的数据和任务。
