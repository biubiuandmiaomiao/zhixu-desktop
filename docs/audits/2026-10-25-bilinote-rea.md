# BiliNote 2.4.5：分发程序与核心流程审计

日期：2026-10-25。范围：视频/本地媒体 → 字幕或转写 → 带出处的笔记 → 历史版本与导出。使用 REA 6.7.0 对真实 Windows 分发程序做 PE 检查、WebView2 CDP 观察、受控界面操作和已载入脚本导出；补充审读同版本官方 tag 源码。没有提交视频、调用模型、下载转写模型或配置凭据。没有改动知序产品代码或用户已安装的 Obsidian/vault。

## 对象与身份

| 对象 | 位置 / SHA-256 |
| --- | --- |
| 官方 Windows NSIS 安装包，103,108,607 bytes | `artifacts/reference/BiliNote_2.4.5_x64-setup.exe`；`4790b5fc4af382a5924274fb24bef60b8cbd449c4034eeb2bfbcc0721a3e642a` |
| 解出的 Tauri 主程序，16,580,608 bytes | `artifacts/reference/bilinote-2.4.5-installed/app.exe`；`a40a254977bb862aca9c14e386a43cdd2efea1849cc985e890f090425864cb23` |
| Python sidecar | 同目录 `BiliNoteBackend.exe`；`59689b1c6b91afffe57396845c200f192f1e82b541d000dc80210bf676e8c608` |
| 同版本官方 tag 源码压缩包 | `artifacts/reference/BiliNote-v2.4.5-source.zip`；`a1d55ebfed24b3d3a4ac44cc3365c73249437d5b1797d30c12bbe1a75a2be9d5` |
| 实际载入的主前端 bundle | `http://tauri.localhost/assets/index-BaRDp64y.js`；2,180,450 bytes；`ba9e43e233204d37328668afaee87c125d31ebe77ba301d0ad7cd9159c78ffab` |

上表路径均相对于 `D:/rea-tools/video-knowledge-desktop`。安装包官方下载地址由父任务核对，本审计结束再次计算哈希一致。未运行安装器，只运行解出的副本；同版本源码用于补充解释，**不宣称与 sidecar 可执行内容已证明逐字一致**。

REA 证据索引（完整记录在 `artifacts/rea-bilinote-evidence.json`）：

| 缩写 | Evidence ID | 内容 |
| --- | --- | --- |
| P | `ev_f0ca43b7b7785e678f16323ca4b0e0879e9030779c4d6a34d32ed8b33b4a8b3e` | 主程序 PE32+ / x86_64 资源身份 |
| B | `ev_07cc3474e03e418a92fd0c51a533ab0b164da80029309d8dfbfa194c6e7e27fe` | WebView2 155.0.4283.62 的真实 page target |
| C | `ev_262a8b49e691c2dd5b545b19cdd74f45dee988b381789700240067f328406212` | 首次引导、后端就绪、DOM/无障碍树、8 个已载入脚本 |
| X | `ev_0455419f58e7bf8afd04d708242ac29eed02535874f78d123ed8138a59f4816f` | 已捕获脚本的导出及逐文件 SHA-256、来源关系 |
| J | `ev_fb06f8c1031ecf201c45271dd32b40071e0e66893cab38a4c20cd4bc6564e652` | 4 个选定已分发脚本的局部静态分析 |
| JS | `ev_644f25cc916c18d53cc383593cbd345a0a97588a5841c0e95959a2ed7d0429fc` | J 的 summary 与内存限额说明 |
| M | `ev_0d846bf190dd551b95d98538d10e20e1e8abfbea54a4ce664f2e7aef7220a74a` | 进入主界面的受控场景与本地 API 请求 |
| O | `ev_4c3ad5e00233a0aa1aa77c8c023beda6569a1036eca2f52a9d76215ed9aa4273` | 平台列表、本地视频输入、9 种笔记风格的实际操作 |
| T | `ev_4ccffd5078a9595099e2fd8927c16790143391394b2ef7ad2bba7227a3a3c3bc` | 转写设置、可用引擎、本地模型未下载状态 |

## 运行边界与可重复性

APPDATA、LOCALAPPDATA、USERPROFILE、TEMP、WebView2 profile、SQLite、笔记与截图输出均设在 `artifacts/rea/bilinote-runtime-20261025/`。sidecar 在解包副本目录工作，仅影响审计 artifact 目录。后端明确绑定 `127.0.0.1:8483`。没有打开或输出 `_internal/.env`，也没有复用用户的 API key/cookie。

第一次 WebView2 启动虽带 CDP 参数但未开放端口。去掉额外 host-resolver 参数后，CDP `127.0.0.1:51906` 正常可用。首次无凭据会进入四步引导；C 实际观察到“后端已就绪”。为了只审查设置与空白工作台，M 在**这个独立 profile** 中预置 `bilinote-onboarded=1`；这不是宣称已完成正常供应商配置或成功生成笔记。[B, C, M]

REA 执行的动作仅为：等待笔记表单、展开平台列表、选择本地视频、展开风格列表、进入音频转写设置、展开转写器列表。未点击生成、保存供应商、测试模型连接、上传、模型下载或外部视频链接。网络记录能看到健康检查、model_list、transcriber_config、transcriber_models_status 等 GET。界面自身还请求了 jsDelivr 的 KaTeX/高亮样式、字体与 webfontloader，故**启动与界面浏览不能被描述为完全离线**。[M, O, T]

## 实际分发界面与代码确认的能力

| 核心问题 | 观察与证据 | 未验证部分 |
| --- | --- | --- |
| 输入平台与本地媒体 | O 中下拉列表实际显示哔哩哔哩、YouTube、抖音、快手、本地视频。选择本地后出现路径输入及拖拽/选择文件区域。已导出主 bundle 的 AST 中有相同的 5 项 value 映射。[O, X] | 没有上传或下载任何视频；不能据此宣称所有站点当前可访问。 |
| 生成风格 | O 实际展开精简、详细、教程、学术、小红书、生活向、任务导向、商业风格、会议纪要共 9 项。bundle 的对应数组与源代码一致。[O, X] | 不评价模型输出是否真实遵守风格或质量。 |
| 生成格式与视频理解 | M 实际出现目录、原片跳转、原片截图、AI 总结；可选视频理解、采样间隔和拼图尺寸。默认采样间隔 6 秒、2×2 网格。UI 提示视频理解需要多模态模型。当前实际界面在未启用视频理解时禁用截图；选择本地视频时还禁用原片跳转。[M, O] | 未执行截图、拼图或多模态请求；截图复选项不等于已生成图片。 |
| ASR 引擎与模型就绪 | T 实际显示 Faster Whisper 本地、必剪在线、快手在线、Groq 在线、MLX Whisper 仅 macOS。当前配置为 Faster Whisper/tiny，各内置模型显示“未下载”；可配置自定义 repo_id 或本地模型目录。[T] | 未验证准确率、速度、在线引擎可用性及下载成功。 |
| 原文、笔记历史与检索 | M/O 实际显示“生成历史”与标题搜索框；本次 profile 无笔记。主 bundle 的 updateTaskContent 函数将生成文本存为含 ver_id/content/style/model_name/created_at 的版本，并保留此前版本；retryTask 向 generateNote 传相同 task_id。源代码的持久化使用 Zustand + idb-keyval，C 同时看到 keyval-store IndexedDB 名称。[C, M, X] | 没有真实生成记录，不把“历史版本代码存在”当作已通过重启/多次重试验收。 |
| 导出 | 分发 bundle 的真实下载 handler 构造 `text/markdown;charset=utf-8` Blob、文件名 `${title}.md` 并触发下载。对应源码 UI 标为“导出 Markdown”；另有思维导图 SVG 导出 handler。[X] | 空白工作台没有触发文件下载；不宣称 PDF/Word/HTML 已在分发 UI 可用。 |

补充的惰性 AST 查询结果在 `artifacts/rea/bilinote-shipped-frontend-ast.json`。这些是 **C→X 逐字节来源链下的真实分发 JS**，不是只从 tag 中找字符串：

| bundle AST 节点 | UTF-16、0 起点半开范围 | 内容 |
| --- | --- | --- |
| ObjectProperty `updateTaskContent` | 259314–259891 | 收到 Markdown 后创建新版本并保留旧版本 |
| ObjectProperty `retryTask` | 259980–260499 | 重新提交原 task_id，成功受理后置 PENDING |
| ArrayExpression | 633319–633438 | 4 个格式选项 |
| ArrayExpression | 633450–633747 | 9 个风格选项 |
| ArrayExpression | 633763–634001 | 5 个平台选项 |
| ArrowFunctionExpression | 2130935–2131213 | 选定内容导出 Markdown |

## 同版本源码解释的处理链

下列内容来自 `artifacts/reference/BiliNote-2.4.5/` 的完整函数体和 Python AST，属于**同版本源码证据**。未声称已从 PyInstaller sidecar 完整还原代码，亦未以真实媒体触发这些分支。16 个选定文件的 SHA-256 与函数范围保存在 `artifacts/rea/bilinote-source-audit.json`。

1. **字幕优先，缺失才走 ASR。** `backend/app/services/note.py` 的 `NoteGenerator.generate`（82–240 行）先读 transcript 缓存，再尝试 `downloader.download_subtitles`；若字幕为空/失败则下载媒体并 `_get_transcript` → `_transcribe_audio`。已有字幕且不需要截图/视频理解时，只获取元信息，跳过媒体完整下载。Bilibili / YouTube 下载器分别有实际字幕函数（157–256、123–142 行），其他平台并不能仅凭入口名字推断都有字幕。
2. **带时间信息的内容进入生成。** `universal_gpt.py` 的 create_messages（45–81 行）把带 start 的分段文本、风格、格式、备注组成请求；有图时构造 text + image_url 的多模态 content。`prompt_builder.py` 以实际映射追加风格和目录/原片跳转/截图/总结要求。这是生成指令，不能保证模型忠实输出。
3. **截图与原片跳转是后处理。** `_post_process_markdown`（624–654 行）按 formats 处理；`_insert_screenshots`（656–676 行）解析截图时间标记，调用 ffmpeg 抽单帧，再替换成图片链接。`note_helper.py` 处理原片时间标记及来源头，`generate_screenshot` 生成对应秒数的图片路径。目录点击和原片链接渲染还有前端分支。
4. **任务与内容分层落盘。** 路由的 run_note_task（124–164 行）通过串行执行器执行生成，失败/无 Markdown 不写成成功结果；save_note_to_file（84–87 行）保存 JSON，任务状态可轮询。客户端另外保留多次生成版本、选定版本及模型/风格元数据；这与一个任务始终只覆盖单份正文不同。

源码限制与发现：

- `note_helper.py:34` 的内部 replacer 在给局部变量 video_id 赋值前先读取它。只抽取已经审读的纯正则函数 AST、对合成字符串做受控离线探针时，bilibili/youtube/douyin 都抛出 UnboundLocalError；local 返回纯时间文本。探针结果与源码哈希在 `artifacts/rea/bilinote-pure-helper-probe.json`。这是**源码探针**，不等价于已证明分发 sidecar 在真实视频中表现相同；因此报告不把“原片跳转选项存在”扩张为“各平台精确跳转已验证可用”。
- `utils/export.py` 的 ExportUtils.export 声明多格式分支，但所审读类只定义 `_to_pdf`，未定义其调用的 `_to_html`、`_to_word`、`_to_image`。本次只确认实际前端 Markdown 下载代码，不据函数里的格式名称宣称这些输出都工作。
- `generate_screenshot` 对 ffmpeg 非零返回码仅打印错误后仍返回路径。知序应验证截图文件实际存在且可读，再将链接插入正文；不能照搬“得到路径即成功”。

## 对知序的具体要求

1. 保留字幕/原文分段和视频时间点，明确展示当前来源使用平台字幕、人工字幕还是 ASR。字幕已足够且不需图片时可跳过大文件下载；ASR 失败应允许重试或导入字幕。
2. 本地媒体、在线链接和手工字幕进入同一资料流程；站点支持用实际下载/字幕结果验证。未知平台不能只靠 UI 选项宣称完成支持。
3. 生成前可选择适合个人学习的精简/详细/教程等风格，输出格式、截图/视频理解及所用模型能力明确匹配。风格数量是设计选择，无须把营销风格原样全部搬入学习应用。
4. 保存任务状态与可恢复的中间结果；重新生成保留旧正文、模型、风格、日期与出处，能够切换版本并导出当前版本。Obsidian 式手工编辑和 AI 重新生成都不能无提示覆盖已有内容。
5. 时间跳转必须按平台构建并测试；截图、附件及导出都验证真实文件。正文失败提示、缺失来源或空白结果不应记为成功。
6. 保持资料库问答、学习复习和 mem0 的既定边界。BiliNote 的生成风格、笔记版本和源媒体定位补充学习流程，不要求复制其部署监控、站点 cookie 管理或全部平台行为。

## 覆盖与清理

REA 从实际 WebView 导出了 8 个脚本，选择 4 个分析；3 个小文件完成语法解析。主 bundle 的 REA worker 在 1 GiB 上限下耗尽堆，记录为 skipped/partial（没有把它误报成语法错误）。没有重复扩大分析；改用同哈希文件的局部 Babel AST 节点补充上述已界定问题。J/JS 中保留该限制、5 个应用 unknown、504 个语义 unknown。

被动捕获仅覆盖 attach 后窗口且按 origin 过滤；场景的短观察窗口存在未完成事件，completeness 为 incomplete。没有从“本次未捕获某请求”推断应用永不联网。未做真实视频、语音准确率、模型质量、生成后截图/跳转/版本切换、导出文件或故障恢复验收。

结束时对自有 app、sidecar、WebView2 后代进行清理。第二次运行的 CloseMainWindow 请求未使进程退出，遂核实根进程绝对路径后终止其拥有的进程树；`cleanup.json` 记录剩余自有进程为空，51906 与 8483 无监听。未关闭用户的其他应用。再次计算了安装包、app.exe、sidecar 哈希；安装包与主程序和启动前标识一致，没有修改这些可执行文件。

最终证据包：`D:/rea-tools/video-knowledge-desktop/artifacts/rea-bilinote-evidence.json`，9 条 canonical REA 记录，7,456,240 bytes；SHA-256 `688c76739b98e171323f54bafb7f0689431a702fc3623b7c3e0f7152a5735eea`。本 worker 使用 target-free 操作，无原生分析目标需要关闭。
