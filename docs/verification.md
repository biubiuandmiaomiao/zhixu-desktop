# 预览版验证记录

日期：2026-10-24

- `python -X utf8 -m unittest discover -s tests -v`：25 项通过。
- `npm run build`：TypeScript 类型检查与 Vite 生产构建通过。
- `npm run smoke`：真实 Electron 开发窗口通过。
- 指定 `ZHIXU_EXECUTABLE=release/win-unpacked/Zhixu.exe` 的 `npm run smoke`：实际打包程序通过。
- 单文件 `release/Zhixu-0.1.0.exe` 已正常启动：出现“知序 · 学习工作台”窗口并在隔离目录创建数据库，正常关闭窗口后退出。自动化完整流程使用上面的解包版，因为单文件启动器不直接暴露 Playwright 所需的调试连接。
- 十题按随机顺序实际作答：单选、多选完全正确；本机测试评分服务将三道简答评为 8 分，最终 94/100，交卷结果持久保存。
- 来源关联已在窗口中发现、确认，并打开对应段落。
- 窗口关闭之前立即输入的最后一笔草稿，在重启后可以恢复。
- 删除引用来源后，题库、问答和已打开的界面缓存均不会再次显示该资料。

在线服务测试使用脚本内明确标识的本机测试 HTTP 服务，模拟生成响应及 Embedding；Qdrant、SQLite、Electron、系统凭据加密与后端 EXE 使用真实实现。上述验证不等于真实模型题目准确性、在线服务稳定性或所有 B 站视频的兼容性已验证。

界面截图保存在 `artifacts/library.png`、`artifacts/relations.png`、`artifacts/quiz.png`、`artifacts/review-result.png`、`artifacts/answer.png`，其中内容均为测试资料。

单文件产物：142082705 字节，SHA256 `6468529670854D7E3671EB5A0021F8FB25AC96EA7F9943FA6F6A7D99B7D6A1E9`。
