# WeChatDaily 与 Magic 微信群日报实现对照

核查日期：2026-10-27（Asia/Shanghai）。本次为源码研究，没有安装或运行对方程序，没有读取真实聊天、测试 Windows 兼容性或改动产品代码。

- 对方固定版本：[`88d261a3e9954e0ed44edb0a247260c509d0022e`](https://github.com/Bryan-Cyf/WeChatDaily/tree/88d261a3e9954e0ed44edb0a247260c509d0022e)。
- 本方：当前工作目录，HEAD `73d610704212bcc2cca5fdd4e32590bde3225d23`，包含用户已有未提交修改；不是对已发布 ZIP 的重新验收。
- 对方逐项源码证据见[上游研究笔记](2026-10-27-wechatdaily-upstream-research.md)。本方旧记录仅用于导航，下面结论以当前源码为准；README、PRODUCT 和部分历史契约的阶段说明不完全同步，不能直接代替当前实现。

## 结论

两者解决的是同一类需求，核心路线也相近：Windows 微信本地数据库 → 解密和消息解析 → 宿主 Agent 写结构化稿件 → HTML／可选图片。没有证据表明对方拥有可直接替换我们现有路线的自动出报基础设施。

对方偏向一次性聊天分析、统计和多种视觉产物；我们偏向已确认关注群的每日阅读、跨日归档与搜索，以及明确表达采集和稿件状态。建议借鉴分析查询、身份显示和去重策略，保留现有归档、验稿、阅读与初始化主线。

## 实现区别

| 环节 | WeChatDaily | Magic 微信群日报 |
|---|---|---|
| 入口 | 旧 `wechat.py` 日报入口，以及新增独立 Codex 分析 Skill，两套并存 | 一个 WorkBuddy Skill，工具模块围绕共同配置和归档协作 |
| 取钥与解密 | README 主流程要求外部 wx_key 取 raw_key；两条主分析路线使用 Python 页解密 | setup 调用本地取钥脚本；safe_decrypt 使用稳定副本、密钥核验、输出检查与替换；AES 优先 Windows CNG，后备 cryptography |
| 取消息 | 旧入口定位首个命中分片并有条数上限；新 Codex 入口遍历全部消息分片、无查询条数上限、显式去重 | 动态发现全部 message_N.db，按配置时区自然日采集；分片异常报告覆盖失败，不把部分结果当完整素材 |
| 数据身份 | 新 Codex 入口优先 server_id 去重，并优先群内名片显示 | 稳定群 ID；消息保留来源分片和 local_id 形成引用 ID；目前没有 server_id 去重，姓名主要取通讯录备注／昵称 |
| AI 职责 | 旧日报由 Agent 读 Markdown 写分析 JSON；新入口由 Python 统计、Agent 做语义分析与视觉生成 | WorkBuddy 当前模型读冻结 JSON，生成 story.json；采集、来源校验和渲染由工具负责 |
| 内容与验稿 | 旧模板含活跃排行、话题与金句；新入口增加人物／话题故事线、画像和多种视觉参考；未发现与本方等价的逐条引文绑定验稿器 | 写报道式故事线，保留 SOP／问答；check_story 检查素材版本、引文原句／作者／消息来源、字数及统计；不等于所有转述均经语义核验 |
| 持久阅读 | 主要输出 MD、JSON、HTML、PNG 等文件；主流程未提供与本方等价的多群日历和稿件状态服务 | JSON 冻结归档、SQLite 阅读索引、本机 Vue 阅读器；按日／群回看和关键词、日期、作者、类型组合搜索 |
| 失败和重跑 | 主分析流程没有本方这类持久采集覆盖与稿件素材版本记录 | 分开记录 collection/report；失败、成功零消息、素材不足分别表达；重采保留旧稿，素材变化标记 stale |
| 定时 | README 明确 Windows 计划任务主要导出 Markdown，完整日报依赖 Agent | 使用 WorkBuddy 本地任务调用完整 Skill；配置说明不等于宿主任务或到点运行已验收 |

对方旧、新入口必须分开评价。不能把旧 `query.py` 的首片读取问题概括成新 Codex 脚本的行为，也不能因新入口已遍历全部分片就断言所有入口都完整可靠。

上游入口证据：[README](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/README.md)、[旧查询](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/src/query.py)、[旧日报 Skill](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-group-daily-report/SKILL.md)、[新 Codex 分析脚本](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-analysis-forcodex/scripts/wechat_analysis.py)。

本方代码依据：[初始化与主流程](../../skills/wechat-group-daily/SKILL.md)、[消息读取](../../skills/wechat-group-daily/scripts/lib/wechat_data/messages.py)、[采集命令](../../skills/wechat-group-daily/scripts/fetch.py)、[素材与稿件状态](../../skills/wechat-group-daily/scripts/lib/wechat_data/collection.py)、[验稿](../../skills/wechat-group-daily/scripts/tools/check_story.py)、[阅读索引及搜索](../../skills/wechat-group-daily/scripts/lib/wechat_data/db.py)、[定时说明](../../skills/wechat-group-daily/references/scheduling.md)。

## 值得借鉴的部分

### 1. 人物／话题命中后带出上下文

新 Codex 脚本会围绕关键词／别名命中取前 8 条、后 12 条消息，并合并重叠窗口。它是检索辅助，最终故事线仍由 Agent 判断；存在窗口数量和文本裁剪上限，不能当作完整全量分析。

对我们的价值：当前搜索定位消息，但用户关心的常是“这个问题后来怎么处理”“某个人本周推动了什么”。可在现有归档／搜索上增加上下文读取，不另建取数系统；支持明确日期范围，输出命中、上下文、来源 ID 和截断说明。群内讨论仍只是项目状态的证据材料，不能自动宣称任务已完成。

### 2. 群内名片优先显示

同一个人在不同项目群可能有不同业务名片。可借鉴新脚本的群内显示名解析，同时保留 sender_id 和稳定群 ID。不要让显示名变化影响归档、引用匹配或同名消歧。

### 3. 消息级去重

本方当前 fetch 跨片拼接，引用用 `source_shard:local_id`，查询没有读取 server_id。对方新脚本的 server_id 优先策略可以作为候选。

先用合成库验证：同一有效 server_id 跨片重复、无效／缺失 server_id、同一人同秒重复发送相同文字、不同群相同 ID。保留来源证据，不能简单按“作者＋文本＋秒级时间”删除合法重复消息；引用 ID 与去重 ID 也不应混为一个字段。本次未证明用户实际库存在跨片重复。

### 4. 分清确定性统计和模型判断

对方新脚本使用 Counter 计算每日数量、小时分布和发言统计，话题、氛围与总结交给 Agent。这一分工可参考。但本方已有归档 stats 和验稿一致性检查，不需要重复建设统计层；若新增日期范围分析，复用现有确定性数据即可。

## 不建议直接搬入

- 活跃榜、全员标签或人物画像与我们当前“理解项目讨论”的目标不同，而且现有写作规范明确排除了发言榜和 Dashboard 堆砌。
- 生图风格、趣味群友画像可以作为独立探索，不应增加每日文本报告的默认依赖和成本。
- 两套主流程没有发现比本方更完整的冻结素材版本、采集覆盖、失败后保留旧稿与验稿机制，不建议替换这些部分。
- 大群处理主要仍依赖提示 Agent 分批阅读，没有看到可直接移植的 token 预算、分块汇总及覆盖验收方案。
- 主分析解密流程未解决加密 WAL 合并；我们当前也仅诊断 WAL，真实消息覆盖仍需 Windows 核查。不能把读取时间较新或 SQLite 可打开等同于微信消息完整。
- 我们已有可选语音模块；对方附带的第三方工具含语音等能力，不代表本方完全缺少，也不代表日报主线已经自动识别附件。

## 建议顺序与验证边界

先完成本方 Windows 首报和真实定时运行反馈；下一步优先考虑“搜索结果带上下文”和群内名片，再研究去重与跨日专题分析。本次只记录候选方向，没有实施、创建票据或扩大现有开发范围。

不以源码功能数比较稳定性。本方已有公共 CLI／HTTP 和合成输入检查记录，但本次未重跑测试；对方代码也没有运行。双方在具体 Windows／微信版本、活库覆盖、模型内容质量和无人值守运行上的差异，仍需要相同环境和数据范围的实测才能下结论。
