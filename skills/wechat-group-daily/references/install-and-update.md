# 安装、加载与更新

供 WorkBuddy 在首次安装、重新加载或用户要求更新 Magic 微信群日报时读取。执行完成后回到 [SKILL.md](../SKILL.md) 的初始化或日常出报流程，复用已有配置。

## 首次从 GitHub 安装

1. 仓库为 `https://github.com/fxbillu/Magic-wechat-group-daily-skills.git`。在合适的本地目录执行 `git clone`；默认使用 `main`，已有克隆则复用并保留其当前分支。缺 Git 或需要用户完成登录/权限操作时说明具体下一步。
2. Skill 源目录为仓库中的 `skills/wechat-group-daily`。优先将工作空间的 `.workbuddy/skills/wechat-group-daily` 以 Windows 目录联接指向这个源码目录，让后续拉取直接作用于同一份程序。先检查目标位置；已有安装按下方更新流程处理。
3. 若当前宿主不支持该加载方式，采用实际支持的导入或复制方式，并记录后续需要同步程序。需要重新加载或开启新对话时，明确告诉用户；报告实际使用的 Skill 路径及 `VERSION`。
4. 在 `%LOCALAPPDATA%\WeChatGroupDaily\安装与更新说明.md` 保存仓库路径、分支、源码/加载路径、加载方式、版本及已确认的配置位置。记录留在包外，不含密钥和聊天。若使用者已指定安装记录位置则沿用。
5. 继续执行 [首次初始化与首报](../SKILL.md#首次在-workbuddy-对话调用)。账号、包外目录、关注群、时区和每日时间由用户确认；桌面入口、写稿和每日任务均使用 Skill 已有流程。

目录联接可在确认实际路径且目标尚不存在后使用 PowerShell 创建；`$WorkspacePath` 和 `$RepoPath` 由本机位置确定：

```powershell
New-Item -ItemType Directory -Force -Path (Join-Path $WorkspacePath '.workbuddy\skills')
New-Item -ItemType Junction -Path (Join-Path $WorkspacePath '.workbuddy\skills\wechat-group-daily') -Target (Join-Path $RepoPath 'skills\wechat-group-daily')
```

安装产生的本地文件留在源码包外，或加入仓库本地排除，不修改已跟踪文件来保存安装状态。遇到旧包内私人配置/数据，按 SKILL 的显式迁移说明保留来源后处理。

## 用户说“更新 Magic 微信群日报”时

1. 读取本机安装记录；没有记录时，从实际加载目录或目录联接目标定位原仓库。ZIP 安装若没有 Git 仓库，先克隆上述仓库并接入原配置，不在 ZIP 目录假装执行更新。
2. 等本项目当前出报任务结束，在该仓库检查分支和本地修改，再执行 `git pull --ff-only`。保留用户修改；有实际冲突或固定在标签上无法直接拉取时，说明情况并由用户选择，不强制重置。
3. 目录联接继续使用同一源码；复制/导入安装则同步新版 Skill 程序。个人配置、密钥、归档、日报和已有定时任务保持原位置，不重新初始化或重复建任务。
4. 按实际需要重新加载 Skill，并只重启本项目阅读服务。在 Windows 更新后，从 `scripts/` 用同一 Python 执行 `tools/desktop.py install`（指定过配置时带上原来的 `--config`），刷新同一个「Magic 群日报」快捷方式及图标，不新增第二个入口。正式多尺寸图标随程序提供，安装时复制到配置旁的 `desktop/` 目录；无需现场绘图。若桌面仍显示旧图标，先刷新桌面；不要为此删除个人配置或重建日报。
5. 更新安装记录，简短报告版本、提交号及需要用户处理的实际问题。

桌面打开验证：双击「Magic 群日报」后，系统默认浏览器应打开 `http://127.0.0.1:8765/`（自定义端口时以实际设置为准）。服务未运行时入口会先启动服务，已有服务则复用。若只出现新标签页，手动输入该地址：能打开阅读台说明服务已运行，应检查快捷方式及浏览器打开步骤；连接被拒绝才继续检查服务启动。浏览器打开报错时提示会保留可手动访问的地址。

日常出报继续按 [SKILL.md](../SKILL.md#首份样例与日常出报)；任务创建/更新只在用户需要时读取 [每日任务说明](scheduling.md)。
