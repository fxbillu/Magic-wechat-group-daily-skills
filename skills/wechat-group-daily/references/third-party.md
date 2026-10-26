# 第三方来源与许可盘点

核查日期：2026-10-27。仅描述本仓库已纳入的文件，不能代替 Windows 行为验证。
固定来源及本地 SHA-256 见 [机器清单](third-party.json)；版本/文件变化后须重新核查，不能默默更新哈希绕过审查。

| 文件/组件 | 一手来源与许可 | 本地修改及边界 |
|---|---|---|
| `scripts/web/vendor/vue.global.prod.js`，Vue 3.5.44 | [官方 npm 元数据](https://registry.npmjs.org/vue/3.5.44)、[官方包](https://registry.npmjs.org/vue/-/vue-3.5.44.tgz)；[Vue 固定提交 LICENSE](https://github.com/vuejs/core/blob/bf5f0dd877dd3c23ce85c2cbc1dd771567e84c8c/LICENSE)，MIT | 与官方 tarball 内 `package/dist/vue.global.prod.js` 逐字节一致，无本地修改；保留原版权头并附 [MIT 全文](../licenses/vue-MIT.txt) |
| `scripts/tools/wcdb_key_tool_windows.py` | 文件头标明 [TANGandXUE/wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool)；固定核查提交 `79f1b5b92e12c66aa281b4a60a3c478b5f547dfa` 的 [源码](https://github.com/TANGandXUE/wcdb-key-tool/blob/79f1b5b92e12c66aa281b4a60a3c478b5f547dfa/wcdb_key_tool_windows.py) 与 [LICENSE](https://github.com/TANGandXUE/wcdb-key-tool/blob/79f1b5b92e12c66aa281b4a60a3c478b5f547dfa/LICENSE)，MIT，Copyright 2025 CloudDreamAI / TANGandXUE | **本地修改版**：删除研究性断点捕获函数/异常类与相关 CLI 分支，调整 Python 要求及部分注释。AST 比对其余共同函数相同，仅 `main` 变化。上游核查提交是比对点，不声称为历史导入提交；精确导入日期/修改作者未从历史取得。附 [MIT 全文](../licenses/wcdb-key-tool-MIT.txt) |
| `scripts/tools/safe_decrypt.py` 的 SQLCipher 页解密/AES/HMAC 思路 | 与上述取钥工具相关算法一致；当前文件无独立来源头 | 作为本地一致性快照实现记录，保守保留上述上游归属及许可；无法据此确定逐行来源与作者，维护者应补历史出处。无新增第三方二进制 |

取钥文件头仍提到已删除的 `capture-experimental` 命令；该文案差异交回主控/后端修正，本发布分支不修改业务脚本。
上游自述的“已验证”不是本产品在当前微信/Windows 版本的证据。

运行时依赖由使用者环境提供，不随 ZIP 打包；Python、Node、浏览器、cryptography、Pillow 和语音库的安装/版本/各自许可需由实际安装环境另行盘点，不能套用 Vue 的 MIT。详见 [依赖表](dependencies.md)。
其余导入代码的原始作者和授权历史尚缺完整证明；当前私有工程准备不等于获得了公开发布整包的许可。正式分发前由维护者确认来源归属与授权范围。
