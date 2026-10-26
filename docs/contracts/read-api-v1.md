# 读取接口契约 v1

适用范围：Windows WorkBuddy 群日报、本机 `127.0.0.1` 只读阅读服务。依据[已批准主计划](../plans/2026-10-26-development-plan.md)与[领域词汇](../../GLOSSARY.md)。前后端共享本文件；契约变更由主控协调，不能各自更名。

## 实现边界

| 能力 | T0 状态 | 后续责任 |
|---|---|---|
| 静态页面、未配置阅读、`/api/status`、未就绪错误 | 已实现 | 保持兼容 |
| 既有 browse/day/chat/entry/search/messages/health | 保留旧字段与正常路径；未就绪统一 503 | T1/T3 增加下述条目字段并修复旧缺陷 |
| 每群每日采集覆盖、素材与日报版本 | 本文件约定，尚未实现 | T1/T3 |
| 首份日报实际验收记录 | 尚未实现，不从文件存在推断 | T2 |
| 宿主任务登记、回读和实际定时运行记录 | 尚未实现，不从时间配置推断 | T4 |

T0 保留的旧浏览接口仍存在审查列出的缺陷；不能以接口存在或这份契约替代后续票据完成。页面不得将 `null` 或缺失字段解释成成功、零消息或已创建任务。

## 配置发现与安装边界

1. 设置了 `WECHAT_DAILY_CONFIG` 时，使用其指定的配置文件；相对值按进程工作目录转为绝对路径，推荐始终给绝对路径。
2. Windows 默认 `%LOCALAPPDATA%\WeChatGroupDaily\config.json`；缺少该环境变量时以用户目录的 `AppData\Local` 为基目录。
3. macOS/Linux 开发默认 `${XDG_CONFIG_HOME:-~/.config}/wechat-group-daily/config.json`。
4. 发现配置不创建文件或目录。代码包内旧 `scripts/config.json` 不自动导入；迁移工具、备份与路径校验的完整流程属于 T2。
5. 配置只保存发现入口，实际数据可由用户选择另一目录。阅读所需的 `paths.root/data/reports` 必须是包外绝对路径；不能缺失后回退到代码目录。

每次 HTTP 请求重新读取配置，初始化或修复完成后刷新即可继续；并发请求使用各自配置快照。密钥、账号 ID、绝对文件路径以及未列入契约的配置值不进入 `/api/status` 响应。公开字段先校验再摘取：`compose` 必须是对象、`chats` 必须是列表；群 ID/名称是最多 256 字、无控制字符的字符串，`daily` 为布尔；不反射嵌套对象或数组。`time` 为合法 `HH:mm`，`target_day` 当前只接受 `yesterday` 或未设置；时区只校验 `UTC` 或 IANA 区域标识形状，实际时区数据库解析属于 T2/T4。错误字段只产生脱敏 `CONFIG_INVALID`。

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

已有合法 WAL 数据必须可见，不使用会忽略活跃 WAL 的 `immutable=1`。SQLite 可能为读取协调使用 WAL/SHM 侧车；这里承诺不创建配置、业务数据或执行索引初始化/迁移，不承诺底层文件系统绝对零写入。

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

T1–T4 将其他业务错误统一扩展为同样的 `code/retryable/next_action`，保留原 `error` 文本；T0 没有宣称所有旧 400/404/500 已完成标准化。

## 既有读取入口与条目扩展（T1/T3 接入）

| 入口 | 输入 | 既有输出/用途 |
|---|---|---|
| `/api/browse` | `days` | `overview/today/chats/matrix/days/recent/dayrows`，概览与导航 |
| `/api/day` | `date` | 某日 `chats` 条目和日期信息 |
| `/api/chat` | `username, limit` | 某群 `entries` 历史 |
| `/api/entry` | `date, username` | 一个日期与群交点 |
| `/api/search` | `q, chat, from, to, sender, type, limit` | `query/count/truncated/results`；`chat` 为稳定群 ID |
| `/api/messages` | `date, username, offset, limit` | 原消息分页；只在本机阅读 |
| `/api/health` | 无 | 索引与前端基本状态；未就绪时也返回上述 503 |

T1/T3 为日期与群条目增加以下结构，保留旧 `state`、标题、计数和报告相对路径。前端正式接入时以新增结构为准，旧接口兼容映射由后端维护，不让每个页面重算。

```json
{
  "username": "fixture-team",
  "chat": "示例群",
  "date": "2026-10-25",
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
- `range` 用左闭右开区间；时间边界由后端统一，不按浏览器本机时区重新分日。
- 错误覆盖项提供可定位的代号和脱敏说明，不包含密钥或消息正文。
- 每日应有关注群按生效范围或当日记录确定；不把后来添加的群追溯为过去日期失败。取消关注不删除已有历史日报。

## 并行开发的验证依据

- 当前可运行：`python3 -B -m unittest discover -s tests -p 'test_*.py' -v`，使用正式源码副本、隔离包外配置和真实 HTTP；夹具不依赖 `legacy-import/`。
- 合成归档在 `tests/fixtures/sample-archive.json`。原导入指纹在 `tests/fixtures/import-baseline.json`，仅用于来源追溯，不是新版代码必须保持旧哈希的断言。
- 前端可以按本契约准备未来状态夹具，但不能把夹具通过当真实后端通过。跨层票据关闭前须连接真实 Python API。
- Windows 取钥、真实库/WAL、模型内容、PNG、宿主回读/到点触发及第二台安装独立验收。
