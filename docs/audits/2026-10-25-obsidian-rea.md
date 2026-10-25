# Obsidian 本机核心功能审计（局部静态）

日期：2026-10-25。目的：为知序的个人学习流程提供可核对的笔记、链接、检索与收藏需求。没有启动 Obsidian，没有读写用户 vault，没有查看用户配置、第三方插件、凭据或网络流量；原安装文件未修改。

## 对象与证据

| 对象 | 本机路径 | 版本 / SHA-256 |
| --- | --- | --- |
| 已下载核心 | `C:\Users\86177\AppData\Roaming\obsidian\obsidian-1.14.5.asar` | package.json 声明 1.14.5；`3a349274f789b62c5b35ad19de10311909a94e8783033569c2210a4bac491780` |
| 安装启动器 | `D:\obsidian\Obsidian\resources\app.asar` | package.json 声明 1.12.7；`fcfed6233474be16330ffccb734401df1a5e132581e1ff673b1df16656735c1b` |
| 核心 `app.js` | 上述核心 ASAR 成员，3,942,126 bytes | `95b9fd3944625c3b88116878b03d655147fed8cdfe6ddf931f2064ead78ccd5b` |
| 核心 `worker.js` | 上述核心 ASAR 成员，239,777 bytes | `a42f7927658132927e124131fdb7fc69fdb2853097c24158e0fdb245b87c34ae` |
| 核心 `main.js` | 上述核心 ASAR 成员，203,702 bytes | `5d90e3738f7db8fb8ea00d01556d71310fd557c4a3c785601274c2bb875a2cba` |
| 启动器 `main.js` | 启动器 ASAR 成员 | `e5d7d3b41ffe834fded7240e701e55b672d3f1fb74fdabaa4eeff8b17809e46f` |

使用 REA 6.7.0。先导入父任务已有清单，未重复生成核心清单。清单有 398 个 occurrence；随后只选择 `package.json`、`index.html`、`main.js`、`worker.js`、`app.js` 做一次核心分析。读取 4,387,310 bytes，解析 3 个 JS 文件，语法解析失败 0；34 个相关文件不在选定范围。分发代码为压缩 bundle，模块关系与语义图仍然部分覆盖。

证据缩写（均保存在 `artifacts/rea-obsidian-evidence.json`）：

| 缩写 | 返回的 Evidence ID | 用途 |
| --- | --- | --- |
| I | `ev_200ac4b91fe291b480752600d47fd2fdea3d994d1aa85760cfff54ddde326d34` | 父任务核心 inspect_artifact |
| IP | `ev_8198551c7c166fb5e9f93e747ac2ad4be0ddb649db7672fc37b4e725508dc66c` | 复用清单的成员页，页耗尽 |
| A | `ev_fda6d4875da50eaa408bfbed40551304eaedde9b962bac677b08e32dcabbdf3d` | 核心应用完整保留记录 |
| AS | `ev_a8dff17e2a25c02a4ae8e5d98a409d3111954e71b164be44a71b6f89cec175c6` | 核心 summary，明确覆盖与限额 |
| AM | `ev_f9aad55cd63e6fd83df37b7b73d1a6168fe5009c73fd6ed392e6e99301b8c0b0` | `app.js` source-module、原成员哈希与范围 |
| AF | `ev_87494a57c82f69a7f7ac0e5c12464759d7d5bf47819d83543085e16a3cd9ced9` | `app.js` artifact identity |
| WF | `ev_3de17405b71770fb8d538cf5dbf7ae83a2fa4470cc1c5bd3b0db38424501d836` | `worker.js` artifact identity |
| EF | `ev_0d43e264a68e634b3dc975c44db0248cdcea8330bd0b302b07c74fee2428204e` | 核心 package.json / index.html 原成员身份 |
| L | `ev_39db3acb2344fb7e1155994f57feb4eb391377f549ff4db2c9cf01ce843e5328` | 启动器的 package.json / main.js 局部分析 |
| LS | `ev_1eb926a75afc6232d4d34095de967f7dab6f945f48407478ab972ca4944e7cfb` | 启动器 summary、完整性限制 |
| T | `ev_9862c7e900d1519d23450b7410a186f379aae8706917fc0211245bc70b52b3cd` | backlinks 属性语义追踪为 partial、零 seed；不能当作功能不存在 |

## 入口与版本解释

观察：启动器 manifest 指向其 `main.js`。该脚本的 `loadApp(asarPath)` 拼接核心 `main.js`、require 后调用其导出函数；启动分支从应用数据目录选择版本号更高的 `obsidian-*.asar`，先尝试更新包，失败再尝试内置包。核心 `index.html` 明确加载 `enhance.js`、`i18n.js`、`app.js` 等资源。因此 1.12.7 是启动器包版本，1.14.5 是本次审计的已下载核心，不能仅凭启动器版本代替核心版本。[L, LS, EF]

推断边界：上述是分支代码，并未验证当前或下次运行确实装载 1.14.5；也没有核实公开发布的最新版本。核心 manifest 的 `main: index.js` 不足以单独说明桌面入口，启动器的实际 `loadApp` 实现提供了更直接的静态线索。

完整性限制：启动器第一次分析因两个 unpacked 原生成员的声明哈希与伴随文件实测哈希不符而拒绝。第二次明确设置 `integrity_policy: record-and-continue`，仅静态分析选定 JS，保留 `node_modules/btime/binding.node` 与 `node_modules/get-fonts/binding.node` 的矛盾及 untrusted 标记。没有加载这些原生模块，不判断不一致的原因或安全性质。[L, LS]

## 功能发现

以下结论结合 REA 的成员身份与模块证据，以及从同一 ASAR 成员在内存中用已安装的 Babel parser 8.0.4 选取的完整函数体。未执行目标脚本。表中位置为原成员 **UTF-16、0 起点、半开区间**，`app.js` 全部位于第 1 行；这些细粒度函数范围来自补充 AST 读取，不是声称 REA 已恢复完整动态调用图。

| 问题 | 观察到的代码行为 | 位置与依据 | 状态 |
| --- | --- | --- | --- |
| 创建、编辑并保存独立笔记 | `createNewFile` 默认扩展名 md，计算可用路径、创建目录，再调用 vault.create；vault.create 检查已存在文件后调用 adapter.write。vault.modify 更新缓存并写入文件，写失败清缓存并重新抛错。文本保存路径调用 vault.modify；失败恢复 lastSavedData、显示错误并保存文本备份。 | `createNewFile` 1788490–1789060；`modify` 1425359–1425756；文本 `save` 2689494–2690583。[A, AF, AM] | 静态路径已回答；真实保存/崩溃恢复未运行 |
| Markdown 与内部链接 | `generateMarkdownLink` 按 useMarkdownLinks 生成 `[label](path)` 或 `[[path\|label]]`，拼接 heading/block subpath。目标解析包含 .md 补全、相对路径、绝对路径、同目录候选优先和同名候选排序。 | `generateMarkdownLink` 1801104–1801530；`getLinkpathDest` 1750937–1752129；`qm` 778490–778598。[A, AF, AM] | 静态已回答；同名冲突的最终 UI 未验证 |
| 自动反向链接与未解析链接 | worker 从 Markdown AST 生成带 position/link/displayText 的 links/embeds，保留 headings、tags、frontmatterLinks。`jm` 遍历 frontmatterLinks、links、embeds；`getBacklinksForFile` 逐条解析目标，仅收集与当前文件对象相等的引用。`resolveLinks` 分别累积 resolvedLinks 与 unresolvedLinks 的引用数量。 | worker metadata 回调 232395–235155；app `jm` 778668–778771；`getBacklinksForFile` 1754053–1754232；`resolveLinks` 1759800–1760124。[A, WF, AM] | 静态已回答；未冒充语义图完整追踪 |
| 编辑、重命名后的索引维护 | 元数据缓存监听 create/modify/delete/rename；重命名通过 runAsyncLinkUpdate 先记录原引用解析结果，再执行移动并 updateAllLinks。更新策略读取 alwaysUpdateLinks；不为自动时进入确认分支。`updateInternalLinks` 对受影响文件应用改写。 | `renameFile` 1789726–1790019；`runAsyncLinkUpdate` 1790020–1791193；`updateAllLinks` 1791194–1792634；`updateInternalLinks` 1753360–1754052；`watchVaultChanges` 1754718–1755071。[A, AF, AM] | 静态已回答；批量失败/中断事务性未验证 |
| 标签与全文检索 | `_m` 合并 frontmatter 标签与正文 tags；getTags 为嵌套标签递归计父级，并合并大小写变体计数。检索工厂表实际构造 path/file/content/line/block/section/task/tag 等 matcher；NL.match 读取文件名、路径、Markdown 正文与缓存，再执行 matcher。全局搜索根据匹配结果增加/移除结果并更新计数。 | `_m` 778869–779069；`getTags` 1750175–1750730；工厂表 BL 1469625–1470453；`NL.match` 1470625–1471635；`startSearch` 2716537–2717492。[A, AF, AM] | 静态已回答；排序质量、大库性能未验证 |
| 持久书签 | 内置书签保存嵌套 items；add/remove/move 触发 onItemsChanged，重建查找缓存并保存。打开分支区分 file（含 subpath）、folder、search、graph、url。文件重命名会重写匹配书签 path。核心插件数据 saveData 通过 vault.writeConfigJson；getConfigFile 使用 configDir/name.json。 | 书签 `onFileRename` 3264211–3264385；`_onItemsChanged` 3272026–3272161；`saveData` 3272162–3272235；`openBookmark` 3273104–3273855；`getConfigFile` 1418092–1418166；核心包装 `saveData` 2972107–2972392。[A, AF, AM] | 静态已回答；外部修改冲突未验证 |
| 全局与局部关系图 | render 从 metadataCache.resolvedLinks / unresolvedLinks 构建节点边，按 showAttachments/hideUnresolved/showTags/showOrphans 分支处理；过滤查询复用检索 matcher。局部图 SZ 按 localJumps、localForelinks、localBacklinks、localInterlinks 选取邻域。 | graph 内部构图函数 2733294–2734579；外层 render 2733122–2735355；SZ 2401838–2402634。[A, AF, AM] | 静态已回答；布局和交互未运行 |

补充观察：反向链接界面另有 `recomputeUnlinked`，用当前文件 basename 与 frontmatter aliases 构造文本匹配候选。它与真正解析成功的 backlink 是两个分支，不能把“文字提及”和“显式链接”混为一类。没有复刻其完整词边界、标点与语言规则。

## 对知序的实现要求

这些是基于观察提出的产品设计要求，并非宣称已经在知序实现：

1. 能直接新建独立 Markdown 笔记、修改标题和正文，重启可恢复；导入的视频教程也进入同一编辑保存流程。保存失败应可见并保留草稿。
2. 内部链接有可点击目标与具体 heading/block 定位；未解析目标有明确状态。由同一引用索引生成出链、反链与计数，修改、重命名、删除后重算。不要把 AI 推荐的相似资料显示成用户写下的反向链接。
3. 同名标题与路径变更不应丢失资料身份；知序已约定的 UUID 可作为稳定标识，显示名称与 Markdown 导出路径单独维护。此 UUID 方案是知序的设计选择，并非 Obsidian 的已观察实现。
4. 支持正文与 frontmatter 标签、嵌套标签浏览，并提供至少正文/标题或文件名/标签的可组合检索；点击结果回到对应笔记或段落。
5. 书签保存稳定的目标及定位，可重命名、取消与重开；收藏摘录继续保留原文和出处，两者的数据语义应清楚。保存查询和书签分组可分阶段提供。
6. 若本轮已扩大到图谱，图节点/边由确定的引用索引生成，并能点击回到资料；AI 概念关系另标类型。原 `docs/design.md` 明确将全局图谱排除于第一版，所以图谱属于后续或新增范围，不能把未实现图谱自动判成原第一版未完成。

团队协作、云同步、Obsidian Publish、完整第三方插件/API/主题兼容不在原约定的个人学习应用范围，也不在本次功能深挖范围。没有因内置模块名称存在便推断账户服务、云能力或插件兼容性。

## 限制与交付

本次是**局部静态审计**，不是完整 Obsidian 克隆规格或验收。核心应用图报告 34 个 unknown；语义图限额为全局 12,000 / 单文件 6,000 nodes、全局 6,000 / 单文件 2,500 unknown records，保留 5,360 个语义 unknown，并记录额外省略发生次数。压缩代码的动态 receiver、跨函数修改和未选资源仍未知。[AS]

专门对 getBacklinksForFile 的语义追踪没有命中 seed，返回 partial 和 1,246 个相关 unknown。这不否定原函数体存在或其局部代码行为；本报告的细粒度行为结论依赖上表列出的同哈希函数体审读。[T]

未做 vault 真实运行、保存/重启、Markdown 兼容矩阵、大库性能、链接重命名失败恢复或图交互验证。应在知序自己的隔离测试数据中验证这些用户流程，不能把 Obsidian 静态代码当作知序已通过测试。

完整 REA 导出：`D:\rea-tools\video-knowledge-desktop\artifacts\rea-obsidian-evidence.json`，27,239,740 bytes，24 条 canonical Evidence 记录。只使用 target-free 分析与导入记录，本 worker 未 open_binary，也无需关闭父任务的目标。
