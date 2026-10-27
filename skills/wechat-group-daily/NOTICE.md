# 版权、来源与第三方声明

核查日期：2026-10-27。项目自有代码和文档按 [MIT](LICENSE.txt) 授权，Copyright (c) 2026 fxbillu and Magic WeChat Group Daily contributors。第三方版权归原权利人；项目许可证不替代下列声明。

| 组件或参考 | 范围与本地处理 | 版权及许可证 |
|---|---|---|
| Vue 3.5.44 | `scripts/web/vendor/vue.global.prod.js` 与官方 npm 发布文件逐字节相同；无修改。保留程序版权头及官方仓库许可全文 | Yuxi (Evan) You and Vue contributors；[MIT 全文](licenses/vue-MIT.txt) |
| wcdb-key-tool | `scripts/tools/wcdb_key_tool_windows.py` 是本地修改版，删除实验性 debugger 路线，调整入口与说明。`scripts/tools/safe_decrypt.py` 的 CNG/AES/HMAC 和页解密部分保守按其衍生实现归属；快照、校验、恢复和锁由本项目实现 | Copyright (c) 2025 CloudDreamAI / TANGandXUE；[MIT 全文](licenses/wcdb-key-tool-MIT.txt) |
| WeChatDaily | 人物／话题上下文、群内名片的数据结构和显示顺序、活跃统计及总览前置布局的参考。本项目在既有归档、API、验稿和阅读流程内实现，未引入其可执行程序、第三方取钥工具、模板图片或完整脚本。保守随包附原许可证，涵盖参考中可能涉及的片段 | Copyright (c) 2026 Bryan；[MIT 全文](licenses/wechatdaily-MIT.txt) |

固定提交、下载来源、修改说明和哈希见 [第三方来源清单](references/third-party.md) 与 [机器清单](references/third-party.json)。每个随包文件的归属分类见 [逐文件来源记录](references/source-provenance.json)。

初始 1.2.0 中其余自写文件由维护者确认使用 WorkBuddy／Codex 开发并拥有开源发布权；32 个原始文件的导入哈希已核对，后续开发可由 Git 历史追溯。该确认是授权依据，不代表恢复了旧电脑上全部生成记录，也不构成“代码绝无相似来源”的保证。

运行时 Python、Node、浏览器、可选加密／图片／语音库、模型及微信和 WorkBuddy 不随包分发。它们各自的许可、模型条款和服务条款独立适用；见 [运行时依赖](references/dependencies.md)。本项目图标和合成演示资料在本仓库开发，截图中的群聊与人员为虚构；真实用户资料不在本许可范围。

修改或再分发时保留适用的版权和许可文本。若发现遗漏的第三方来源，请在 [项目 Issues](https://github.com/fxbillu/Magic-wechat-group-daily-skills/issues) 提供公开来源及对应文件，勿提交私密聊天或密钥。
