// Real Electron/HTTP/SQLite round trip; deterministic model fixture exercises repair and draft display.
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  let calls = 0;
  const server = http.createServer(async (req,res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    const request = JSON.parse(body);
    const user = JSON.parse(request.messages[1].content);
    calls++;
    if (calls === 2) {
      assert.equal(user.validation_errors[0].code,'invalid_source_ids');
      assert(user.draft.content.includes('[来源:wrong-id]'));
    }
    const result = {content:'# 工具执行\n\n' + '应用负责执行实际工具，模型负责提供调用请求。'.repeat(4) +
      (calls !== 2 ? '[来源:wrong-id]\n\n<img src=x onerror="window.__unsafeDraft=true">' : `[来源:${user.sources[0].id}]`)};
    res.writeHead(200,{'Content-Type':'application/json'});
    res.end(JSON.stringify({choices:[{message:{content:JSON.stringify(result)}}]}));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const root = path.resolve(__dirname,'..');
  const directory = path.join(root,'.test-data','tutorial-repair-'+Date.now());
  fs.mkdirSync(directory,{recursive:true});
  const env = {...process.env,ZHIXU_DATA_DIR:directory}; delete env.ELECTRON_RUN_AS_NODE;
  let app;
  try {
    app = await electron.launch({args:process.env.ZHIXU_EXECUTABLE ? [] : [root],
      executablePath:process.env.ZHIXU_EXECUTABLE || undefined,env});
    const page = await app.firstWindow();
    await page.getByRole('heading',{name:'让知识，在这里生长。'}).waitFor();
    const doc = await page.evaluate(async base_url => {
      await window.knowledge.call('save_settings',{base_url,model:'repair-fixture'});
      await window.knowledge.saveCredential('repair-fixture-key');
      const doc = await window.knowledge.call('import_text',{title:'引用修正验收',content:'工具由应用执行，模型负责调用请求。'.repeat(8)});
      await window.knowledge.call('tutorial',{id:doc.id});
      return doc;
    },`http://127.0.0.1:${server.address().port}/v1`);
    await page.reload();
    await page.locator(`.document-card[data-id="${doc.id}"]`).click();
    await page.getByRole('heading',{name:'教程生成记录',exact:true}).waitFor();
    const records = await page.evaluate(id=>window.knowledge.call('document',{id}),doc.id);
    assert.equal(calls,2);
    assert.equal(records.tutorial_attempts.length,2);
    assert.equal(records.tutorial_attempts[0].status,'saved');
    assert.equal(records.tutorial_attempts[1].errors[0].invalid_ids[0],'wrong-id');
    const failed = page.locator('.tutorial-attempts details').filter({hasText:'校验未通过'});
    await failed.locator('summary').click();
    assert((await failed.locator('pre').innerText()).includes('<img src=x'));
    assert((await failed.innerText()).includes('wrong-id'));
    assert.equal(await page.locator('.tutorial-attempts img').count(),0);
    assert.equal(await page.evaluate(()=>window.__unsafeDraft),undefined);
    assert.equal(await page.locator('#reading-content .source-ref').count() > 0 || records.document.content.includes(records.segments[0].id),true);
    await page.getByRole('button',{name:'AI 整理为中文教程',exact:true}).click();
    await page.locator('#tutorial-form button[type="submit"]').click();
    await page.locator('.busy-mask').waitFor({state:'hidden'});
    await page.waitForFunction(()=>!document.querySelector('#tutorial-form'),{},{timeout:3000});
    assert.equal(calls,4);
    assert.equal(await page.locator('.tutorial-attempts details').count(),4);
    const afterFailure = await page.evaluate(id=>window.knowledge.call('document',{id}),doc.id);
    assert.equal(afterFailure.document.content,records.document.content);
    assert.equal(afterFailure.tutorial_attempts[0].status,'validation_failed');
    await page.screenshot({path:path.join(root,'artifacts','tutorial-repair-records.png'),fullPage:true});
    console.log('PASS: automatic citation repair, persisted original/repair drafts, exact invalid ID displayed, escaped draft HTML, and reload persistence.');
  } finally {
    if(app) await app.close();
    await new Promise(resolve=>server.close(resolve));
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
