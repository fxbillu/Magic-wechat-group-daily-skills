# T5 发布基础与独立验收准备

日期：2026-10-27。票据：[T5 #7](https://github.com/fxbillu/wechat-group-daily-skills/issues/7)。
固定开发/评审基线：`1bef2b65624f7f6dd7d4273ce30cfa4cc8bc2884`。
本轮仅提前准备打包基础和验收材料，**T5 未完成、未关闭、未发布**；T4 尚为产品依赖。
主控确定目标版本为 **1.3.0**，仍是候选阶段，待全部集成后统一修改版本与变更记录。

## 交付与操作入口

- [打包 CLI](../../skills/wechat-group-daily/scripts/tools/package.py)：源码检查 → 白名单暂存 → 再检查 → ZIP → 解压再检查 → 实际输出 ZIP 重开复核 → SHA-256 / 文件哈希回执。只生成内部候选，不推送、不打 tag、不发布。
- [逐文件清单](../../skills/wechat-group-daily/references/release-files.json)：当前 41 个文件（含主控通知的 T1 `collection.py`），每个都是必需项；无通配符。前端、入口、依赖说明、来源说明、许可全文、Windows 验收说明另列不可删除的关键项。T1–T4 新增文件要逐项由主控审查后补清单。`collection.py` 已按主控明确通知加入，独立分支的业务代码仍不越界修改。
- [公共 CLI 测试](../../tests/test_package.py)：只经 subprocess 入口与最终 ZIP 观察行为，不 import 打包器或断言内部函数；临时安装副本、隔离配置与临时产物，无真实聊天/密钥。
- [依赖能力表](../../skills/wechat-group-daily/references/dependencies.md)、[第三方来源](../../skills/wechat-group-daily/references/third-party.md)、[来源哈希清单](../../skills/wechat-group-daily/references/third-party.json)。
- [给 Windows 使用者的首装/升级流程](../../skills/wechat-group-daily/references/windows-acceptance.md)：可复制给 WorkBuddy 的指令、每步预期/失败反馈、脱敏结果模板；由用户本人运行并反馈，无需上传原始数据。

从仓库根目录运行（将候选输出路径换成新的临时路径；不能在 Skill 内输出或覆盖已有文件）：

```bash
python3 -B skills/wechat-group-daily/scripts/tools/package.py
python3 -B skills/wechat-group-daily/scripts/tools/package.py --build --output /tmp/wechat-daily-candidate.zip
python3 -B skills/wechat-group-daily/scripts/tools/package.py --verify-zip /tmp/wechat-daily-candidate.zip --sha256 <64位预期哈希>
python3 -B skills/wechat-group-daily/scripts/tools/package.py --capabilities
python3 -B -m unittest discover -s tests -p 'test_package.py' -v
```

`--verify-zip` 以当前受审源码为可信文件清单和逐文件哈希来源，因此必须在与包对应的源码版本运行；还会检查解压后的清单/版本/引用/隐私。不能仅信任 ZIP 内自带清单。
`--capabilities` 独立于发布版本检查，缺必需能力退出 1，可选降级不当作主线失败；不安装依赖、不读取用户配置、不提取微信密钥、不登记任务。
构建成功产生 ZIP 和旁边的 `.zip.json`；回执包含 `kind=internal_candidate`、包版本、ZIP SHA-256、每文件 SHA-256、源码提交/dirty 状态（无 Git 时为 null）、`release_tag=null`、`windows_acceptance=not_verified`。它不是正式发布证明，合成副本的回执不能冒充已提交集成版本。

## 边界与阻断

| 检查 | 行为 |
|---|---|
| 未知文件/目录、缺少清单项、符号链接、异常路径/文本 | 拒绝；不悄悄忽略本机文件，也不读取链接目标来凑包 |
| 包外个人状态 | 运行配置、密钥、解密库、归档、日报、日志、T1 的 `collections/` 与 `report-records/` 及备份既不能默认进入，也不能被补到白名单绕过 |
| 版本 | SKILL frontmatter 与 VERSION 必须一致、格式有效；不因目标版本已决定而跳过核对 |
| 隐私 | 对所有允许的 UTF-8 文本扫描，含 HTML/CSS/SVG/本地 vendor；拒绝不可解码与 NUL 文本；检测账号/群 ID、个人目录、私钥头、带值的典型密钥字段及明确合成标记；只输出文件/行号/类别，不重复命中值 |
| 配置模板 | 账号、路径、关注群和创建时间必须空白，不能只凭 ID 正则判定干净 |
| 引用与来源 | Markdown 相对引用与前端静态资源存在性；固定第三方文件与许可哈希。依赖声明/许可缺失均阻断 |
| ZIP | 精确文件集、重复项、目录/符号链接、路径穿越、解压体积上限、CRC/内容、版本与引用；输出后重开实际 ZIP 并核对哈希；已有产物不覆盖 |

文本扫描是有限启发式，不能识别所有任意聊天正文或所有密钥形式。主控仍需人工审查待提交 diff 和完整发布文件；扫描通过不等于隐私审计、产品功能和来源授权都完成。打包 CLI 扫描的是 Skill 发布源码树，不扫描仓库之外的目录或旧备份。

## 实际验证记录

2026-10-27，在 macOS、Python 3.14.7、Node v24.18.0、SQLite 3.53.4 上：

| 命令/检查 | 实际结果 | 可以证明的范围 |
|---|---|---|
| `python3 -B -m unittest discover -s tests -p 'test_package.py' -v` | 17 项：16 通过、1 因当前解释器缺 Pillow 跳过 | F13 修复与打包 CLI/ZIP 边界；成功构建用临时副本对齐版本；若尚无 T1 collection.py，仅在临时副本写明确的合成模块占位，不覆盖真实模块；不验证该业务行为 |
| `python3 -B -m unittest discover -s tests -p 'test_*.py' -v` | 24 项：23 通过、1 跳过（17 发布 + 7 原 T0） | 公共 CLI 与已有真实 HTTP 读取测试；不含 Windows 取数/宿主实际行为 |
| `node --check skills/wechat-group-daily/scripts/web/app.js` | 退出 0 | 语法；没有修改前端，也未新增浏览器视觉验收 |
| Python AST 解析、`git diff --check` | 通过 | 语法/空白；不能证明平台兼容 |
| 正式源码 `package.py --build --output /tmp/wechat-release-source-blocked-candidate.zip` | 退出 1，`MISSING_FILE: scripts/lib/wechat_data/collection.py` 与 `VERSION_MISMATCH`；未生成 ZIP | 独立分支仍是 T0 基线，未复制 T1 业务源码；缺资产与 VERSION 1.2.0 / SKILL 1.1.2 的真实阻断均保留，主控集成时纳入 T1 并统一目标 1.3.0 |
| `package.py --capabilities` | 退出 1；Python/SQLite/Node Zstd 通过；AES 与 Pillow 失败，当前解释器无 cryptography/Pillow；PNG/语音/Windows/宿主未测 | 实际能力探测能揭露缺依赖；本轮没有安装任何依赖 |
| 应用自带 Python 3.12.14：完整同一测试命令 | 24 项全部通过（含真实 Pillow 正向能力回归）；SQLite 3.53.1 | 使用已有依赖，无新安装；不继承为 Windows 兼容 |
| 应用自带 Python 3.12.14：`package.py --capabilities` | 退出 0；AES、SQLite、Node Zstd、Pillow 均通过，cryptography 50.0.2 / Pillow 12.3.0；PNG 浏览器/语音/Windows/宿主仍未测 | 主线合成能力与可选 PNG 编解码成功；未执行真实浏览器截图或微信工具 |
| 上游源码与许可核对 | Vue vendor 与官方 npm 3.5.44 逐字节相同；两份 MIT 全文来自固定一手提交；取钥脚本 AST 差异已记录 | 来源/许可材料已补；上游自述不继承为产品 Windows 兼容证明 |

红绿证据：旧打包器缺整个前端仍退出 0 并出包；加入回归后失败，再实现白名单阻断转绿。版本不一致、CSS 合成群 ID、未回查的 ZIP、断链、许可变化、个人模板值、运行配置被加入清单等也分别观察到失败后实现转绿。未知文件、HTML/SVG、篡改 ZIP 等使用明确合成数据，无旧导入区依赖。

## 交回主控的发现与建议

1. **版本**：保留当前阻断；主控在全部集成后统一 SKILL/VERSION/CHANGELOG 到 1.3.0，不在本分支越权修改。
2. **主线能力检查**：当前 `doctor.py` 强制导入 cryptography，`safe_decrypt.py` 则优先 CNG。T2 应统一“当前流程硬依赖”与“实际解密能力”的表达；本分支不改业务检查器。
3. **语音依赖**：`voice.status()`/文案允许 silk-python，但实际 `silk_to_wav()` 只 import pilk；模型不存在时 ASR 可能自动下载 `base`。先与文本主线分离，后续真实启用再验证，不因安装名存在宣称可用。
4. **来源与文案**：本地取钥脚本已删 `capture-experimental` 实现，头部 Usage 还列它；交回后端修正文案。精确历史导入提交/修改作者、其余导入代码归属仍待维护者补证；当前 MIT 核查不等于整包公开发布授权。
5. **取数覆盖**：按主控最新决定，T1 对非空源 WAL 保守拒绝。WAL 非空可能是 header/checkpoint 残留，主库 `quick_check` 通过也不能证明不漏消息；先请目标 Windows 反馈版本、核心库数量、WAL 大小分类与稳定性，报告「检测到 WAL，覆盖尚未核验」。本轮不发明加密 WAL 合并算法。
6. **集成维护**：本轮只改所分配的打包/发布独立文件；共享 contracts、fixtures、readiness 测试、SKILL 正文与主控 dev-log 均未改。主控集成时将本记录统一追加到 `docs/dev-log.md`，再更新发布白名单以包含后续新增文件。

## 尚未完成的发布门槛

- T1–T4 集成、真实后端与浏览器联调；最终源码提交干净、1.3.0 版本一致、最终 ZIP 重新生成并完整检查。
- 第一台 Windows 真实取钥、核心库/WAL 覆盖、模型首报及原文核对、HTML/PNG、任务创建回读与真实到点触发。
- 第二台 Windows 从同一最终 ZIP 独立首装，执行 [验收流程](../../skills/wechat-group-daily/references/windows-acceptance.md)，并分别反馈首装/真实自动执行/读报认可。
- 升级保留配置/历史/同一宿主任务，无重复；迁移失败与回滚在真实环境演练。
- 验收后由主控建立私有源码提交、版本 tag、正式包版本、ZIP SHA-256 的追溯关系；本工具不会创建 tag 或 Release。

## 变更记录与评审

2026-10-27：为修复 F13 和提前准备 T5，新建逐文件清单、来源/许可/依赖与 Windows 验收材料，替换原宽松打包器，增加公共 CLI 回归。关键决定：任何未知文件拒绝、版本差异保留阻断、只出内部候选、合成与 Windows 证据分开。验证见上表；主控专属 dev-log 未改。
双轴评审固定点为上述基线，首次评审提交 `e5992c2`，两名代理只读独立评审；修复增量随后分别复核。

### Standards

工程规范硬违反 0，Fowler smell 0。补充实现发现 1：Pillow 子进程片段漏 `import io`，会在已安装 Pillow 时恒报失败；已补导入，以应用自带、已安装 Pillow 的解释器从公共 CLI 复现红→绿。可移植性建议 1：中文文本读写未显式 UTF-8；已补齐 Path 读写和测试文本 open。增量复核确认均已闭合，无新问题。

### Spec

首次发现 1（P2）：上述 Pillow 误报违反真实能力探测要求。修复与正向回归后，独立复核确认原 P2 闭合，增量无新增规格发现。当前窄范围未见其他遗漏或越界；Windows/T5 状态不提升。

主控随后通知 T1 新增 collection.py 及包外 collections/report-records；已同步严格清单、禁入规则和两项回归。独立分支缺业务模块时正式源码阻断，合成占位只在临时打包测试副本，不能作为 T1 产品验证。

两轴最终未解决发现均为 0；本轮技术检查通过不改变 T5 依赖与真实 Windows 验收门槛。
