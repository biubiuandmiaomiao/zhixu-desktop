const { _electron: electron } = require('playwright');
const { strict: assert } = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const http = require('node:http');

async function main() {
  const directory = path.resolve(__dirname, '..', '.test-data', 'smoke-' + Date.now());
  const artifacts = path.resolve(__dirname, '..', 'artifacts');
  fs.mkdirSync(artifacts, { recursive: true });
  const server = http.createServer(async (req, res) => {
    let raw = ''; for await (const chunk of req) raw += chunk;
    const payload = JSON.parse(raw);
    let output = {};
    if (req.url.endsWith('/embeddings')) {
      output = { data: payload.input.map((text, index) => ({ index, embedding: [1, text.includes('闭包') ? 1 : 0, text.includes('函数') ? 1 : 0, .1] })) };
    } else {
      const prompt = payload.messages[0].content; let user; try { user = JSON.parse(payload.messages[1].content); } catch { user = {raw:payload.messages[1].content}; }
      let value;
      if (user.raw && user.raw.includes('## New Messages')) value = {memory:[{text:'闭包捕获外层变量，装饰器可通过闭包包装函数并添加日志。'}]};
      else if (prompt.includes('grades')) value = { grades: user.answers.map(q => ({ question_id: q.id, score: 8, feedback: '理解了变量捕获，请进一步举例说明生命周期。' })) };
      else if (prompt.includes('questions')) value = { questions: ['single','single','single','single','multiple','multiple','multiple','short','short','short'].map((type, i) => ({
        type, prompt: ['闭包怎样保留外部函数中的变量？','闭包与普通函数返回值有什么不同？','哪种写法能形成捕获变量的闭包？','装饰器包装函数的主要用途是什么？','下面哪些场景适合使用闭包？','装饰器可以为函数添加哪些能力？','关于闭包变量生命周期哪些说法正确？','请用自己的话解释闭包如何捕获变量。','请描述一个装饰器添加日志的过程。','闭包和装饰器之间存在什么联系？'][i],
        options: type === 'short' ? [] : [{ id:'A',text:'通过内层函数保留并使用外部变量' },{ id:'B',text:'能够保存调用间需要的状态' },{ id:'C',text:'所有函数必须使用全局变量' },{ id:'D',text:'函数返回后任何变量都无法访问' }],
        answer: type === 'short' ? [] : type === 'single' ? ['A'] : ['A','B'],
        rubric: type === 'short' ? ['说明外部变量捕获','说明返回函数或包装过程'] : [],
        explanation:'闭包使内层函数能够引用外层作用域变量；装饰器可以通过返回包装函数添加日志等行为。', source_ids:[user.sources[0].id]
      })) };
      else if (prompt.includes('related')) value = { related: true, kind:'shared', reason:'两份资料都讲解闭包捕获变量及装饰器包装函数。' };
      else if (prompt.includes('source_ids')) value = { answer:'闭包保存外部变量，装饰器可通过闭包包装函数并添加日志。[1]', source_ids:[user.sources[0].id] };
      else value = { ok:true };
      output = { choices:[{ message:{ content:JSON.stringify(value) } }] };
    }
    res.writeHead(200, { 'Content-Type':'application/json' }); res.end(JSON.stringify(output));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let app;
  const errors = [];
  async function launch() {
    const env = { ...process.env, ZHIXU_DATA_DIR: directory }; delete env.ELECTRON_RUN_AS_NODE;
    app = await electron.launch({ args:process.env.ZHIXU_EXECUTABLE ? [] : [path.resolve(__dirname, '..')],
      executablePath:process.env.ZHIXU_EXECUTABLE || undefined, env, timeout:45000 });
    const page = await app.firstWindow();
    page.on('pageerror', error => errors.push(error.message));
    await page.getByRole('heading', { name:'让知识，在这里生长。' }).waitFor();
    return page;
  }
  async function settle(page) { await page.locator('.busy-mask').waitFor({ state:'hidden' }); }
  try {
    let page = await launch();
    const content = '# 闭包与装饰器\n\n闭包能够捕获外层函数中的变量。返回的内层函数依然可以引用这些变量，因而保存调用间的状态。装饰器接收一个函数，返回包装函数，可以添加日志、重试和计时等能力。装饰器可以通过闭包保存被包装函数。理解时应关注作用域、变量生命周期和调用顺序。\n\n' + '例如：外层函数接收计数起点，内层函数累加并返回当前计数。返回内层函数后，起点仍然被引用。' .repeat(5);
    await page.getByRole('button', { name:'导入学习资料', exact:true }).click();
    await page.getByLabel('资料标题').fill('Python 闭包与装饰器');
    await page.getByLabel('粘贴文本或 Markdown').fill(content);
    await page.getByRole('button', { name:'保存到知识库' }).click(); await settle(page);
    await page.getByRole('heading', { name:'Python 闭包与装饰器', exact:true }).waitFor();
    await page.getByRole('button', { name:'来源片段', exact:true }).click();
    await page.getByRole('button', { name:'收藏此段', exact:true }).first().click(); await settle(page);
    await page.getByRole('button', { name:'我的收藏', exact:false }).click();
    assert.equal(await page.locator('.note-card').count(), 1);
    await page.getByRole('button', { name:'长期记忆', exact:false }).click();
    await page.getByRole('button', { name:'添加记忆', exact:true }).click();
    await page.getByLabel('标题（同名会替代旧版本）').fill('讲解风格');
    await page.getByLabel('希望助手记住什么').fill('先给例子，再讲概念。');
    await page.getByRole('button', { name:'保存记忆', exact:true }).click(); await settle(page);
    assert.equal(await page.getByRole('heading', { name:'讲解风格' }).count(), 1);
    await page.getByRole('button', { name:'导入学习资料', exact:true }).click();
    await page.getByLabel('资料标题').fill('装饰器与日志案例');
    await page.getByLabel('粘贴文本或 Markdown').fill('装饰器使用闭包保存被包装的函数，并通过内层函数添加日志和计时。闭包捕获外部变量，在包装函数返回后继续使用。' .repeat(6));
    await page.getByRole('button', { name:'保存到知识库' }).click(); await settle(page);
    await page.getByRole('button', { name:'发现关键词关联' }).click(); await settle(page);
    assert(await page.locator('.related-mini').count() > 0);
    await page.getByRole('button', { name:'确认关联', exact:true }).first().click(); await settle(page);
    await page.getByRole('button', { name:'对应段落', exact:false }).first().click(); await settle(page);
    await page.getByRole('heading', { name:'资料出处', exact:true }).waitFor();
    await page.getByRole('button', { name:'关闭', exact:true }).click();
    await page.getByRole('button', { name:'知识关联', exact:false }).click();
    await page.screenshot({ path:path.join(artifacts, 'relations.png') });
    await page.getByRole('button', { name:'复习与题库', exact:false }).click();
    await page.getByRole('button', { name:'生成十道题', exact:false }).click(); await settle(page);
    await page.getByRole('alert').filter({ hasText:'设置' }).waitFor();
    await page.getByRole('button', { name:'模型与设置', exact:true }).click();
    await page.getByLabel('兼容 API 地址（包含 /v1 等前缀）').fill(`http://127.0.0.1:${server.address().port}/v1`);
    await page.getByLabel('对话模型名称').fill('local-test-fixture');
    await page.getByLabel('API Key', { exact:true }).fill('fixture-key-only-for-test');
    await page.getByLabel('Embedding 模型名称').fill('local-test-embedding');
    await page.getByRole('button', { name:'保存设置', exact:true }).click(); await settle(page);
    await page.getByRole('button', { name:'测试已保存的连接' }).click(); await settle(page);
    await page.getByRole('status').filter({ hasText:'连接成功' }).waitFor();
    await page.getByRole('button', { name:'同步 mem0 记忆' }).click(); await settle(page);
    await page.getByRole('status').filter({ hasText:'mem0 已同步' }).waitFor();
    const memoryStatus = await page.evaluate(async () => (await window.knowledge.call('bootstrap')).mem0);
    assert.equal(memoryStatus.engine, 'mem0'); assert.equal(memoryStatus.version, '2.2.1');
    assert(memoryStatus.knowledge_count >= 2); assert(memoryStatus.personal_count >= 1);
    const semanticOnly = await page.evaluate(async () => window.knowledge.call('search', { query:'lexically-unmatched-query' }));
    assert(semanticOnly.results.some(s => s.retrieval === 'mem0' && s.facts.length > 0));
    await page.getByRole('button', { name:'知识库', exact:false }).first().click();
    await page.screenshot({ path:path.join(artifacts, 'library.png') });
    await page.getByRole('button', { name:'复习与题库', exact:false }).click();
    await page.getByRole('button', { name:'生成十道题', exact:false }).click(); await settle(page);
    assert.equal(await page.locator('.question-numbers button').count(), 10);
    assert.equal(await page.locator('.explanation').count(), 0);
    await page.screenshot({ path:path.join(artifacts, 'quiz.png') });
    const firstSession = await page.evaluate(async () => (await window.knowledge.call('bootstrap')).sessions[0]);
    const draft = await page.evaluate(id => window.knowledge.call('quiz', { id }), firstSession.id);
    assert.equal(draft.questions.length, 10);
    assert(draft.questions.every(q => !('answer' in q) && !('rubric' in q)));
    const shortIndex = draft.questions.findIndex(q => q.type === 'short');
    await page.getByRole('button', { name:`第 ${shortIndex+1} 题`, exact:true }).click();
    await page.locator('.question-top').getByText(`第 ${shortIndex+1} / 10 题 · 10 分`, { exact:true }).waitFor();
    // Clicking the active question must not replace a textarea while typing.
    await page.getByRole('button', { name:`第 ${shortIndex+1} 题`, exact:true }).click();
    await page.locator('#short-answer').fill('关闭窗口前的最后一笔草稿');
    const closed = app.waitForEvent('close');
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close());
    await closed; app = null;
    page = await launch();
    await page.getByRole('button', { name:'复习与题库', exact:false }).click();
    await page.locator('.history-list button').first().click(); await settle(page);
    const restored = await page.evaluate(id => window.knowledge.call('quiz', { id }), firstSession.id);
    assert.equal(restored.answers[draft.questions[shortIndex].id], '关闭窗口前的最后一笔草稿');
    for (let i = 0; i < 10; i++) {
      await page.getByRole('button', { name:`第 ${i+1} 题`, exact:true }).click();
      await page.locator('.question-top').getByText(`第 ${i+1} / 10 题 · 10 分`, { exact:true }).waitFor();
      if (await page.locator('#short-answer').count()) await page.locator('#short-answer').fill('闭包通过内层函数捕获外层变量，返回包装函数后仍能引用它。装饰器能包装函数并添加日志。');
      else {
        await page.locator('input[name="choice"][value="A"]').check();
        if (await page.locator('input[type="checkbox"]').count()) await page.locator('input[name="choice"][value="B"]').check();
      }
    }
    await page.getByRole('button', { name:'提交并查看解析' }).click(); await settle(page);
    assert.equal(await page.locator('.score-badge strong').innerText(), '94');
    await page.getByRole('button', { name:'第 8 题', exact:true }).click();
    await page.screenshot({ path:path.join(artifacts, 'review-result.png') });
    await page.getByRole('button', { name:'知识问答', exact:false }).click();
    await page.getByLabel('你的问题').fill('闭包和装饰器有什么联系？');
    await page.getByRole('button', { name:'开始提问', exact:true }).click(); await settle(page);
    assert.equal(await page.locator('.citation').count(), 1);
    await page.screenshot({ path:path.join(artifacts, 'answer.png') });
    assert.deepEqual(errors, []);
    const stored = await page.evaluate(async () => window.knowledge.call('bootstrap'));
    assert.equal(stored.cards.length, 1); assert.equal(stored.memories.length, 1);
    assert.equal(stored.sessions[0].status, 'completed');
    await page.getByRole('button', { name:'知识库', exact:false }).first().click();
    const citedDocument = stored.conversations[0].citations[0].document_id;
    await page.locator(`.document-card[data-id="${citedDocument}"]`).click(); await settle(page);
    await page.evaluate(() => { window.confirm = () => true; });
    await page.getByRole('button', { name:'删除', exact:true }).click(); await settle(page);
    await page.getByRole('button', { name:'复习与题库', exact:false }).click();
    assert.equal(await page.locator('.question-card').count(), 0);
    await page.getByRole('button', { name:'知识问答', exact:false }).click();
    assert.equal(await page.locator('.answer-card').count(), 0);
    assert.deepEqual(errors, []);
    console.log('PASS: actual Electron import, collection, memory, encrypted settings, real mem0 extraction and retrieval, ten-question generation, close/restart draft recovery, scoring 94/100, cited answers and deletion cache cleanup.');
    console.log('Screenshots: ' + artifacts);
  } finally { if (app) await app.close(); await new Promise(resolve => server.close(resolve)); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
