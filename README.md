# 知序 · Windows 学习工作台（预览版 0.2）

本地资料库、跨教程关联、个人长期记忆和每次十题的复习工作台。已实际接入你下载在 `D:/Memo/mem0` 的开源 mem0ai 2.2.1，直接调用 `Memory.add`、`Memory.search` 和删除接口。未修改的第三方代码保存在 `vendor/mem0`，来源提交与 SHA256 见 `vendor/mem0/UPSTREAM.json`。使用用户配置的模型服务，不依赖 mem0 云 API。

## 使用

双击桌面“知序”或根目录“启动知序.cmd”，也可运行 `release/win-unpacked/Zhixu.exe`。可运行目录中的资源必须与 EXE 一起保留。

1. 点击“导入学习资料”，粘贴文本或导入 Markdown、TXT、SRT、VTT、B 站字幕 JSON。
2. 打开“模型与设置”，填写兼容 API 的基础地址、对话模型名称和自己的 API Key，保存后测试连接。地址应包含服务商要求的 `/v1` 等前缀。
3. 填写同一服务的 Embedding 模型，点击“同步 mem0 记忆”。mem0 从原文提取知识事实，保存到本地向量库，并保留原文出处。设置中显示 mem0 版本、事实数量和待同步数量。每次最多同步 24 个片段或个人记忆，仍有待同步项时可继续点击。未配置时仍可使用本地关键词搜索。
4. 打开资料，收藏选中内容或来源段落；发现关键词关联，或通过 AI 分析关联，再确认或忽略建议。
5. 在“知识问答”中提问，回答提供资料出处；在“长期记忆”中维护讲解偏好、目标和经自己确认的进度。
6. 在“复习与题库”选择整个知识库、某份资料或“仅我的收藏”，生成十道题。

## 十题复习

- 每组 4 道单选、3 道多选、3 道简答，顺序随机；使用随机抽样的来源片段，适当增加近期错题涉及片段的权重。
- 每次向模型请求新题，同组和最近五组的相同题干会被拒绝；校验失败自动重试一次，仍失败不保存不完整题组。
- 资料须至少 200 字，题目必须携带有效来源。形式与出处校验无法保证模型的每一道题在知识上都正确，提交后应结合原文核对。
- 每题 10 分，总分 100；单选按正确答案计分，多选必须完全匹配，错选或漏选均为 0 分。
- 简答结合预先生成的评分要点，由 AI 给出 0–10 分和反馈。模型服务失败时保留草稿，重试即可。
- 交卷前不向界面提供正确答案、解析和评分要点；交卷后查看解析、来源和成绩。练习组与题库记录一起保存在本地。
- 输入简答时自动保存；正常关闭窗口前再次保存草稿。已交卷记录只读，重复提交不会重复计分。

## 数据与隐私

整个项目位于 `D:/rea-tools/video-knowledge-desktop`，双击根目录的“启动知序.cmd”即可运行。默认数据目录为项目旁的 `data`，当前是 `D:/rea-tools/video-knowledge-desktop/data`。其中包含 SQLite 主库、可重建的 Qdrant 本地向量索引及加密凭据文件；桌面缓存与日志存放在 `data/app-state`。备份请先关闭应用，再复制整个数据目录。环境变量 `ZHIXU_DATA_DIR` 可用于指定独立数据目录，设置页面会显示实际位置。

API Key 由 Electron `safeStorage` 使用 Windows 系统保护保存，不写入业务数据库或日志。在线生成、评分、问答及 Embedding 会将需要处理的内容发送给所配置的服务；本地保存不代表完全离线。Embedding 共用对话 API Key，应使用同一服务商或兼容网关。mem0 遥测关闭，其向量、历史与运行状态位于 `data/mem0`。原有资料和题库无需迁移，升级前数据库备份在 `data/backups`。

删除资料会删除其收藏、关联、含该来源的练习，以及引用该资料的问答；不会删除与其无关的问答。编辑普通文本时，搜索片段会重建，旧练习和问答引用将失效并清理；视频/AI 教程编辑保留原始来源片段。请在编辑前导出需要保留的版本。当前没有完整的版本恢复界面。

## 已实现与当前边界

已实现资料管理、收藏、来源检索、关键词/可选语义检索、关系建议与确认、带段落出处的问答、人工可管理的长期记忆、完整十题练习与历史。

B 站自动导入使用可获取的字幕；登录受限或无字幕视频可能无法导入，可手动提供字幕文件。当前没有音频转写、视频截图、完整概念图谱、后台定时复习提醒、自动画像抽取和多设备同步。AI 整理教程保留原始来源，补充内容需核对。不能据此宣称已经完全复刻 BiliNote 或 Obsidian。

当前记忆以用户明确维护为主，同名记忆更新时旧版本退出默认召回。不会根据一次阅读或一次练习自动判定已经掌握知识。

跨教程关联先通过 mem0 召回抽取出的知识事实，再回链原始片段，由 AI 判断关系。关键词检索作为独立补充；未安装上游可选的 spaCy / fastembed，因此 mem0 内部不启用这两项扩展。更换模型使用独立索引空间，需重新同步。同步失败不会影响原资料，失败片段可以重试。

## 开发与验证

Python 3.11 与 Node.js 24，在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
npm.cmd ci
npm.cmd run build
npm.cmd start
```

验证：

```powershell
npm.cmd test
npm.cmd run build
npm.cmd run smoke
```

`scripts/smoke.cjs` 启动真实 Electron 窗口和本机测试 HTTP 服务，不调用收费在线模型。覆盖导入、收藏、记忆、系统加密密钥、真实 mem0 抽取与语义召回、本地 Qdrant、十题生成、关闭时保存与重启恢复、客观题和简答评分、引用问答、来源删除和界面缓存清理。测试数据置于 `.test-data`，不会混入正常知识库。37 项 Python 测试、4 项桌面数据路径测试及 0.2 打包窗口流程已通过，细节见 `docs/verification.md`。

构建 Windows 产物：

```powershell
npm.cmd run build:backend
npm.cmd run build
npm.cmd run dist:win
```

测试打包程序时可将 `ZHIXU_EXECUTABLE` 指向 `release/win-unpacked/Zhixu.exe` 后再运行 smoke。真实在线模型的出题质量、评分一致性和特定视频的字幕获取尚未使用用户凭据实测。

## 工程参考

- [Electron IPC](https://www.electronjs.org/docs/latest/tutorial/ipc)：隔离界面与系统能力。
- [Qdrant Python 客户端](https://github.com/qdrant/qdrant-client)：本地向量索引。
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：可用视频字幕获取。
- [PyInstaller](https://pyinstaller.org/en/latest/operating-mode.html)：Windows 后端打包。
