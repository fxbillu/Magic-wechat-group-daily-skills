<p align="center">
  <img src="assets/readme/hero.svg" width="100%" alt="微信群日报：由 Windows 上的 WorkBuddy 整理关注群，每群独立成篇，按日期与群回看。">
</p>

# Magic 微信群日报

把关注群，读成一份日报。

选择多个微信群，由你 Windows 电脑上的 WorkBuddy 在选定时间每天整理成独立日报；按日期看多群，按群看历史，也能组合搜索。配置、密钥和归档文件保存在本机的包外目录。

**Windows · WorkBuddy · 1.3.0-rc.9 Windows 测试候选**

[复制安装提示词](#安装与更新) · [下载候选 ZIP](https://github.com/fxbillu/Magic-wechat-group-daily-skills/releases/tag/v1.3.0-rc.9) · [Windows 试用说明](skills/wechat-group-daily/references/windows-acceptance.md)

新版保留「今日故事」的大标题与首字下沉导语，随后是实算活跃统计、主要话题和待确认事项，再读完整故事线；日期和实际时间范围只在报头显示一次。人物动态、原文金句和搜索前后文都可核对来源，沿用原配置与历史。

## 为什么做这个项目

每天在微信里来回切换不同的项目群，消息很多，项目的进展、问题和待跟进事项却散落在各段对话里。即使经常看群，也很难对整体项目进度有一个清楚的把控。

所以做了这套日报，把关注群每天的讨论整理下来，方便回看，也作为项目进度同步的素材。**目前开源的只有微信群日报部分**，包含按群生成日报、阅读、历史回看和搜索；更完整的项目进度整合与同步不在本次开源范围内。日报反映的是群内讨论，项目的实际进度和完成情况仍需相关负责人确认。

## 界面示例

<a href="assets/readme/daily-overview.png"><img src="assets/readme/daily-overview.png" width="100%" alt="本地阅读器的多群日报列表：分别展示采集结果、可读日报与旧稿待更新状态。截图全部使用合成数据。"></a>

*截图来自程序的合成数据浏览检查，用于展示界面；不是真实微信群或 Windows 运行证明。可点击查看原图。*

<a href="assets/readme/overview-first.png"><img src="assets/readme/overview-first.png" width="100%" alt="rc.8 日报恢复今日故事、大标题和首字下沉导语，随后展示活跃统计与主要话题；全部为合成示例。"></a>

*rc.8 今日故事开场与总览，由正式渲染器生成，示例人员与群聊均为虚构。*

| 日常要做的事 | 在这里怎么完成 |
| --- | --- |
| 只关注重要的群 | 在 WorkBuddy 对话里确认账号与群；同名群按稳定身份区分 |
| 读完昨天的讨论 | 每群每天独立成篇，先核对引文和发言人，再生成 HTML／可选 PNG |
| 找回某天、某群的内容 | 按日期、群和关键词回看；重采后仍保留可读旧稿 |

## 使用边界与数据处理

1. **只处理有权处理的数据。** 在本人设备上使用本人账号，确认群聊导出、分析、向模型提供及分享所需的权限，并遵守群内约定和组织的数据管理要求。不得未经授权访问他人数据或用于侵害他人权益的行为。
2. **归档按所选群保存，解密范围可能更大。** 配置、密钥、解密数据库、归档和日报保存在本机包外目录。日报归档只保存所选群指定时间范围的消息；底层按共享数据库分片解密，明文数据库可能包含其他会话。历史文件不自动到期删除，需按配置目录自行备份和清理。
3. **模型处理取决于宿主配置。** WorkBuddy 整理日报时，聊天内容或片段可能发送至云端模型服务；传输、留存和使用方式以所用服务的条款与设置为准。处理前请确认相应权限和数据处理方式，本机保存不代表全程离线。
4. **分享和反馈前脱敏。** 聊天、日报和截图可能包含成员身份、联系方式或保密信息。分享前请取得必要授权并脱敏；反馈问题时不要提交密钥、个人配置、原始数据库或未经处理的聊天记录。

## 安装与更新

打开 Windows 上的 WorkBuddy，复制下面这段即可。安装、加载与更新的执行细节已[内置到 Skill](skills/wechat-group-daily/references/install-and-update.md)。

```text
请安装并使用这个项目：
https://github.com/fxbillu/Magic-wechat-group-daily-skills

按照仓库说明加载微信群日报 Skill，带我完成初始化、生成首份日报，并配置每日任务。已有安装则更新，保留原配置和历史。
```

也可以下载 [候选 ZIP](https://github.com/fxbillu/Magic-wechat-group-daily-skills/releases/tag/v1.3.0-rc.9) 导入 WorkBuddy。

## 桌面快捷方式

Windows 初始化保存配置时，会创建带报纸图标的 **Magic 群日报** 桌面快捷方式。重复初始化或恢复会更新同一个入口，不生成副本。双击自动启动或复用本地阅读服务，优先以 Edge/Chrome 独立窗口打开。

如需重建，在 WorkBuddy 使用同一 Python 执行 `tools/desktop.py install`。快捷方式和图标保存在本机包外目录，不上传到 GitHub；未初始化也可打开阅读指引。

## 每天只出一次

时间由使用者设置，推荐 21:00；每个关注群每天最多一份。统计从该群上次成功处理截止点到本次计划截止点的消息，报头标明真实起止时刻。失败重试复用原窗口，消息不够成篇时如实记录；截止后的消息进入下一份。更新现有同一条任务，不再单独运行早报、晚间采集或包外 next_range.py。

## 第一次跑通，看这三件事

1. **确认用对数据。** 本人账号、关注群、时区和包外目录正确；首次建议先试 1—2 个群。
2. **打开一份实际日报。** 先生成当前接续窗口的 HTML，核对话题、引文和署名。无消息、素材不足与失败分别说明。
3. **核对每天的任务。** 首报可读后，再按 [配置与复建指引](skills/wechat-group-daily/references/scheduling.md) 创建或更新 WorkBuddy 本地任务。

任务运行时电脑需开机、不休眠，WorkBuddy 保持运行；微信数据应能按本机现有流程读取。手动试跑和真正到点执行是两项结果。

## 以后怎么更新

对 WorkBuddy 说 **“更新 Magic 微信群日报”**。Skill 按本机安装记录更新程序，保留个人配置、历史和已有任务。

## 当前验证范围

rc.9 仅更新使用边界与免责声明，检查及安装包结果见 [rc.9 验证记录](docs/verification/1.3.0-rc.9.md)。开场、响应式和此前公共检查见 [rc.8 记录](docs/verification/1.3.0-rc.8.md)，完整页面联调见 [rc.6 记录](docs/verification/1.3.0-rc.6.md)，来源、许可和 Windows 修复验证见 [rc.7 记录](docs/verification/1.3.0-rc.7.md)。此前完整检查的一项可选 Pillow 检查跳过。

默认跳过不需要的 FTS 库，仅额外尝试群内名片所需的可选联系人索引，失败回退原名称；保留 rc.3 的核心库解密与恢复能力。程序按核心库结果判断解密成功，并支持跨盘目录和中断临时文件回收。数据库层仍按共享消息分片解密，归档仅保存所选群的指定日期；旧版无归属临时文件和历史日报不会自动删除。

**Windows 真实微信取数、模型首报、PNG 和实际到点执行，仍由使用者在本机反馈。** WAL 仅记录诊断并沿用原路径，不一刀切阻断；新版 HTML 日报支持窄屏单列；旧版历史 HTML 沿用原有排版，可单独打开阅读。

rc.5 的每日一次路径已通过三个聚焦 CLI 场景：时间边界/重复与出报、首次失败后接续、旧归档及旧日报保留。Windows 安装后，请以真实取数、打开 HTML/PNG 和历史回看确认可用，无需先安装 pytest 或运行开发测试。

## 免责声明

完整 [使用边界、数据处理与免责声明](skills/wechat-group-daily/DISCLAIMER.md) 已随安装包提供，可离线阅读。

本项目是独立的社区项目，非微信、WeChat 或 WorkBuddy 官方产品，与腾讯及相关服务提供方无隶属或背书关系。相关名称和商标归各自权利人所有。数据读取方式受[微信等平台协议](https://oper.my-qcloud.com/cgi-bin/readtemplate?lang=zh_CN&s=default&t=weixin_agreement)约束，本项目不提供平台授权，也不保证账号或服务不受限制。

项目按现状提供，在适用法律允许的范围内不作 MIT 许可证所列保证。兼容性、消息完整性、日报准确性和任务执行会受软件版本及运行环境影响。AI 总结可能遗漏或误解，引用、署名、项目状态及重要结论需核对原始消息；人物分析不应作为能力、信誉、性格或绩效评价。

请遵守适用法律法规，妥善保管密钥和本地数据。本说明不增加 MIT 软件许可的限制，不替代数据或平台授权，也不改变各方依法应承担的责任。第三方组件的许可见下文。

## 许可证与第三方来源

本项目自有代码与文档采用 [MIT 许可证](LICENSE)：允许使用、修改、分发和商业使用，须保留版权及许可声明；不提供许可证所列保证。版权标识为 fxbillu and Magic WeChat Group Daily contributors。

第三方组件保留各自版权及许可，见 [NOTICE](NOTICE.md) 和 [来源清单](skills/wechat-group-daily/references/third-party.md)。Vue、wcdb-key-tool 和 WeChatDaily 的 MIT 文本均随包提供；可选语音 pilk 使用 GPLv3，运行库和模型不随包分发，不能把完整语音环境统称为 MIT。软件许可不授予聊天内容、账号、商标或第三方服务的权利。

[来源与开发过程审查](docs/reviews/2026-10-27-license-audit.md) 记录了导入哈希、Git 开发、第三方比对和维护者授权依据；旧电脑上未留存的初始生成记录不能据此补证。rc.7 补齐随包声明与打包检查，保留 rc.6 功能、原配置和历史。

## 开发与文档

正式 Skill：[`skills/wechat-group-daily/`](skills/wechat-group-daily/)；测试仅使用合成数据。

```bash
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
node --check skills/wechat-group-daily/scripts/web/app.js
python3 -B skills/wechat-group-daily/scripts/tools/package.py
```

[产品上下文](PRODUCT.md) · [视觉基线](DESIGN.md) · [读取契约](docs/contracts/read-api-v1.md) · [开发记录](docs/dev-log.md) · [依赖能力](skills/wechat-group-daily/references/dependencies.md) · [第三方来源与许可](skills/wechat-group-daily/references/third-party.md)

个人配置、密钥、聊天、日报及本地导入备份均不进入 Skill ZIP；程序和完整前端按显式清单出包。每位使用者使用自己的数据和任务。
