# 群语音转文字

适用于日常接续日报和按自然日归档。处理关注群、指定时间范围内的语音；成功文字保留原消息身份、发言人与时间，供 WorkBuddy 写稿。识别文字可能有误，不冒充人工逐字稿。

## 首次配置

复用 WorkBuddy 已确认的同一 Python，从 Skill 的 `scripts/` 运行：

```powershell
python -B fetch.py voice status
python -B fetch.py voice configure --model-dir "<包外本地模型目录>" --timeout 300
```

`status` 只检查配置、模型文件及依赖是否可发现，`runtime_verified=false` 不代表实际转写通过。配置命令只保存路径，不安装依赖、不加载或下载模型。模型目录需包含 `model.bin`、`config.json`、`tokenizer.json`；也接受包含完整模型快照的 Hugging Face 缓存目录。

实际转写需要 `pilk`、`faster-whisper`、`ctranslate2` 和已有的本地 Whisper 模型；仅装 silk-python 不够。默认 CPU/int8。缺少依赖或模型时先向用户说明下载、安装和空间需求，在已有授权范围内准备，不在每日运行中反复安装。模型来源见 [依赖说明](dependencies.md)，可选语音许可见 [第三方清单](third-party.md)。不把某台开发机曾有的缓存当作使用者已经安装。

## 日常与补跑

正常 `fetch.py daily` 与 `fetch.py archive` 会在统计素材前尝试转写，成功文字计入素材量与活跃统计。无语音不加载模型。模型未配置或单条失败时保留语音占位和原因，不中断其他文字素材；HTML 强制显示转写成功与未转写条数。成功文字按来源缓存，普通重跑不重复识别。

从 CLI／HTTP 条目的 `voice_transcription` 查看成功、失败数；归档消息的 `voice.transcription` 保存状态和脱敏原因。常见原因包括：`VOICE_MODEL_NOT_CONFIGURED`、`VOICE_MODEL_UNAVAILABLE`、`VOICE_DEPENDENCY_MISSING`、`VOICE_MEDIA_UNAVAILABLE`、`VOICE_AUDIO_MISSING`、`VOICE_NO_SPEECH`、`VOICE_TRANSCRIPTION_FAILED`、`VOICE_TIMEOUT`、`VOICE_BUSY`。缺失内容不得由模型补写，也不当作已完整读过。

修复具体缺口后，只补跑冻结归档中未成功的语音：

```powershell
python -B fetch.py voice retry --chat "<稳定群ID>" --date <归档日期>
```

补跑不重采消息或扩大原窗口。素材修订带有持久化恢复标记；中断后重跑 `voice retry` 或相应日常任务会补齐索引和每日状态，即使语音已全部识别成功，也不重复识别。文字变化会更新素材 revision，已有日报保留并显示 stale。WorkBuddy 应重新读取修订后的归档，用新 revision 写同一群同一天的稿件，验稿、重新渲染后再运行 `daily --finish`；不另外创建一份日报，不把旧稿算作新版完成。历史修订不移动较新窗口的游标，也不会把最近一次采集失败改成成功。缺少可核验来源记录的旧归档先按原流程重新采集，再尝试转写；素材仍不足时如实说明，不硬凑日报。

## 资源与文件

- 每批语音在独立 Python 子进程处理，模型加载一次。正常结束调用 CTranslate2 卸载并退出进程；超时结束进程，保留已完成的文字。子进程也监测父任务退出，避免遗留模型进程。
- SILK、PCM、WAV 和按需解密的 `media_*.db` 副本使用包外 `data/voice-work/job-*` 目录；先等待子进程退出，再清理本次任务目录。不修改微信原库、既有核心解密库或其覆盖记录。
- 下次语音任务会回收带本程序标记、创建超过 30 秒且所属进程已结束的遗留目录；跳过活跃、新建、无标记及符号链接目录。父任务被强停时，临时文件的回收发生在后续运行。
- 保留本地模型权重、已安装依赖和 `data/voice-text/` 中成功的转写文字缓存。它们不同于内存／显存中的模型，不需要每天重下；日报不嵌入原音频。旧版本已有的媒体快照不自动删除。

## 验证边界

公共 CLI、真实 HTTP、实际 HTML 和进程生命周期以合成数据检查。真实 Windows 语音库字段与分片、CNG 解密、依赖可安装性、Whisper 准确率和实际内存／显存回落仍需在使用者本机验收；不从合成替身推断这些已通过。

## Windows 实机交接

开发侧只交付脚本和编排。以下结果以 Windows 上的实际运行和使用者确认记录，不要求先安装 pytest 或跑开发测试。

1. 核对实际加载的 Skill 路径与本轮提交／安装回执，复用当前 WorkBuddy 的 Python、账号、包外目录和关注群。先运行 `voice status`；缺依赖或模型时再按授权准备，配置完整本地模型目录。
2. 选择一个已获授权的关注群和日期，先用 `fetch.py archive --chats "<稳定群ID>" --date <日期>` 验证一小批真实语音。核对转写文字、发言人、时间与原语音，特别留意跨群重复消息编号和连续多条语音。
3. 按既有流程让 WorkBuddy 读取该归档、生成稿件、验稿和渲染 HTML；实际打开日报，确认使用了识别文字且注明成功／未转写数。然后再用正常 `daily` 验证接续窗口，无需另建每日任务。
4. 在任务管理器观察本次语音子进程、CPU／内存；使用 CUDA 时也看显存。确认批次结束后该进程退出、占用回落，模型权重保留，任务目录中的音频和媒体副本已清理。不要结束其他项目的 Python 进程。
5. 有真实失败项时修复其具体原因，再运行 `voice retry`。确认成功项不重复识别，原时间窗口不变，旧日报仍可读并提示更新；使用新素材版本更新原稿。没有失败样本则记为未测，不修改微信原库制造故障。
6. 超时／主任务被中止后的进程退出、遗留回收及 Windows 文件锁单独记录。反馈版本／提交、成功和失败条数、脱敏错误码及资源观察结果即可，不回传密钥、原音频、原始聊天或完整个人路径。
