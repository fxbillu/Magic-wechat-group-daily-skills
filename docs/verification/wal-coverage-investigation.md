# WAL 覆盖边界调查

日期：2026-10-27。范围：T1 评审中的 `safe_decrypt.py`、`guard.py`、旧解密算法与一手公开资料。本文补充[主计划](../plans/2026-10-26-development-plan.md)的 Windows 验证依据，不改变[读取接口契约](../contracts/read-api-v1.md)。

## 当前执行政策（2026-10-27 最新要求）

按用户要求回到原 Windows 已跑通路径，保留真实缺陷修复，取消本轮新增的“非空 WAL 一律阻断”，改为诊断提示并在用户 Windows 测试中核实；后端正在完成撤回。非空仍不能被说成“未合并”，也不能把诊断提示当成覆盖已验证。候选上传不等待该实机验收，且不宣称新增了加密 WAL 合并能力。

以下保留调查当时的实现说明、建议和实验数据；其中一律拒绝非空 WAL 的建议已被上述政策替代，不能继续作为当前交付门槛。

## 调查时的实现边界（历史记录）

**非空 WAL 不等于存在尚未合并的数据。** T1 评审时的实现，在复制主库前后发现非空源 `-wal` 就拒绝发布新的解密产物。这是无法核验覆盖时的保守拒绝：避免旧实现只复制主库而静默漏数，同时可能挡住已经 checkpoint 的库。零字节 WAL 通过这一闸门，不代表整个采集流程已经验收。

准确提示应为“检测到 WAL，完整覆盖尚未核验”；“WAL 未合并”把未确定的状态说成了事实。本调查支持继续推进 T1 的失败保护，不支持放松闸门、删除源 WAL 或强制对微信源库执行 checkpoint。

旧算法与当前候选算法均以源主库的大小和修改时间前后相同，作为文件复制稳定性的判断。它不是数据库引擎提供的事务快照；`quick_check` 成功只说明读取到的数据库结构通过检查，不能证明包含 WAL 中的最新提交。解密完成时间也不能单独证明某自然日的消息已经全部同步和采齐。

## 已执行的普通 SQLite 合成实验

运行环境为本地 Python 标准库，SQLite **3.53.4**；所有文件都在临时目录中，退出后清理。没有读取微信数据库、取密钥、安装加密依赖或修改任何项目实现。

| 场景 | 实际观察 | 能证明什么 |
|---|---|---|
| 一条记录已提交到 WAL，只复制主库 | 正常只读连接看到 1 条；主库副本看到 0 条，`quick_check` 仍为 `ok` | 主库结构正常不能证明消息完整；忽略 WAL 可以静默漏数 |
| 同一库完成 PASSIVE checkpoint，保持写连接存在 | checkpoint 返回 `(0, 1, 1)`；主库副本已有 1 条；WAL 在前后均为 4152 字节 | 非空 WAL 可以全部回填，文件大小本身不能判定“未合并” |

以下命令可在仓库根运行，仅读写新建的临时合成库。实验中的 checkpoint 仅作用于合成库，不能改成真实微信路径。

```bash
python3 -B - <<'PY'
from pathlib import Path
from contextlib import closing
import json
import shutil
import sqlite3
import tempfile

with tempfile.TemporaryDirectory(prefix="wal-research-") as temp:
    root = Path(temp)
    source = root / "synthetic.db"
    wal = Path(str(source) + "-wal")
    with closing(sqlite3.connect(source)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO sample VALUES(1)")
        writer.commit()

        raw_copy = root / "raw-copy.db"
        shutil.copyfile(source, raw_copy)
        with closing(sqlite3.connect(raw_copy)) as copied:
            raw_count = copied.execute("SELECT count(*) FROM sample").fetchone()[0]
            check = copied.execute("PRAGMA quick_check").fetchone()[0]
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as live:
            live_count = live.execute("SELECT count(*) FROM sample").fetchone()[0]

        before = wal.stat().st_size
        checkpoint = writer.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        after = wal.stat().st_size
        checkpoint_copy = root / "post-checkpoint-copy.db"
        shutil.copyfile(source, checkpoint_copy)
        with closing(sqlite3.connect(checkpoint_copy)) as copied:
            copied_count = copied.execute("SELECT count(*) FROM sample").fetchone()[0]
        print(json.dumps({
            "sqlite_version": sqlite3.sqlite_version,
            "raw_main_copy_count": raw_count, "quick_check": check,
            "live_ro_count": live_count, "checkpoint_result": checkpoint,
            "wal_bytes_before": before, "wal_bytes_after": after,
            "post_checkpoint_main_copy_count": copied_count,
        }))
PY
```

具体字节数可能随 SQLite 配置变化；验收现象是“只拷主库漏已提交记录”和“全部回填后 WAL 仍非空”。本实验没有验证加密 WAL、微信使用的页格式或跨分片一致性。

## 一手资料与候选路线

- [SQLite 文件格式：WAL](https://sqlite.org/fileformat.html#walformat)：WAL 由 32 字节头与零个或多个帧组成；提交标记、校验和及盐值用于区分有效帧与历史残留。由此可知存在仅头文件的格式情况，但本轮没有观察真实微信的仅头 WAL。
- [SQLite WAL 机制](https://www.sqlite.org/wal.html)：checkpoint 通常不截断 WAL；只读打开 WAL 数据库有对应的侧车与访问条件。WAL 模式不提供跨多个数据库的整体原子性。
- [SQLite Online Backup API](https://sqlite.org/backup.html)：数据库引擎能够在其他连接仍运行时创建一致副本。它提供的是单个数据库层面的机制，不能直接证明微信各分片在相同时刻采齐。
- [SQLCipher 设计](https://www.zetetic.net/sqlcipher/design/)：WAL 中的页数据同样加密，不能将普通 SQLite 合成结果当作微信加密兼容测试。
- [SQLCipher 维护者的 Backup API 说明](https://discuss.zetetic.net/t/using-the-sqlite-online-backup-api/2631)：SQLCipher 4.3.0 起支持加密到加密及明文到明文备份，不支持用该 API 混合两种类型。
- [SQLCipher 导出 API](https://www.zetetic.net/sqlcipher/sqlcipher-api/#sqlcipher_export)：`sqlcipher_export` 可把内容复制到独立附加目标，支持加密与明文之间转换。目标可写不等于允许修改源数据库。
- [腾讯 WCDB](https://github.com/Tencent/wcdb)：基于 SQLite 与 SQLCipher，并包含自身优化。公开框架资料不是当前 Windows 微信所使用版本、加密参数和运行行为的确认。

值得后续验证的候选路线是：使用与实际库兼容的加密引擎，以只读源连接创建独立备份或导出目标，让引擎处理事务与 WAL。它不要求预先关闭微信，但当前项目尚未证明这条接入在目标 Windows 环境成立。只读业务数据也不等于底层文件系统绝对零写入，WAL/SHM 协调行为仍需核验。不要通过 `immutable=1` 绕过正在变化的源库，也不要未经验证自行拼接、解密或重放 WAL 帧。

## Windows 首轮无敏感诊断

首轮只判断保守闸门的实际影响，不执行解密或更改微信状态。用户在本机运行，回传以下汇总字段即可：

- Windows、微信、WorkBuddy、Skill 与 Python 的版本；不包含主机名或用户账号。
- 按联系人、会话、消息分片分类的文件数量，以及检查成功、缺失和无法访问的数量。
- WAL 大小类别的数量：不存在、0 字节、1–31 字节、32 字节、大于 32 字节。32 字节只能称“仅头候选”，不能仅凭大小宣布有效；大于 32 字节也不能直接称“未合并”。
- 在注明采样间隔与总次数的短观察窗口内，主库与 WAL 的大小/修改时间变化次数，以及文件出现、消失次数。只回传分类汇总，不回传文件名或绝对路径。

该诊断只读取文件元数据，不打开数据库页、读取进程内存、采集账号/群名/聊天、输出盐值/密钥，或上传原文件。它也不调用源库的 checkpoint、迁移、修复或清理功能。

诊断能说明“源文件是否持续变化、非空 WAL 有多普遍”，不能判定其有效提交是否已经回填。取得统计后，再选择有边界的兼容引擎实验；实际加密参数、WAL 可见性、源访问权限、逐库消息覆盖及长期定时成功率，均仍需 Windows 证据。首次本机实测应只回传版本、结果计数和脱敏错误类别，原始库与密钥保留在用户电脑。
