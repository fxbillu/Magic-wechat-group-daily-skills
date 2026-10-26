# T1 前端状态与 T3 阅读准备验证

日期：2026-10-27（Asia/Shanghai）。关联：[#3 T1](https://github.com/fxbillu/wechat-group-daily-skills/issues/3)、[#5 T3](https://github.com/fxbillu/wechat-group-daily-skills/issues/5)。共同基线：`1bef2b65624f7f6dd7d4273ce30cfa4cc8bc2884`。

## 范围与结果

本轮完成可集成的前端增量，以[读取契约 v1](../contracts/read-api-v1.md)的 `collection` 与 `report` 为依据。**合成 HTTP 同伴验证通过，真实 Python API 联调和跨层票据验收仍待主控安排，T1/T3 均不因本记录而完成。**

- 日期、最近列表、群历史和详情独立显示采集与日报状态；区分未采集、采集中、采集失败、成功零消息、素材不足、待产稿、产稿中、可读和旧稿待更新。未知枚举、缺失值、缺产物链接不显示为成功。
- 采集成功数只统计覆盖完整的成功条目，包含成功零消息。列表不以条目数组长度冒充归档群数，不把当前关注群追溯补入历史日期。
- 群路由与列表 key 保持稳定群 ID；同名群展示 ID 便于辨认。矩阵只展示服务返回的日期与交点，缺失交点显示未核验。
- 使用服务给出的 `/r/` 产物 URL；不凭旧相对路径拼接可读结论。旧稿链接保留；HTML 可嵌入阅读，无 PNG 时明确说明。iframe 受 sandbox 限制。
- 搜索支持关键词、稳定群 ID 与起止日期组合，筛选条件写入 URL，刷新和历史导航可以恢复。无命中、日期范围错误与服务失败均有终态。
- 删除硬编码出报时间及浏览器时钟成功推断；配置意图、首报核验、宿主任务回读和真实定时观察分开展示。定时记录没有进一步约定结构时仅提示到 WorkBuddy 核对，不推断成功。
- 页面保持只读，恢复出口为可复制的 WorkBuddy 指令。复制未确认时提供手动复制提示；不添加配置写 API 或宿主深链。
- 保留纸色、炭黑、砖红、本地 Vue 3 和无构建链。补充双维徽章窄屏换行、筛选表单、原生键盘帮助模态框与跳到正文入口。

## 红到绿证据

测试在正式 `scripts/web/` 上运行，合成 API 同伴仅在 `tests/frontend/fixture_server.py`，不进入发行代码。未使用真实聊天、原始备份或包内运行配置。

1. `check-states.mjs` 修改前失败：未采集条目被显示为“已出日报”，10 条目全部被计为归档/出报。修复后通过：10 个交点中 6 个群采集成功，2 份有可读产物；缺链接的 ready 显示未核验。
2. `check-history.mjs` 修改前失败：没有群、日期组合筛选控制。修复后通过：关键词 + 群 ID + 同日起止日期过滤、刷新保留条件、结果进入正确群日路由、旧稿产物实际 HTTP 200。
3. 扩展交互测试覆盖 8 个公开路由 × 1280px/390px，无文档级横向溢出、可见错误或页面异常；另外检查 j/Enter、搜索快捷键、Escape、原生模态框 Tab、可复制指令反馈、读取失败与重试、无命中和无效日期范围。

原生 dialog 的 Tab 可经过浏览器工具栏；测试核验 `:modal` 和背景页面不可聚焦，不将浏览器工具栏焦点误判成页面逃逸。复制反馈断言限定在用户实际展开的指令，避免读取隐藏的运行状态指令。

## 实际运行的检查

```bash
python3 -B -m unittest discover -s tests/frontend -p 'test_*.py' -v
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
node --check skills/wechat-group-daily/scripts/web/app.js
git diff --check
/Users/mac/.codex/skills/impeccable/scripts/impeccable detect --json skills/wechat-group-daily/scripts/web/app.js skills/wechat-group-daily/scripts/web/app.css
```

- 前端 unittest：5/5 通过；运行浏览器为 Ego Lite 0.6.0.16。每次使用独立任务空间、四个仅本机监听的合成服务，结束后关闭空间和服务。
- 根公共入口基线检查：7/7 通过。
- JavaScript 语法与 whitespace：通过。
- Impeccable：本会话针对正式 `app.js` 执行 context 一次，编辑前读取 craft-floor；targeted detect 返回 `[]`，不代替交互与视觉验收。PRODUCT 的旧 schema 提示未自动修订。

## 视觉证据

所有截图均为合成内容，实际查看并核对；不作为微信取数或模型质量证据。

- [1280px 最近列表](../../tests/frontend/evidence/recent-1280.png)
- [390px 日期与双维状态](../../tests/frontend/evidence/day-390.png)
- [390px 组合搜索](../../tests/frontend/evidence/search-390.png)
- [390px 旧稿待更新与 HTML 阅读](../../tests/frontend/evidence/stale-390.png)

## 主控集成与待验证项

共享契约、Python、共享夹具、根文档和开发日志均未改动。本文件承载本分支实现记录，供主控集成时追加 `docs/dev-log.md`。

后端接入需保留契约字段、返回真正存在的 `html_url/png_url`、提供按生效范围确定的群日条目。前端不比较版本散列，不替后端推导 stale，不把聚合旧 state 当成功。仅有旧字段时会显示未核验；这是兼容阶段的有意保守行为。

集成后必须将浏览器切到真实 Python API，验证采集零消息/失败/部分覆盖、重采保留旧稿和过滤搜索，不能以 fixture HTTP 200 替代。契约对全量历史聚合和 `last_scheduled_run` 的结构尚未详细定义：窗口外日期显示未核验，定时记录提示核对；如需更细状态由主控协调最小契约增量。

Windows 微信真实取数、真实库/WAL、模型产稿与来源核对、PNG、WorkBuddy 任务登记回读/真实触发及第二台安装均未验证。

## 独立双轴评审及修复

固定点为上述 T0 基线，初次评审对象为 `6fbefd5` 的三点 diff。

### Standards

初评 2 项 P2：等待时同时显示无数据结论；`empty` 计数缺失仍显示成功零消息。没有需要单独修改的 Fowler smell。

已修复：日期/群/详情恢复加载、错误、空态的互斥分支；成功状态同时核对完整覆盖及已知计数，empty 必须恰为 0，collected 必须为正整数。公共浏览器测试分别观察到旧行为失败和修复通过。成功群数仍为 6；新增异常 empty 夹具后共 11 个交点，异常计数不进入成功统计。

### Spec

初评 2 项 P2：成功零消息被排除在每日平均数之外；加载时出现无数据结论（与 Standards 重复）。未发现额外范围扩张，未误报后端或 Windows 完成。

已修复：仅统计成功且计数已知的日期，同时保留零值。新增历史场景为 2 条与 0 条，修改前平均为 2，修改后平均为 1，归档天数保持 2。慢 HTTP 日期、群、详情测试均验证请求进行中不出现空态结论。

评审原始计数：Standards 2 项、最高 P2；Spec 2 项、最高 P2，去重共 3 项，均已补回归修复。后续复核结果由提交后的复核补充。

测试服务显式禁用静态缓存，避免不同测试空间复用浏览器缓存时读取旧源码；每次仍从正式 web 目录提供资产，没有替换产品内部代码。
