# 第三方来源与许可盘点

核查日期：2026-10-27。范围为本仓库及 rc.7 实际随包文件；许可结论不代表 Windows 运行验证。项目自有文件采用 [MIT](../LICENSE.txt)，完整归属见 [NOTICE](../NOTICE.md)。

## 随包组件与参考

| 文件／组件 | 固定一手来源及许可 | 核查与本地修改 |
|---|---|---|
| `scripts/web/vendor/vue.global.prod.js`，Vue 3.5.44 | [官方 npm 包](https://registry.npmjs.org/vue/-/vue-3.5.44.tgz)；[固定仓库 LICENSE](https://github.com/vuejs/core/blob/bf5f0dd877dd3c23ce85c2cbc1dd771567e84c8c/LICENSE)，MIT | 程序与 npm 包内文件逐字节一致。附 [仓库许可全文](../licenses/vue-MIT.txt)，保留程序版权头。npm 包许可作者行较仓库少 `and Vue contributors`，两者均为 MIT；附仓库较完整的版权行，未将其误记为 npm 许可逐字节相同 |
| `scripts/tools/wcdb_key_tool_windows.py` | TANGandXUE/wcdb-key-tool，核查提交 [79f1b5b](https://github.com/TANGandXUE/wcdb-key-tool/tree/79f1b5b92e12c66aa281b4a60a3c478b5f547dfa)，[MIT](../licenses/wcdb-key-tool-MIT.txt) | 本地修改版。AST 比对：删除 6 个实验性调试函数／类，其余共同定义仅 `main` 改动；本轮仅补版权和修正文档，未改函数。固定提交为比对点，非已证明的历史导入提交 |
| `scripts/tools/safe_decrypt.py` | 同上，CNG/AES/HMAC 和数据库页解密部分保守归属上游 MIT | 不主张这些部分为本项目独占原创。稳定快照、输出验证、锁和中断恢复经本地 Git 开发；附上游版权及许可。未引入 SQLCipher 二进制或源文件 |
| WeChatDaily 的上下文、群名片及布局参考 | Bryan-Cyf/WeChatDaily，核查提交 [88d261a3](https://github.com/Bryan-Cyf/WeChatDaily/tree/88d261a3e9954e0ed44edb0a247260c509d0022e)，Copyright (c) 2026 Bryan，[MIT 全文](../licenses/wechatdaily-MIT.txt) | 功能思路、数据结构与信息顺序参考，在本项目原 API／归档内实现。未纳入其可执行程序、完整脚本、图片或 wx_key。保守附许可，不把文本相似度检查当作独立原创证明 |

原始第三方文件、许可与衍生解密文件的本地 SHA-256 见 [机器清单](third-party.json)。构建时校验这些哈希，源码或许可变化需重新审查。

## 自有代码与开发过程

维护者于 2026-10-27 确认：除已注明第三方部分，其余初始代码由其使用 WorkBuddy／Codex 自写，并认为拥有开源发布权；本轮明确授权选择许可证并公开更新。该说明与原始导入哈希、Git 历史一起作为项目自有部分 MIT 授权的依据。

初始 32 个 Skill 文件均与导入时保存的 SHA-256 一致；之后从 `bf0d3bec202a2e9d3216cd354726f343a8653243` 开始的修改可由公开 Git 追溯。旧 Windows 上未保留的对话、最初生成过程及每一行的独立作者无法恢复，不声称已经逐行证明。逐个随包文件的分类见 [来源记录](source-provenance.json)；详查记录见 [仓库审查报告](https://github.com/fxbillu/Magic-wechat-group-daily-skills/blob/main/docs/reviews/2026-10-27-license-audit.md)。

## 外部运行时与可选组件

Python、Node、浏览器、cryptography、Pillow、语音库和模型均不随 ZIP 分发，其许可不能套用本项目的 MIT。特别是 **pilk 的 PyPI 分类标为 GPLv3**，可选语音不属于文本主线；启用、组合或再分发相关运行环境时，应核对所装版本及其附带 SILK 代码的许可义务，不能宣称整个语音环境都可按 MIT 闭源分发。

具体一手入口及未随包范围见 [依赖说明](dependencies.md)。本项目不分发微信、WorkBuddy、wx_key、调试器、模型权重、系统字体或用户聊天。
