# B 站第 12 集与腾讯云真实验证

2026-10-25，知序 0.4.1。用户要求用实际链接验证教程生成，并授权配置其腾讯云 API Key。本报告不保存密钥，也不以测试模型响应替代真实生成。

## 输入与结果

- 用户视频：`https://www.bilibili.com/video/BV1AJen6SEVQ?p=12`。跟踪参数移除，分 P 保留；没有把整套课程或第一集当作目标。
- 分集接口确认：第 12 集，`cid=41916106061`，标题“4-评估反射的影响”，目录时长 497 秒，公开媒体实际时长约 496.21 秒。匿名字幕列表为空。
- 已取得约 9.3 MB 的完整公开 MP4；源代码后端与实际打包后端均完成真实下载、Whisper tiny CPU 转写及六张 FFmpeg 截图，没有使用登录 Cookie、伪造字幕或模拟 ASR。
- 生成采用首次较可读的 90 段英文转写快照，总计 8033 字符、首段 0 秒、末段 490.4 秒。第二次在语言约束下的转写出现混杂误识别，未将它用于最终教程。此测试证明处理链可运行，不是 ASR 准确率评估；英文原声宜选自动检测或英语。
- 实际调用用户授权的腾讯云 TokenHub `hy3`，成功生成中文教程，覆盖反射前后 SQL 问答的客观评估、图表的主观评价、位置偏置及二元 rubric。核对了 95% 示例的原始片段；未声称所有模型解释均已人工验证。
- 知识库文档 ID `c9f7391e-5772-43c6-aa96-c3ef96fd8aff`，标题 `BV1AJen6SEVQ P12 · 4-评估反射的影响`；Hy3 初版保留 90 段原始来源、80 处有效引用和六张真实截图。引用 UUID 均属于该资料的当前来源；后续 DeepSeek 版本见文末。
- Hy3 初版已导出 `data/exports/BV1AJen6SEVQ-P12-评估反射的影响-教程.md`，可携带原文来源 / 时间 / 图片。当时的实际打包窗口显示中文教程、80 个出处按钮和六张图片，重启后凭据和资料仍可读取。

## 过程中实际发现并修复的问题

1. **页面壳解析失败。** yt-dlp 2026.10.21 抛出 `Unable to extract initial state`；不能笼统归因于登录。B 站普通匿名 `pagelist` / `player/wbi/v2` / `player/playurl` 接口可用，公开 MP4 可读取。`backend/bilibili.py` 仅在页面提取器异常后补充这条获取路径。精确选择页号与 cid；不存在的页不会回退第 1 集。拒绝不完整 / 试看、非许可媒体主机和重定向，保留大小、超时、取消与临时文件边界。
2. **Windows 文本换行。** Python 将 LF 写成 CRLF 后，原生文件读取保留 CRLF，导致可携带正文计数不匹配。`Notebook.decode_portable` 在计数失败时仅尝试一次归一化，再完整验证元数据。正确计数的原始 CRLF 不改写；1100 个重复 CR 的异常输入以 ValueError 拒绝，避免递归或反复复制。
3. **Hy3 默认深度思考耗尽等待。** 模型列表和小请求正常，但第一次完整教程请求超时。根据[腾讯云深度思考文档](https://cloud.tencent.cn/document/product/1823/131208)，针对四个准确 TokenHub 主机上的 `hy3` / `hy4-preview`，结构化 JSON 请求显式传 `thinking:{type:'disabled'}`。其他服务 / 模型不附加此参数；真实重试成功。

## 配置与验证

接口地址 `https://tokenhub.tencentmaas.com/v1` 与 `hy3` 通过实际模型列表和连接响应核对，接口规范见[腾讯云 API 使用说明](https://cloud.tencent.com.cn/document/product/1823/130078)。Key 最终由运行中的知序原生保存接口写入系统加密凭据；独立辅助加密写入未通过主程序读回，未以该步骤作为配置成功依据。真实主程序保存后，连接测试与重启读取都通过。测试中的临时密钥变量已清除。

新增 helper、精确分 P 媒体集成、CRLF 及异常边界、TokenHub 参数回归都先复现失败后修复。最终 134 项 Python 和 5 项 Node 路径测试通过，TypeScript / Vite、PyInstaller 与 Windows 目录打包通过，两套打包窗口 smoke 通过；独立复核另验证取消清理、重定向拒绝和限定参数。

## 后续按用户要求改用 DeepSeek 图文模型

用户明确指定支持图片的 DeepSeek。当前默认模型已切换为腾讯云 TokenHub 的 `deepseek-v4.1-flash`；其视觉能力与[DeepSeek 官方图像文档](https://api-docs.deepseek.com/zh-cn/guides/vision/)一致，并经过实际调用验证，而非只根据模型名称判断。

先只发送 98.32 秒处的真实截图，不提供字幕文本，服务返回 HTTP 200，正确读出 `1201`、`Airflow sneaker` 及生成 SQL / 反思 V1 / 执行 V2 等框图标签。随后通过知序原生 `tutorial(use_images=true)` 发送六张登记截图和九十段来源，生成中文图文教程，91 处引用均指向当前原始片段。原 Hy3 版本留在历史和原导出中，最新导出为 `data/exports/BV1AJen6SEVQ-P12-DeepSeek图文教程.md`。

为让已有导入笔记可重新使用该视频截图，核对了两库的 URL、全部九十段来源正文及时间完全一致，再将原实际媒体任务的七个文件按 SHA256 验证复制到当前受管理目录，并在同一 SQLite 事务中登记完成任务 / 图片；没有任意附件路径读取入口。操作前备份 `data/backups/before-deepseek-vision-20261025-165912.sqlite3`。

首次长图文生成没有返回有效 JSON，旧教程未被覆盖；依照[DeepSeek 思考模式文档](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/)对指定 TokenHub DeepSeek Flash ID 关闭默认深度思考后重试成功。仅图片输入的请求与完整六图生成都成功；该结论仍不等于每个细节的视觉准确率已经评测。本地记录 `artifacts/deepseek-image-probe.json`、`deepseek-p12-result.json` 和 `deepseek-p12-tutorial.png` 不含 Key。

真实课程生成、语音识别、截图与服务连接使用真实实现和服务。原有十题 / mem0 的自动回归仍使用本机模型响应；没有据此宣称真实在线出题与评分也通过。视频 / 模型兼容性的结论仅限本例及对应修复，不推广到所有 B 站资源。

业务库变更前备份为 `data/backups/before-bili-p12-20261025-164556.sqlite3`。本地忽略的验证记录为 `artifacts/bilibili-p12-20261025-163217.json`（旧版失败）、`bilibili-p12-20261025-164156.json`（首次转写）、`bilibili-p12-20261025-164646.json`（打包媒体流程）、`bilibili-p12-tutorial-result.json` 和 `bilibili-p12-tutorial.png`。这些记录均不保存 API Key。
