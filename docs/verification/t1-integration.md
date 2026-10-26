# T1 正式 Python API 与前端跨层联调

日期：2026-10-27（Asia/Shanghai）。关联 [T1 #3](https://github.com/fxbillu/wechat-group-daily-skills/issues/3)，T3 限制另列。基线：`5a128916f919e830fc958b652680b756c072cbe5`，分支：`codex/wechat-t1-integration-qa`。

## 结论与边界

**T1 本轮合成输入下的公共 CLI → 正式 Python HTTP → 正式前端链路已实际验证。** 未使用 `fixture_server.py`、fetch 替换、模拟 API 数据或产品私有调用。T1 的 Windows 取数与业务验收仍未通过，#3/#5 由主控决定关闭。

测试将正式 Skill 复制到临时安装目录，配置、合成解密快照、归档、索引与日报全部在临时包外目录。输入构造复用 `tests/test_backend_collection.py` 的合成 SQLite 方法；替代边界仅为 Windows 微信来源快照。程序实际执行 `fetch.py archive/reindex`、`render_daily.py --no-png --no-avatar`、`serve.py` 和已提交的本地 Vue 前端。测试结束后停止服务并删除临时状态，关闭本轮 Ego Lite 任务空间。

## 实际观察

| 场景 | CLI / 真实 HTTP | 浏览器观察 |
|---|---|---|
| 同名群 | 两个稳定 ID 各保留一条素材，分片中重复 rowid 分别署为成员甲/乙 | 1280px / 390px 日期列表有两群与各自 ID，键盘 j/Enter 进入正确群日详情，原消息与发言人正确 |
| 改名 | 更新合成联系人后重采，群 ID 不变，另一群不受影响 | 原群 ID 路由显示“改名后的合成群” |
| 成功零消息 | 10-24 成功，collection.empty、count=0；10-23 未采集、count=null | 成功零消息与未采集分开显示；日期、群历史、矩阵和群日导航均可用 |
| 实际 HTML | 公共渲染器登记 ready，真实 `/r/` 文件返回 200；另一同名群没有该链接，PNG 为 null | 正式 iframe 与打开 HTML 链接使用后端原 URL，能取得合成日报正文 |
| 素材变化 | 修改合成消息后重采，revision 改变、source_revision 保留，report.stale | 显示旧稿待更新，旧 HTML 仍可打开 |
| 分片损坏 | 非零退出，collection.failed / coverage.complete=false；原成功素材与报告保留 | 旧稿仍可读；采集失败不被旧稿状态掩盖；另一无稿群仍能读到上次成功消息 |
| 索引重建 | 公共 reindex 返回 0，失败记录、报告版本和 URL 与重建前相同 | 重建后仍显示失败和旧稿待更新，旧消息可阅读 |
| 从无成功素材的失败 | `/api/messages` 为 409 `COLLECTION_FAILED` | 采集失败与原始记录读取失败有明确终态，不显示成功零消息 |
| 缺时区能力 | `TIMEZONE_UNAVAILABLE`，issue.retryable=false，range=null；重建保留失败 | 显示实际失败原因、先修复再采集指引；消息、人数、字数未知时均为“—” |

当前没有发现阻断上述 T1 合成链路的后端问题。最后一项通过 `PYTHONTZPATH` 指向不存在的合成时区数据目录触发，不改变系统时区或安装依赖。

## 联调发现与必要前端修正

在正式 API 上增加浏览器断言并先确认失败：

1. 从无成功素材的失败，原页面仍显示人数 0、字数 0，尽管消息为未知。已在前端适配处将没有消息计数依据的人数和字数也显示为未知；保留有历史成功素材的真实计数。
2. 时区缺失只有通用失败提示，无法区分需先修复的情况。已在详情展示后端 `collection.coverage.issues` 的 code/message，并依据 `retryable=false` 提示先在 WorkBuddy 修复后再采集。页面仍只读，没有新增 API 写入、安装依赖或宿主深链。

针对性复测两种失败场景通过。测试对修复提示使用语义词序匹配，避免把“请先在 WorkBuddy 中修复”误判成缺少“先修复”。

## 检查与证据

```bash
# 两个 T1 跨层测试 + 一个 T3 已知失败观察；第三项不是搜索修复验收。
WECHAT_T1_EVIDENCE_DIR=tests/frontend/evidence/integration \
  python3 -B -m unittest discover -s tests/frontend -p 'test_real_api.py' -v

# 修正后仅重跑出现失败的409/时区场景，其余已通过主路径未无理由重复。
WECHAT_T1_EVIDENCE_DIR=tests/frontend/evidence/integration \
  python3 -B tests/frontend/test_real_api.py \
  RealApiFrontendTest.test_first_failure_409_and_timezone_unavailable_are_not_empty -v

python3 -B -m unittest discover -s tests -p 'test_*.py' -v
node --check skills/wechat-group-daily/scripts/web/app.js
git diff --check
/Users/mac/.codex/skills/impeccable/scripts/impeccable detect --json \
  skills/wechat-group-daily/scripts/web/app.js
```

实际结果：T1 主路径和失败场景两个测试均已通过；T3 F10 探查确认已知失败。最后针对性复测 1 项（包含两种失败 subtest）通过；根公共测试 23/23 通过，Node/whitespace 通过，targeted detect 为 `[]`。此前 fixture HTTP 同伴的 5 项测试未在本轮重复，也未当成本轮真实 API 证据。

截图均为合成内容，已实际查看。外层阅读页面在两档宽度无文档级横向溢出；主路径记录无页面 error/unhandledrejection。样例 HTML 的固定宽度限制见下节。

- [1280px 正式 API 的同名群日期列表](../../tests/frontend/evidence/integration/live-day-1280.png)
- [390px 正式 API 的同名群日期列表](../../tests/frontend/evidence/integration/live-day-390.png)
- [390px 未采集](../../tests/frontend/evidence/integration/live-not-collected-390.png)
- [390px ready 与真实 HTML 容器](../../tests/frontend/evidence/integration/live-ready-390.png)
- [390px 改名与 stale](../../tests/frontend/evidence/integration/live-stale-390.png)
- [390px 分片失败保留旧稿](../../tests/frontend/evidence/integration/live-failed-390.png)
- [390px 重建后同一结果](../../tests/frontend/evidence/integration/live-reindexed-390.png)
- [390px 首次失败与未知统计](../../tests/frontend/evidence/integration/live-first-failure-390.png)
- [390px TIMEZONE_UNAVAILABLE 修复指引](../../tests/frontend/evidence/integration/live-timezone-390.png)
- [最近一次针对性复测结果](../../tests/frontend/evidence/integration/outcomes.json)只含 409 与时区复测，不冒充全部主路径记录。

## T3 与其他残留限制

- **F10 未修复**：同一索引上的纯关键词搜索 HTTP 200；关键词 + 群 ID + 起止日期组合返回 HTTP 503 / `INDEX_INVALID`，提示恢复阅读索引。测试明确断言该已知结果并单列为缺陷观察，没有把“复现失败”记为搜索功能通过。该现象仍由 T3 处理，不能凭当前错误代号认定索引文件真的损坏。
- 实际渲染器的 HTML 日报是 900px 固定宽度版式。390px 外层页面没有横向溢出，但 iframe 内需要横向滚动才能看完整张报纸；HTTP 200、正文存在和外层状态正确，不等于移动端报纸阅读品质已经验收。本轮没有修改后端渲染器。
- Windows 真实取钥、核心库与加密 WAL 覆盖、真实模型产稿及来源核对、PNG、WorkBuddy 任务回读与真实到点触发、第二台安装均未验证。合成明文 SQLite 不能替代这些能力。
- 共同契约补充由主控维护；本分支没有修改后端、共享夹具、契约或根开发日志。主控集成时可将本记录中的原因、范围与检查结果追加到统一日志。

## 工作区保留与交接

开始前旧分支 `codex/wechat-t1-frontend` 有一张未提交的 `tests/frontend/evidence/recent-1280.png`。已用 Git stash 保留，说明为 `preserve pre-QA screenshot on codex/wechat-t1-frontend`；未将它混入本分支，也未删除旧分支。恢复应在旧分支按该 stash 身份操作。

## 双轴独立评审

评审固定点为 `5a128916f919e830fc958b652680b756c072cbe5`，对象为首个提交 `957e147` 的三点 diff。两个只读子 Agent 分别检查 Standards 与 Spec，均未重跑旧 fixture 测试或检查图片像素。

- Standards：0 项可执行问题，无需修改的 Fowler smell；确认未知值、失败说明、只读边界和真实公共测试边界符合规范。
- Spec：0 项可执行问题；确认两处 UI 修正属于必要范围，T1 证据、T3 F10 及 Windows/390px 报纸内横滚限制分开记录。

本轮实质检查已结束，服务与浏览器测试空间均已清理；不推送、不合并、不关闭 #3/#5。
