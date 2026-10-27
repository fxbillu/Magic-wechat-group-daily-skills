# WeChatDaily 上游源码研究

日期：2026-10-27。研究对象：Bryan-Cyf/WeChatDaily。仅阅读公开源码，未安装、执行上游代码，也未接触真实聊天数据。

固定版本：`88d261a3e9954e0ed44edb0a247260c509d0022e`；本次查询的 master HEAD，提交日期 2026-07-03。以下结论均限定该版本。当前仓库比较与产品建议由主评审另行汇总。

## 结论

它与我们的产品目标高度重叠，主要路线也是 Windows 微信本地数据库解密，加宿主 Coding Agent 总结；没有发现一种绕开微信密钥或数据库兼容性的全新采集方法。

需要区分两套代码：README 主要介绍旧日报流程，但 HEAD 另外包含独立 Codex 分析 Skill。后者已经补上跨消息库合并去重、日期区间、群名片、人物或话题素材提取，不能把旧入口的限制概括为整个项目的能力。

## 1. 两套实现

| 范围 | README 日报流程 | 独立 Codex 分析 Skill |
| --- | --- | --- |
| 入口 | `wechat.py` + `.claude/skills/wechat-group-daily-report/`，另有内容相同的 `skills/wechat-group-daily-report/` | `skills/wechat-analysis-forcodex/scripts/wechat_analysis.py` |
| 采集 | wx_key 提供 raw_key，setup 生成密钥清单，Python 解密为 SQLite | 同样依赖外部 raw_key；Skill 本身不分发 wx_key，脚本可独立运行 |
| 查询 | 指定群、指定自然日；默认每群最近 1000 条，Skill 传 99999 | 群聊或私聊、日期区间；查询本身不设消息条数上限 |
| 跨库 | 找到首个 `Msg_<md5>` 表即返回，只读该库 | 遍历全部 `message_*.db` 合并后去重 |
| 产物 | Markdown 原始材料 → Agent 分析 JSON → HTML + 可选 PNG | Markdown + 统计 JSON；Agent 另做总结、故事线、生图 |
| 输出风格 | 固定 HTML 日报 | 多套参考提示词；Codex 内置 image_gen 生成图片 |
| 状态 | 文件输出及简单命令返回码 | 独立工作目录、doctor 和 JSON CLI 输出；仍未见日报流水线的持久作业状态 |

来源：[旧 CLI 导出与参数](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/wechat.py#L340-L428)、[旧查询首表返回](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/src/query.py#L89-L100)、[独立 Skill](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-analysis-forcodex/SKILL.md#L8-L95)。

## 2. 采集、平台与解密边界

- README 声明 Windows、微信 4.1+、Python 3.14+；这是上游声明，本次未验证兼容矩阵。顶层 `requirements.txt` 为未锁版本的 pycryptodome、playwright。独立 Codex Skill 说明仅需 pycryptodome，不应把 README 的所有依赖都强加给独立脚本。
- 主路线由用户运行 wx_key v2.1.8，把 raw_key 放进 `.env`；Python 使用 PBKDF2-HMAC-SHA512 派生页面密钥并 AES-CBC 解密，第一页 HMAC 验证成功后写出整个文件。
- 主流程 `src/decrypt.py` 与独立脚本的解密函数均直接读源 `.db`，直接覆盖解密文件。所读函数未见源库稳定快照、加密 WAL 回放、临时文件完成后原子替换、全库完整性验收或按库新鲜度状态。仅第一页 HMAC 校验不能等同于全库无缺失。
- setup 先验证一个库的 raw_key，再为扫描到的各库记录相同 raw_key；解密时又从清单取首个 enc_key 应用于所有库。这与对每库独立 key 的工具路线有区别。

来源：[README 环境与安装](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/README.md)、[主解密实现](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/src/decrypt.py#L46-L125)、[密钥生成](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/src/keys.py#L41-L79)、[独立解密实现](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-analysis-forcodex/scripts/wechat_analysis.py#L227-L337)。

单独的第三方辅助脚本 `tools/wechat-decrypt/decrypt_db.py` 确有 `--incremental`：仅当源 `.db` 的 mtime 晚于输出文件才重新解密，并查询 sqlite_master 检验能否打开。这个参数没有接入上述两个主解密入口；它是按文件跳过，不是按消息增量。只看 `.db` mtime 不能证明 WAL 内没有新数据，源码中的 WAL 删除是清理输出端验证残留文件，不是回放源 WAL。还需注意该辅助脚本使用直接 enc_key 及其自己的密钥约定，不能直接假设与主入口 raw_key 等价。[辅助解密脚本](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/tools/wechat-decrypt/decrypt_db.py#L109-L237)

## 3. 新 Codex 脚本真正可借鉴的部分

### 跨库合并去重

`query_raw_messages()` 遍历所有 `message_*.db` 中同一会话表，记录 `_source_db`，优先以非零 `server_id` 为键；缺失时用 `(local_id, create_time, real_sender_id, sha_content(message_content))`。最终按时间和 local_id 排序。

借鉴价值是避免搬迁、同步或重复分片让同一消息进入两次统计。落地需验证 server_id 在本方目标版本及会话内的有效性，保留重复记录的来源，明确冲突优先级。上游遇到重复键时是后遍历的记录覆盖前者；备用组合键含本地 ID，可能漏掉本地 ID 已变化的同消息，也可能在不同库恰好各字段相同时合并不同记录。不能直接以“内容相同”去重群成员重复发送的消息。

[具体实现 770–820 行](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-analysis-forcodex/scripts/wechat_analysis.py#L770-L820)

### 群名片和有歧义的会话选择

`load_group_member_display_map()` 使用 contact.db 的成员 ID 映射，查询 contact_fts.db 中 `chatroom_member_fts_v3` 的 room_id/member_id/a_group_remark。导出把群名片覆盖全局联系人名称。这有助于让报告中的称呼与群内可见名称一致，但依赖具体表结构，必须保留回退策略。

旧 CLI 模糊群名命中多项时会选第一个；新 `find_chat()` 返回候选，`cmd_export()` 在无法唯一匹配时以错误码 2 退出。新实现更适合参考。

[群名片实现 434–482 行](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-analysis-forcodex/scripts/wechat_analysis.py#L434-L482)、[会话选择 591–644 行](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-analysis-forcodex/scripts/wechat_analysis.py#L591-L644)、[导出中的名称合并 1299–1326 行](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-analysis-forcodex/scripts/wechat_analysis.py#L1299-L1326)

### 人物、话题与上下文窗口

新 `story` 命令按人物名/别名或话题关键词命中消息，取前 8 后 12 条上下文，合并重叠窗口，最多 180 个窗口，单条序列化文本最多 260 字。它输出的是后续供 Agent 阅读的材料，而非代码完成语义事件识别。

可借鉴“带上下文地找材料”，尤其适合跨日人物/事件追踪；当前数量和字符截断不能当完整性保证，窗口按条数而不是时间跨度，固定关键词分类也不能替代模型理解。

[命中与窗口实现 960–1114 行](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-analysis-forcodex/scripts/wechat_analysis.py#L960-L1114)

### 确定性统计与 Agent 分析分工

Python `Counter` 计算 message_count、by_day、by_hour、top_senders，列出 source_dbs 和材料路径。人物资料来自联系人结构，非由模型猜性别。语义话题、整体氛围、总结和图片内容则由宿主 Agent 处理。

旧 HTML 日报同样用 Python 算总消息、人数、时段和排名，Agent JSON 只负责 summary/topics/user_titles。这个边界清楚，但 old renderer 会重新从 Markdown 正则解析消息；不匹配格式或多行正文可能造成渲染统计与源导出数偏差，正式实现更适合直接用结构化数据。

[独立统计 1168–1228 行](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-analysis-forcodex/scripts/wechat_analysis.py#L1168-L1228)、[旧报告统计](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/src/visual_report.py#L32-L48)、[Markdown 反向解析](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/scripts/render_manual_report.py#L384-L414)

## 4. 生成、调度与运行成熟度

- 它和我们一样可以借助宿主 Agent，无需单独配置 LLM API Key；不能把“无需 API Key”当成独有优势，也不能据此推断聊天不会进入云端模型。
- 原日报 Prompt 要求语义聚合、每主题简短证据、真实发言者和非攻击性称号；输出校验主要是 Agent 自检 JSON 可解析与字段。未见把每条摘录严格绑定到原始消息 ID 和作者的程序校验。
- 大群只要求分批阅读 Markdown，未见 token 预算、自动切块、分块摘要合并或全天覆盖率检查。
- `run_report.ps1` 仅调用 `wechat.py export` 并追加日志。README 明确 Windows 计划任务只能导出 Markdown，完整 HTML 日报仍需 Agent 分析。未见主线的无人值守 Agent 调度、日报推送、失败重试和补偿流水线。
- 原日报 Skill 即便用户已给群、日期、刷新倾向，也强制逐项再次确认。适合避免误选，却不适合直接迁移到已配置的每天自动运行流程。
- 静态 HTML 及 PNG 长图便于分享；新 Codex Skill 的内置生图及多风格提示词是另一输出通道，不是已经实现的 reader/归档服务。
- 读取的顶层树未发现本项目测试目录或 CI 工作流；第三方目录有 latency_test.py，不能当项目完整验收证据。本次没有实际运行，无法确认真实 Windows 首次安装、数据完整性及每日运行可靠性。

来源：[原 Skill 全流程](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/.claude/skills/wechat-group-daily-report/SKILL.md#L30-L172)、[分析 Prompt](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/.claude/skills/wechat-group-daily-report/references/analysis-prompt.md)、[运行脚本](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/run_report.ps1)、[Codex 生图规则](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-analysis-forcodex/SKILL.md#L138-L185)。

## 5. 安全与复用边界

- 本项目 LICENSE 为 MIT；wx_key 单独许可，README 也明确区分。不能以本项目 MIT 推断第三方工具可随本方重新打包分发。
- 主流程密钥、明文库和导出在本地文件；`.gitignore` 排除 .env、export 等。独立 Codex Skill 把私有工作目录与 Skill 源码目录分开，这一点适合保留。
- wx_key 下载清单固定版本与上游 Release URL，但清单未提供 SHA256；下载后主要检查 exe 存在，不是完整的供应链完整性校验。
- 不建议直接替换本方采集/解密层；先借鉴跨库重复处理、群名片优先与人物/事件检索交互，并沿用本方已有完整性、证据引用和验收边界。

来源：[MIT](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/LICENSE)、[wx_key 清单](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/tools/wx_key.manifest.json)、[下载与解包](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/wechat.py#L195-L293)、[独立工作目录](https://github.com/Bryan-Cyf/WeChatDaily/blob/88d261a3e9954e0ed44edb0a247260c509d0022e/skills/wechat-analysis-forcodex/SKILL.md#L26-L36)。
