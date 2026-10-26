# 依赖与能力检查

当前为开发候选；没有经过 Windows 兼容矩阵验证。文本日报主线不安装语音模型。
所有命令从 Skill 根目录执行；请使用 WorkBuddy 确认的同一 Python 解释器。

```powershell
python -B scripts/tools/package.py --capabilities
```

JSON 的 `passed` 只代表指定的合成能力检查通过。必需检查失败退出 1；可选失败或未测不阻断文本主线。
本命令不安装软件、不读取个人配置或微信、不加载语音模型、不登记任务；临时文件自动清理。
当前 `doctor.py` 尚未接入这份探测结果，日常流程仍须执行 doctor 和真实首报检查。

| 能力 | 必需性、源码依据 | 本命令实际验证 | 尚需验证 |
|---|---|---|---|
| Python ≥3.11、标准库 SQLite | 主线；所有 Python 工具与 `db.py` | 版本；临时内存 SQLite 建表、写入、查询 | Windows 解释器/架构与真实库、WAL 覆盖 |
| AES-256-CBC 解密 | 主线；`safe_decrypt.py` 优先 Windows CNG，失败回退 cryptography | 实际调用该解密适配器，通过 NIST 公开向量核对明文 | 进程取钥、SQLCipher 页/HMAC、活库覆盖；合成 AES 不代表这些通过 |
| cryptography | 当前 doctor **强制导入**；解密适配器在 CNG 可用时可能不使用它 | 记录安装版本；AES 检查验证实际路径 | doctor 与 CNG 策略差异需初始化责任方统一；不能因原生 AES 通过就宣称 doctor 通过 |
| Node + 内置 Zstd 解压 | App/链接/文件内容所需；`content.py` 调用 `zstd_bridge.js`，缺失会降级 | 用公开的合成 Zstd 帧走真实桥接脚本并核对 `hello` | 真实微信压缩消息；仅 `node --version` 不足以证明能力 |
| 本地 Vue 3.5.44 | 阅读主线，自带 vendor，无 npm 安装/CDN | 打包清单、文本扫描及来源哈希 | 浏览器与真实 Python HTTP 联调 |
| WorkBuddy、微信 Windows | 真实取数/模型成稿/本地任务所需 | **不探测**；恒为 `not_tested` | 用户在实际客户端完成首报、任务回读与到点触发 |
| Chromium / Edge / Chrome | PNG 可选；HTML 不依赖它 | 默认 `not_tested`；显式 `--browser` 才用隔离临时 profile 打开合成页并检查 PNG 签名/尺寸 | 真实日报 PNG 的文字/裁切效果；测试页面成功不代表日报截图正确 |
| Pillow（导入名 PIL） | PNG 裁边、头像处理可选 | 创建 PNG、重新解码并核对尺寸 | 实际头像与日报裁边 |
| pilk（当前真实解码路径） | 语音解码可选；`silk_to_wav` 实际只导入 pilk | 仅记录 distribution 版本；语音保持 `not_tested` | 授权本地音频的真实解码 |
| ctranslate2 + faster-whisper + 本地模型 | 语音识别可选；`voice.py` | 仅版本盘点；不加载/下载模型 | 模型能加载、实际转写、资源释放 |
| torch / opencc-python-reimplemented | 语音 GPU 资源回收/繁简转换可选 | 不承诺可用，opencc 仅版本盘点 | 需要时独立验收；CPU 文本主线不需安装 torch |

例如显式验证 Node 或 PNG（路径由本机发现，不能照抄其他人的绝对路径）：

```powershell
python -B scripts/tools/package.py --capabilities --node node
python -B scripts/tools/package.py --capabilities --browser "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
```

当前 `voice.status()`/错误文案把 silk-python 也列为可选解码器，但 `silk_to_wav()` 只调用 pilk；仅安装 silk-python 不能据此声称能解码，需后续责任方修正。ASR 在模型目录不存在时会选择 `base`，可能触发下载，所以本探测不会调用它。

任何缺失依赖先报告，让使用者决定是否安装；这份检查不自动执行 pip、npm、管理员提权或调试器。
取钥工具的研究性 debugger 路线不属于本轮主线，不能据上游宣传推断当前微信版本兼容。
Node 官方文档说明 Zstd API 的可用性随版本变化，因此以真实桥接向量为判断依据：[Node Zlib](https://nodejs.org/api/zlib.html#zlibzstddecompresssyncbuffer-options)。
AES 向量出处：[NIST SP 800-38A](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-38a.pdf)，F.2.5/F.2.6。
