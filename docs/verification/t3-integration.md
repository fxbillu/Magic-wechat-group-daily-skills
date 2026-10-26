# T3 前端与真实 API 联调

日期：2026-10-27（Asia/Shanghai）。关联 [T3 #5](https://github.com/fxbillu/wechat-group-daily-skills/issues/5)。精确基线：`874ce0e6af481a78a2ff0b7c047201ec99c0da9e`；独立分支：`codex/wechat-t3-integration`。

## 结论与实现边界

**本轮 T3 合成输入下的公共 CLI → 正式 Python API → 当前正式前端已验证。** F10 从上一轮“组合搜索返回 503”的历史探查转换为 HTTP 200、精确结果、实际浏览器表单/刷新/导航的正向验收；当前测试不再期待旧 bug 才通过。此前历史验证记录保持原样，以便追溯，不能当成当前行为。

没有修改 Python 后端、共享契约、共享夹具、根开发日志或报纸渲染模板。所有输入均为隔离包外合成 SQLite，测试实际运行干净安装副本中的 `fetch.py archive`、`render_daily.py`、`serve.py` 和本地 Vue；不使用 fixture HTTP 替代跨层验收。原有 fixture 同伴只补了符合新语义的 `expected=true` 字段，用于一项受影响的状态回归。

## 页面行为

- 按后端 `expected` 三值显示事实，不在前端计算生效日期。只有 `expected=true` 条目进入应采集分母与采集/日报状态统计。
- `not_collected` 且 expected=false：显示“当前关注范围外”；expected=null 或缺失：显示“关注范围未知”。两类占位都不显示待产稿，不计历史欠账。expected=true 的未采集仍保留“未采集”状态。
- 矩阵保持日期列对齐。范围外/未知占位显示中性文字，不创建进入不存在记录的链接，也不参加 j/k 交点导航；实际记录及确有应采证据的交点保持入口。行标题补充稳定 ID，区分同名群。
- 详情明确说明当前证据不等于完整历次关注历史；无可列出条目的日期有说明，不把现有名单追溯成历史缺口。
- 取消关注、daily=false 或从配置移除，不影响实际历史、搜索结果和已有日报。实际历史应由后端返回 expected=true，不被当前关注状态隐藏。
- 保留暖纸色/炭黑/砖红、本地 Vue 和只读操作出口。未改动配置、关注或任务写入行为。
- 日报 HTML 仍为固定 900px 版式；页面新增窄屏可在独立窗口打开的提示，未声称已解决报纸内部横向滚动。

`effective_from` 仅代表当前这一轮关注，包含该日；没有证据的旧名单不猜起点。多轮关注/取消/重新关注的完整区间仍不能由一个日期还原。

## 真实链路证据

| 场景 | 实际观察 |
|---|---|
| F10 同名群组合筛选 | 公共采集后，关键词 + 稳定群 ID + 同日起止日期返回 200，两群各精确命中一条本人消息；ID 片段和日期范围外均 0 条 |
| 浏览器筛选与刷新 | 1280px、390px 依次选择同名的甲/乙群，提交后命中对应群；URL、刷新后表单与结果均保留群 ID/日期；j/Enter 打开乙群正确详情与原消息 |
| 新增关注不补历史缺口 | 已有两群两天素材后新增两群，旧日列表仍只有实际两群，不出现新增群欠账 |
| 生效日包含当天 | 新群 effective_from=2026-10-26；10-24/25 矩阵显示范围外，10-26 显示应采但未采。当天实际成功 1 群、应采分母 2、未采集 1 |
| 未知旧范围 | 没有 effective_from 的新增群，矩阵三个日期均范围未知；显式群日详情给说明，不显示待产稿 |
| 取消/移除后的实际历史 | 甲设 daily=false、乙从配置移除；未来日期不补两群应采项；两群时间线仍有实际记录，甲的 ready 报告仍可通过原 URL/iframe 阅读 |
| T1 状态不回归 | 正式 API 主路径重新验证同名/改名、成功零消息、未知范围、stale、失败保留旧稿/旧素材、重建；双维状态针对性检查仍通过 |

范围适配先红证据：后端矩阵给 known 群两个 expected=false 和一个 expected=true，前端原先三格均显示“未采集”。修复后对应显示两个“当前关注范围外”与一个“未采集”，未知群三格均为“关注范围未知”。

## 实际检查

```bash
# T3 两项，分别执行；证据目录按场景分开，避免覆盖先前结果。
WECHAT_T1_EVIDENCE_DIR=tests/frontend/evidence/t3-search \
  python3 -B tests/frontend/test_real_api.py \
  RealApiFrontendTest.test_t3_f10_combined_filters_match_stable_group_and_survive_reload -v
WECHAT_T1_EVIDENCE_DIR=tests/frontend/evidence/t3-integration \
  python3 -B tests/frontend/test_real_api.py \
  RealApiFrontendTest.test_t3_expected_scope_and_unfollowing_keep_actual_history -v

# 仅回归受共享条目适配影响的既有检查，未重复完整 fixture 浏览套件。
python3 -B tests/frontend/test_reader.py \
  ReaderBrowserTests.test_collection_report_contract_states -v
python3 -B tests/frontend/test_real_api.py \
  RealApiFrontendTest.test_same_name_rename_empty_stale_failure_and_reindex_through_live_ui -v

python3 -B -m unittest discover -s tests -p 'test_*.py' -v
node --check skills/wechat-group-daily/scripts/web/app.js
git diff --check
/Users/mac/.codex/skills/impeccable/scripts/impeccable detect --json \
  skills/wechat-group-daily/scripts/web/app.js skills/wechat-group-daily/scripts/web/app.css
```

T3 新行为两项通过；T1 真实 API 主路径和受影响的双维状态各 1 项通过；根公共测试 **26/26** 通过。Node、whitespace 通过，targeted detect 返回 `[]`。页面错误监听无 error/unhandledrejection；桌面与 390px 已实际截图查看，外层页面无文档级横向溢出。矩阵在自己的滚动容器中横向滚动，稳定 ID 在窄屏换行。

Impeccable 沿用本会话已运行一次的 context 和已批准 PRODUCT/DESIGN；此次 UI 编辑前重读 craft-floor，没有自动修订根产品文档。

## 合成截图与结果

- [1280px 精确组合搜索](../../tests/frontend/evidence/t3-search/t3-search-1280.png)
- [390px 精确组合搜索](../../tests/frontend/evidence/t3-search/t3-search-390.png)
- [搜索正向验收结果](../../tests/frontend/evidence/t3-search/outcomes.json)
- [1280px 范围矩阵](../../tests/frontend/evidence/t3-integration/t3-matrix-1280.png)
- [390px 范围矩阵](../../tests/frontend/evidence/t3-integration/t3-matrix-390.png)
- [390px 未知范围详情](../../tests/frontend/evidence/t3-integration/t3-unknown-390.png)
- [390px 取消关注后实际报告](../../tests/frontend/evidence/t3-integration/t3-unfollowed-390.png)
- [范围与取消关注验收结果](../../tests/frontend/evidence/t3-integration/outcomes.json)

## 待主控归档的边界

当前未发现阻断本轮 T3 合成跨层链路的后端问题。#3/#5 不由本分支关闭，不推送或合并。旧分支及原 stash 保留。

Windows 微信真实取数、密钥、加密 WAL 覆盖、真实模型产稿及来源核对、PNG、WorkBuddy 宿主任务回读/真实触发及第二台安装均未验证。HTML 返回 200、状态正确和外层控件窄屏可用，不代表固定宽度报纸的移动阅读品质通过。本轮不修改后端 900px 模板。

本文件承载本分支的原因、范围、关键判断和验证记录；主控集成时追加统一 `docs/dev-log.md`。

## 双轴独立评审

固定点为本轮精确基线 `874ce0e6af481a78a2ff0b7c047201ec99c0da9e`，评审对象为实现提交 `e7b062f` 的三点 diff。

- Standards：0 项可执行问题，无需修改的 Fowler smell。确认范围状态、只读边界、真实公共测试和验证表述符合规范。
- Spec：0 项发现。确认 F10 正向验收、三值 expected、矩阵占位与历史保留符合本轮授权，没有越界修改后端或渲染模板。

两个评审均只读，未重复运行已通过检查或检查截图像素。截图由本对话实际查看。最终文档链接检查通过，工作区旧分支与原 stash 均保留；本轮测试服务和浏览器任务空间已清理。
