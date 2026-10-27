# 搜索上下文、群内名片与分析验证

日期：2026-10-27。对象：当前工作目录的未发布增量，继续使用原采集、冻结归档、宿主写稿和本地阅读流程。输入全部为合成数据；没有访问真实微信或调用模型生成分析。

## 已实现

- 搜索结果按需展开同群同日的前 8 条／后 12 条消息，保留其他人的回复，标记命中及归档边界。可组合人物名片／姓名或稳定用户 ID 筛选，URL 刷新后保留条件。
- 采集优先群内名片，以稳定成员 ID 区分同名人物。缺失或不兼容的可选名片库回退原名称；只额外尝试联系人名片库，不恢复所有可选 FTS 的默认解密。
- 活跃统计由冻结素材计算：总消息、发言人数、文本字数、时段分布和发言量／占比。旧稿可正常阅读；新日报加入活跃统计与可选金句、话题、人物栏目。
- `fetch.py analyze` 只读归档，支持日期范围及人物／话题命中窗口。窗口合并，命中截断、缺失日期和最新采集失败明确表达。
- 宿主在 `analysis.topics/people/quotes` 写语义内容，验稿及渲染核对来源。读者可展开原文核对；重采后来源版本变化则分析为 stale，不把旧分析当当前结论。

## 实际执行

| 检查 | 结果与范围 |
|---|---|
| `python3 -B -m unittest discover -s tests -p 'test_*.py' -v` | 74 项，73 通过，1 项 Pillow 可选能力跳过。包括新增 6 项公共 CLI／真实 HTTP 验收 |
| `python3 -B -m unittest discover -s tests/frontend -p 'test_analysis_api.py' -v` | 1 项通过，实际 CLI → Python HTTP → Ego 浏览器；1280/390px、人物筛选、上下文、分析来源、键盘折叠和无页面横向溢出 |
| `python3 -B -m unittest discover -s tests/frontend -p 'test_real_api.py' -v` | 原有 4 项全部通过，覆盖同名群、改名、零消息、失败、旧稿、重建索引、搜索组合筛选、键盘导航和取消关注后历史 |
| 最后一次来源投影收紧后的新增后端检查 | 重新运行 `test_backend_analysis.py`，6 项通过；金句只按单条 source_id 渲染证据，忽略不属于金句结构的 source_ids |
| Node 语法、静态 release inventory、Markdown 引用与空白 | 通过。新模块与说明已列入显式发布清单，没有创建或上传新版 ZIP |
| Impeccable mechanical detector | 对改动 JS/CSS 返回 `[]`；结合实际截图检查，不把扫描等同视觉验收 |

Ego 初次在默认 macOS 沙箱内无法启动；获得 GUI 访问后测试通过。该失败属于环境访问，没有忽略产品断言。所有浏览器测试的临时服务和浏览器空间均已关闭。

## 截图与入口

- [390px 搜索上下文](../../tests/frontend/evidence/analysis-2026-10-27/context-390.png)
- [390px 活跃统计和来源分析](../../tests/frontend/evidence/analysis-2026-10-27/analysis-390.png)
- [1280px 分析与原文证据](../../tests/frontend/evidence/analysis-2026-10-27/analysis-1280.png)
- [Skill 使用说明与 story.json 结构](../../skills/wechat-group-daily/references/analysis.md)
- [读取 API 契约](../contracts/read-api-v1.md)

截图展示程序读取合成归档和人工编写的合成分析，不是实际群聊、真实模型质量或 Windows 运行证明。

## 仍需真实环境确认

Windows 微信版本的群名片表结构和密钥可读性、真实模型的语义准确性与人物归因、实际 HTML／PNG 的最终内容，以及原有 WorkBuddy 到点运行，仍需使用者本机验证。新功能没有声称完成这些验收，也没有改变现有任务调度或对消息完整性的边界。
