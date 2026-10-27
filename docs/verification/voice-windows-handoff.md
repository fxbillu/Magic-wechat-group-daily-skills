# 群语音 Windows 开发预览交接

日期：2026-10-27。分支：`codex/wechat-voice-transcription`。脚本快照：`1972e457e2017cf532b9eb1d850c2ed799b83e85`，基线 `29cf961b48df30c5d42018b81d2c3f47eb49fdde`。

## 交付与范围

- 开发预览 ZIP：`wechat-group-daily-voice-windows-preview-1972e45.zip`，60 个显式随包文件，含新脚本和 [完整语音流程](../../skills/wechat-group-daily/references/voice.md)。构建回执为干净源码、解压文件核对通过，`windows_acceptance=not_verified`。
- SHA-256：`55a3ed2057a5fe4d8276ce39f62338bd58b819fa74875a73602fba0ba21e5b8d`。
- 基础 VERSION 沿用 1.3.0-rc.9，但这是独立开发快照，**不是 GitHub 已发布的 rc.9 ZIP**。Windows 导入本预览包后明确重新加载，以本回执的提交与摘要识别，不能只看 VERSION。
- 未合入主分支，未替换正式安装包；并发安装更新工作保留在原目录。本轮仅交付语音脚本与编排，不把 Mac 合成检查当作目标环境可用证明。

## 静态评审

### Standards

两项发现已修复并源码复核关闭：音频临时目录绑定 job；文字补跑保留最新采集失败、coverage、observed_at 与采集游标。限定复核范围内零项剩余问题。

### Spec

初始两项及后续一项中断恢复问题均已修复并源码复核关闭：临时目录归属、只修订目标语音且不改无关消息、JSON/索引/每日 pending 状态的持久化恢复。限定复核范围内零项剩余问题。

## 验证边界与 Windows 下一步

用户要求收敛后，仅做源码评审、语法解析和打包文件核对，未再运行产品/模型测试。此前八个合成场景及已启动的94项公共检查在早期实现上通过（93通过、可选Pillow跳过）；**不覆盖最后静态修复的真实运行，也不代表Windows验证**。

Windows 按包内语音说明操作：核对加载目录/回执 → 复用Python → voice status → 按授权准备依赖与本地模型 → voice configure → 小范围真实语音归档 → WorkBuddy写稿并打开HTML → 观察子进程和内存/显存回落 → 有失败时voice retry并更新原稿。特别验证最终的临时音频归属、最近采集失败保护、无关消息保持和中断修订恢复。
