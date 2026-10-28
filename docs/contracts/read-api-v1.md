# 读取接口契约 v1

适用范围：Windows WorkBuddy 群日报、本机 `127.0.0.1` 只读阅读服务。依据[已批准主计划](../plans/2026-10-26-development-plan.md)与[领域词汇](../../GLOSSARY.md)。前后端共享本文件；契约变更由主控协调，不能各自更名。

## 实现边界

| 能力 | 当前集成状态（2026-10-27） | 后续责任 |
|---|---|---|
| 静态页面、未配置阅读、`/api/status`、未就绪错误 | 已实现 | 保持兼容 |
| 既有 browse/day/chat/entry/search/messages/health | 日期/群条目提供 `collection/report`；T3 已加入精确组合筛选与历史生效边界，公共验收通过；health 的脱敏例外及未就绪 503 不变 | T3 真实 API 的前端联调仍待完成 |
| 稳定群身份、逐库覆盖、成功零消息 | 公共 CLI / HTTP 及 T1 正式 Python API 的前端联调通过，输入均为合成数据 | Windows 实库验证 |
| 素材与日报版本、重采保留旧链接 | 公共验收及 T1 跨层联调通过；链接须对应真实文件 | T3 完整历史阅读验收 |
| 前端采集/日报双维状态与读取路径 | T1 的两组公共 CLI → 正式 Python API → 前端场景通过 | T3 的 `expected` 与组合搜索前端验收仍待完成 |
| 首份日报实际验收记录 | 尚未实现，不从文件存在推断 | T2 |
| 宿主任务登记、回读和实际定时运行记录 | 尚未实现，不从时间配置推断 | T4 |

当前集成通过 26 项公共入口测试；T1 的两组正式 API 前端联调已通过，T3 前端联调、旧缺陷剩余项和 Windows 验证仍未完成，#3/#5 尚未由主控关闭。页面不得将 `null` 或缺失字段解释成成功、零消息或已创建任务。证据见 [T1 跨层联调](../verification/t1-integration.md)与 [T3 后端](../verification/t3-backend.md)。T1 记录中的 F10 失败探查是修复前证据，不能作为搜索修复通过的证明。

## 配置发现与安装边界

1. 设置了 `WECHAT_DAILY_CONFIG` 时，使用其指定的配置文件；相对值按进程工作目录转为绝对路径，推荐始终给绝对路径。
2. Windows 默认 `%LOCALAPPDATA%\WeChatGroupDaily\config.json`；缺少该环境变量时以用户目录的 `AppData\Local` 为基目录。
3. macOS/Linux 开发默认 `${XDG_CONFIG_HOME:-~/.config}/wechat-group-daily/config.json`。
4. 发现配置不创建文件或目录。代码包内旧 `scripts/config.json` 不自动导入；迁移工具、备份与路径校验的完整流程属于 T2。
5. 配置只保存发现入口，实际数据可由用户选择另一目录。阅读所需的 `paths.root/data/reports` 必须是包外绝对路径；不能缺失后回退到代码目录。

每次 HTTP 请求重新读取配置，初始化或修复完成后刷新即可继续；并发请求使用各自配置快照。密钥、账号 ID、绝对文件路径以及未列入契约的配置值不进入 `/api/status` 响应。公开字段先校验再摘取：`compose` 必须是对象、`chats` 必须是列表；群 ID/名称是最多 256 字、无控制字符的字符串，`daily` 为布尔；不反射嵌套对象或数组。`time` 为合法 `HH:mm`，`target_day` 当前只接受 `yesterday` 或未设置。状态入口对时区只校验 `UTC` 或 IANA 区域标识形状，配置错误只产生脱敏 `CONFIG_INVALID`；T1 采集入口已按配置时区实际解析自然日，时区能力缺失按下述 `TIMEZONE_UNAVAILABLE` 记录，不回退到另一时区。环境引导与宿主时区核验仍属 T2/T4。

T3 接受可选的 `chats[].effective_from`：合法 `YYYY-MM-DD` 表示当前这一轮关注从该自然日开始，包含当天。缺失或无效旧值表示范围未知，不从配置创建时间、首次归档或执行机今天猜测。新增或重新启用关注时，由 T2 记录用户确认的生效日；本字段不是完整的多轮关注历史。

## 通用约定

- 日期为 `YYYY-MM-DD`。新增时间戳使用 RFC 3339，必须带偏移；`timezone` 是显式配置的时区，未配置为 `null`。旧接口时间字符串在迁移前保留原格式，不冒充已带时区。
- 群 ID 沿用 `username`，为不透明、稳定的字符串；`name`/`chat` 仅是展示名。路由和查询参数使用群 ID，不能用群名当唯一身份。
- 本地 API 只允许读取，不提供选群、配置写入、补跑或任务创建操作。用户通过 WorkBuddy 对话执行这些动作。
- 产物地址仍由 `/r/` 服务，现有 `report_html/report_png` 为报告根目录下的相对路径。新增 `html_url/png_url` 必须在核验文件存在后才返回，不能暴露本机绝对路径。
- 配置、首报、任务回读、真实定时执行是独立事实；任一项成功都不能代替其他项。

## `GET /api/status`（T0 已实现）

始终尝试返回 200 和可读状态；配置损坏不让服务启动失败。`schema_version: 1` 适用于本状态结构。字段新增保持兼容；不复用旧字段表达新语义。

```json
{
  "schema_version": 1,
  "configuration": {"state": "unconfigured"},
  "reading": {
    "available": false,
    "code": "NOT_CONFIGURED",
    "message": "尚未初始化。请在 WorkBuddy 对话中调用微信群日报，完成账号与关注群设置。",
    "retryable": false,
    "next_action": "initialize_in_workbuddy"
  },
  "first_report": {"state": "not_observed", "verified_at": null},
  "schedule": {
    "registered": false,
    "task_id": null,
    "readback_at": null,
    "enabled": null,
    "timezone": null,
    "trigger_time": null,
    "target_rule": null,
    "planned_at": null,
    "target_date": null,
    "last_scheduled_run": null
  },
  "last_run": null,
  "followed_chats": []
}
```

- `configuration.state`：`unconfigured` / `needs_repair` / `configured`，只说明阅读所需配置可解析，不代表微信数据或初始化验收完成。
- `reading.available`：配置有效、阅读索引采用受支持的 schema version，且具备所有读取必需列。不是采集覆盖、模型质量或自动化健康证明。
- `followed_chats`：`[{username, name}]`。仅列启用的关注群，不返回账号路径。
- `first_report`：T0 恒为 `not_observed`；T2 才登记实际结果，允许 `running/verified/empty/insufficient/failed`，没有有消息样例时不能记 `verified`。
- `schedule.registered`：未配置为 `false`；有配置但没有宿主证据时为 `null`。不能因为 `compose.time` 存在而设 `true`。
- `trigger_time/timezone/target_rule`：读取用户配置意图；旧 `target_rule` 值 `yesterday` 表示前一完整自然日。它们不等于宿主已接受。
- `planned_at`：下一次已核验宿主触发时刻，不是日报完成承诺；T0 为 `null`。
- `target_date`：该次运行实际目标日期，不能从前端时钟猜；T0 为 `null`。
- `task_id/readback_at/enabled/last_scheduled_run`：只由宿主回读和实际触发证据填充；T0 全为 `null`。
- `last_run`：T4 后为 `{run_id, trigger, stage, started_at, finished_at, target_dates, succeeded_groups, failed_groups, error}`；T0 为 `null`。`trigger` 至少区分 `manual/scheduled/retry`，手动试跑不能填写定时成功记录。

## 未就绪与错误

已知业务 API 与 `/r/` 在未就绪时返回 HTTP 503；缺配置/索引时不新建目录或索引，损坏/不兼容索引不自动修复。静态页面和 `/api/status` 仍可用。状态探查和业务读取均通过 SQLite `mode=ro` 读取连接；每个读取连接都核验受支持的 schema version 与完整必需列，不调用初始化或迁移。校验后索引再次变化也不能转成写连接。

阅读索引已有合法 WAL 数据必须可见，不使用会忽略活跃 WAL 的 `immutable=1`。SQLite 可能为读取协调使用 WAL/SHM 侧车；这里承诺不创建配置、业务数据或执行索引初始化/迁移，不承诺底层文件系统绝对零写入。这不表示微信源库的加密 WAL 已处理：按用户收敛要求，当前主库采集路线对非空源 WAL 仅记录诊断并继续原路径，尚无加密 WAL 合并；非空不等于存在未合并数据，真实覆盖留待目标 Windows 核实，见 [WAL 覆盖边界调查](../verification/wal-coverage-investigation.md)。

```json
{
  "schema_version": 1,
  "error": "配置已保存，阅读数据还未就绪。请在 WorkBuddy 中完成首次采集或恢复索引。",
  "code": "INDEX_NOT_READY",
  "retryable": false,
  "next_action": "prepare_reading_data_in_workbuddy"
}
```

| `code` | 含义 | `next_action` |
|---|---|---|
| `NOT_CONFIGURED` | 没有配置文件 | `initialize_in_workbuddy` |
| `CONFIG_INVALID` | 无法解析、阅读必需路径缺失或路径落在包内 | `repair_configuration_in_workbuddy` |
| `INDEX_NOT_READY` | 尚无阅读索引 | `prepare_reading_data_in_workbuddy` |
| `INDEX_INVALID` | 索引不可读、缺必需列或 schema version 不受支持 | `repair_reading_index_in_workbuddy` |

这些错误需要先处理原因，故 `retryable: false`；“重新检查”只刷新读取状态。页面不能据此自动循环重试或调用写操作。`message/error` 可调整中文文案，逻辑只依赖 `code/next_action`。

T1 已增加以下采集错误语义，保留原 `error` 文本；其他旧 400/404/500 未因此全部标准化。

- `/api/messages` 在最新采集失败且从无成功素材时返回 HTTP 409，`code: COLLECTION_FAILED`、`retryable: true`、`next_action: decrypt_and_retry_in_workbuddy`，并携带该条目的 `collection`。已有成功素材时仍返回 HTTP 200 和旧成功消息，同时携带最新失败的 `collection`，不能将旧消息误作本次采集成功。
- 配置时区能力缺失时，`collection.coverage.issues` 记录 `TIMEZONE_UNAVAILABLE`、`retryable: false`、`next_action: repair_timezone_in_workbuddy`。无法计算目标范围时 `collection.range` 为 `null`，不伪造另一时区区间；这是具体采集失败原因，与消息接口外层 `COLLECTION_FAILED` 分开保留。

## 既有读取入口与条目扩展（T1 已接入，T3 继续验收）

| 入口 | 输入 | 既有输出/用途 |
|---|---|---|
| `/api/browse` | `days` | `overview/today/chats/matrix/days/recent/dayrows`，概览与导航 |
| `/api/day` | `date` | 某日 `chats` 条目和日期信息 |
| `/api/chat` | `username, limit` | 某群 `entries` 历史 |
| `/api/entry` | `date, username` | 一个日期与群交点 |
| `/api/search` | `q, chat, from, to, sender, type, limit` | `query/count/truncated/results`；`chat` 为稳定群 ID |
| `/api/messages` | `date, username, offset, limit` | 原消息分页及最新 `collection`；无成功素材的当前失败返回上述 409 |
| `/api/health` | 无 | 索引与前端基本状态；未就绪时也返回上述 503 |

兼容例外：旧 `/api/health` 的 `web_dir` 会暴露本机绝对路径，因此已移除。读取方使用 `web_ready` 判断前端资源是否齐备，不应依赖或恢复绝对路径输出。

T1 已为日期与群条目增加 `collection/report`，T3 再以可加兼容方式增加条目和矩阵单元格的 `expected`；旧 `state`、标题、计数、报告相对路径及采集/日报枚举不变。T1 正式 API 联调已通过，T3 新字段的前端联调仍待完成。旧接口兼容映射由后端维护，不让每个页面重算。

```json
{
  "username": "fixture-team",
  "chat": "示例群",
  "date": "2026-10-25",
  "expected": true,
  "collection": {
    "state": "collected",
    "revision": "opaque-material-revision",
    "message_count": 2,
    "observed_at": "2026-10-26T08:30:00+08:00",
    "range": {"from": "2026-10-25T00:00:00+08:00", "to": "2026-10-26T00:00:00+08:00", "timezone": "Asia/Shanghai"},
    "coverage": {"complete": true, "issues": []}
  },
  "report": {
    "state": "pending",
    "source_revision": null,
    "composed_at": null,
    "html_url": null,
    "png_url": null,
    "reason_code": null
  }
}
```

示例完全合成，表示结构，不是已运行事实。

- `collection.state`：`not_collected/running/collected/empty/failed`。只有覆盖已完成且消息数为零才能为 `empty`；失败不能变成零消息。
- `report.state`：`pending/running/ready/stale/insufficient/failed/orphan`。`stale` 仍保留可读旧稿；`orphan` 表示产物在、素材归档缺失。
- `revision/source_revision` 为不透明版本标识；同一素材重跑应稳定，源素材变化需明确标记旧稿。前端不生成或比较原消息散列。
- `range` 用左闭右开区间；时间边界由后端统一，不按浏览器本机时区重新分日。配置时区不可用且无法计算范围时为 `null`；未指定时区则使用执行机时区计算，`timezone` 保持 `null`。
- 错误覆盖项提供可定位的代号和脱敏说明，不包含密钥或消息正文。
- `expected: true` 表示当日有实际采集/报告记录，或有明确生效证据应当采集；`false` 表示当前证据不在范围内；`null` 表示缺少生效证据。缺字段的兼容读取也不能猜测为 true。
- 每日列表只补入明确应采集的关注群；`daily: false` 不补应采集项。矩阵为日期对齐保留的 `false/null` 占位不计为历史欠账，显式进入这些交点也不代表采集失败。
- 实际采集和报告记录始终保留，不因后来关注、取消关注、移出名单或修改当前生效日而删除。按群历史仍返回实际记录；单一 `effective_from` 不声称覆盖多轮取消和重新关注的完整区间。

## 并行开发的验证依据

### 2026-10-27 分析与上下文增量

现有 API 和索引 schema 保持兼容，新增能力复用冻结归档，不从 GET 写配置、迁移索引或调用模型。

- `/api/search` 的每条结果增加 `context_key`，为该条索引内容绑定的检索锚点，不使用不稳定的 SQLite rowid。`sender` 接受显示名片段或精确稳定用户 ID；其他筛选及返回字段不变。
- `GET /api/context?date&username&key&before&after`：稳定群 ID、出报日期和有效搜索锚点必填；默认 `before=8/after=12`，各自夹在 0—30。只读取同一份归档，返回 `messages`（含 `source_id/is_match`）、`anchor_id/source_revision/range/scope`（自然日归档为 `group_day`，接续归档为 `archive_range`）、`before_available/after_available/has_earlier/has_later` 及最新 `collection`。上下文不受搜索关键词、人物和类型筛选影响。归档不存在返回 404；来源变化或有歧义返回 409 `CONTEXT_CHANGED`，不猜测命中。旧成功归档仍可读，并保留最新采集失败状态。
- `GET /api/analysis?date&username`：返回该群当日 `activity`、素材 `source_revision`、最新 `collection` 和可选已保存分析。`activity` 按本次归档的原消息实算，按稳定成员 ID 区分同名人物；`participants` 提供 `name/sender_id/messages/text_chars/share`，`by_hour` 按归档时间的小时分布。不是实时微信全量统计或工作贡献评价。
- `analysis.state` 为 `pending/ready/stale/invalid`。只读取已有日报 `.story.json`，核对群、日期、素材版本及分析来源后，才返回 `overview/topics/followups/people/quotes` 与各项 `evidence` 原消息。无新版字段为 pending，素材不符为 stale，结构或来源不合格为 invalid；后两者不输出语义结论。状态不是对模型语义真实性的自动证明。
- 两个新接口沿用未配置／索引不可用的 503 规则，归档缺失不冒充成功零消息。它们不会自动生成分析；宿主仍按既有写稿、验稿和渲染流程更新日报。

短总述 `overview` 为可选对象，其他四项为数组；短总述与待确认事项同样校验 `source_ids`，不使用预览中的手写样例。缺失时为空对象或数组，不推断自动任务状态。

Schema 与宿主分析字段详见 [Skill 分析说明](../../skills/wechat-group-daily/references/analysis.md)。

- 当前可运行：`python3 -B -m unittest discover -s tests -p 'test_*.py' -v`，使用正式源码副本、隔离包外配置和真实 HTTP；夹具不依赖 `legacy-import/`。
- 合成归档在 `tests/fixtures/sample-archive.json`。原导入指纹在 `tests/fixtures/import-baseline.json`，仅用于来源追溯，不是新版代码必须保持旧哈希的断言。
- 前端可以按本契约准备未来状态夹具，但不能把夹具通过当真实后端通过。跨层票据关闭前须连接真实 Python API。
- Windows 取钥、真实库/WAL、模型内容、PNG、宿主回读/到点触发及第二台安装独立验收。

## 开发分支：按群日报模板（Windows 待验收）

- 包外 `chats[].report_template`：`detailed`（缺省）或 `project`，仅影响之后新采集的归档；归档及 `daily` pending 条目冻结该值。
- 读取条目的顶层 `report_template` 表示当前归档模板，`report.report_template` 表示已登记产物模板（旧记录缺省 detailed）；旧稿待更新时两者可以不同。阅读器按产物模板展示已生成日报，按归档模板展示待出报状态。
- 项目版素材地板为至少有可读文字（含成功语音转写），叙事版沿用原字数规则；其余 `collection/report` 状态及旧字段映射保持现有含义。
- `daily` 返回的 `delivery: {open_browser: false, notify_only: true}` 供宿主编排；该 JSON 不是跨宿主禁止弹窗的系统策略，旧定时任务提示词仍需更新。
