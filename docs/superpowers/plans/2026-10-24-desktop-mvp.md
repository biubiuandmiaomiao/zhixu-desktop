# Windows 视频知识库与十题复习 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. 用户已授权开始开发，在当前聊天内连续执行。

**Goal:** 交付可在 Windows 启动的本地知识桌面应用，优先验证资料收藏、相关检索、长期记忆与每次十题的完整练习闭环。

**Architecture:** Electron 主进程通过 JSON Lines 管理 Python 后端，渲染进程通过白名单 IPC 调用。SQLite 是主存储，Markdown 导出与向量索引可重建；在线服务使用用户配置的兼容接口。无密钥时可管理资料和检索，但不冒充 AI 生成结果。

**Tech Stack:** Electron、Vite、TypeScript、Python 3.11、SQLite、Qdrant local、urllib、unittest、Playwright Electron、PyInstaller。

---

## 文件职责

- `backend/store.py`：实体、来源片段、收藏、关系、记忆、练习的持久化及检索。
- `backend/provider.py`：兼容接口、凭据过滤、超时与 JSON 输出解析。
- `backend/review.py`：十题约束、出题、答案隐藏、作答与评分。
- `backend/knowledge.py`：视频及字幕导入、教程生成、关联候选和引用问答。
- `backend/service.py`、`backend/main.py`：受限操作分发和 JSON Lines 协议。
- `desktop/main.cjs`、`desktop/preload.cjs`：进程、凭据加密、文件对话框和 IPC。
- `src/main.ts`、`src/style.css`：资料、关联、记忆、问答、复习和设置界面。
- `tests/`：业务集成测试；`scripts/smoke.cjs`：实际桌面窗口验证。

## Task 1：本地资料与隔离

- [x] 先写 `tests/test_store.py`，临时数据库写入中文资料，重开后仍可读取；关键词检索能找到具体片段，删除后不返回派生记录；跨知识库不泄漏。

```python
store = Store(temp_dir)
doc = store.add_document('闭包', '闭包能够捕获外层函数的变量。')
assert store.search('闭包')[0]['document_id'] == doc['id']
```

- [x] 运行 `python -m unittest discover -s tests -v`，观察缺少存储实现的失败；实现 schema、分段、中文全文召回、数据目录、删除与记忆作用域，再运行通过。

## Task 2：十题生成与评分

- [x] 先写 `tests/test_review.py`，注入固定模型响应，验证恰好 4/3/3 题、有效来源、答案不提前暴露、重复及无效题拒绝、草稿与交卷持久化、多选完全匹配、简答评分失败可重试、重复交卷不重复计分。

```python
session = review.generate()
assert len(session['questions']) == 10
assert 'answer' not in session['questions'][0]
```

- [x] 运行 `python -m unittest tests.test_review -v` 看到功能未实现的失败；实现经过验证后一次性保存的练习组、草稿、在线评分和题库，再验证通过。

## Task 3：在线服务与知识处理

- [x] 先写 `tests/test_knowledge.py`，验证字幕分段保留时间点、来源引用校验、关联拒绝记录、断网错误提示、模型 JSON 校验及密钥脱敏。
- [x] 运行上述测试观察失败；实现兼容 chat/embedding 接口和 Qdrant local 可选索引，缺少配置时明确降级到本地全文检索。教程和引用问答均不把资料视为指令。
- [x] 视频先获取可用字幕，失败时支持手动导入字幕；不把未实现的转写显示为成功。进程中断后的持久任务可以重试。

## Task 4：桌面工作台

- [x] 配置 `package.json`、TypeScript 和 Vite，建立独立项目仓库及功能分支，不改动其他工作目录。
- [x] 实现受限 preload、启动握手、错误返回、Windows 凭据加密和本地文件导入导出；配置页面明确说明 API 发送范围。
- [x] 实现中文界面与空状态、资料编辑收藏、关联确认、带引用问答、可编辑记忆、十题逐题作答和历史解析。
- [x] 创建 `scripts/smoke.cjs`：启动实际 Electron，导入测试资料、收藏、建立记忆、确认本地搜索、无 Key 出题提示及恢复，截图并检查控制台错误。
- [x] 运行 `npm run build` 与 `npm run smoke`，成功后再打包。

## Task 5：验证与交付

- [x] 运行 `python -m unittest discover -s tests -v`、`npm run build`、`npm run smoke`。
- [x] 用 PyInstaller 打包后端，再生成 Electron Windows 可运行目录；实际启动打包产物验证握手与资料保存。
- [x] 在 `README.md` 写明启动方式、模型配置、存储目录、评分规则和已验证范围；在线真实生成需用户 Key，不能称其已实测。
- [x] 自审来源删除、答案泄漏、重试幂等和接口边界，必要修复后重复相关验证。记录最终测试和交付位置。
