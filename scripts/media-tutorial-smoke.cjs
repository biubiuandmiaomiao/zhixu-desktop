// Real Electron, FFmpeg subtitles/screenshots and background jobs; local model fixture only.
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

async function main() {
  const root = path.resolve(__dirname, '..');
  const directory = path.join(root, '.test-data', 'media-tutorial-' + Date.now());
  fs.mkdirSync(directory, {recursive:true});
  const subtitle = path.join(directory, 'english.srt');
  const video = path.join(directory, 'english.mp4');
  fs.writeFileSync(subtitle, '1\n00:00:00,000 --> 00:00:01,300\nThe model chooses which function to call.\n\n2\n00:00:01,400 --> 00:00:02,900\nThe application runs the actual function.\n');
  execFileSync('ffmpeg', ['-v','error','-f','lavfi','-i','color=c=blue:s=160x90:r=10',
    '-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-i',subtitle,
    '-t','3','-map','0:v','-map','1:a','-map','2:s','-c:v','libx264','-pix_fmt','yuv420p',
    '-c:a','aac','-c:s','mov_text','-metadata:s:s:0','language=eng','-y',video], {windowsHide:true});
  let calls = 0, lastPayload, releaseSecond;
  const secondGate = new Promise(resolve=>{releaseSecond=resolve});
  const server = http.createServer(async (req,res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    const payload = JSON.parse(body);
    const content = payload.messages[1].content;
    const user = JSON.parse(typeof content === 'string' ? content : content[0].text);
    lastPayload = user; calls++;
    if (calls === 2) await secondGate;
    assert(payload.messages[0].content.includes('中文'));
    assert(user.sources.some(s=>s.text.includes('The model')));
    const source = user.sources[0].id;
    const frame = user.frames[0];
    const result = {title:'创建工具',content:calls === 1 ?
      '# Function calling\n\n' + 'The application executes the function requested by the model. '.repeat(4) + ` [来源:${source}]` :
      '# 创建工具的中文教程\n\n' + '模型依据函数说明选择工具，程序负责调用实际函数并返回执行结果。'.repeat(4) +
      ` [来源:${source}]\n\n![工具调用画面][shot]\n\n[shot]: ${frame.asset_url.replace('zhixu-asset:', 'frame:')}`};
    res.writeHead(200, {'Content-Type':'application/json'});
    res.end(JSON.stringify({choices:[{message:{content:JSON.stringify(result)}}]}));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  let app;
  try {
    const env = {...process.env, ZHIXU_DATA_DIR:directory}; delete env.ELECTRON_RUN_AS_NODE;
    app = await electron.launch({args:process.env.ZHIXU_EXECUTABLE ? [] : [root],
      executablePath:process.env.ZHIXU_EXECUTABLE || undefined, env, timeout:45000});
    const page = await app.firstWindow();
    await page.getByRole('heading',{name:'让知识，在这里生长。'}).waitFor();
    await page.evaluate(async base_url=>{
      await window.knowledge.call('save_settings',{base_url,model:'test-tutorial-model'});
      await window.knowledge.saveCredential('isolated-model-fixture');
    },`http://127.0.0.1:${server.address().port}/v1`);
    await page.reload();
    await page.getByRole('button',{name:'导入学习资料',exact:true}).click();
    await page.locator('[data-action="local-media-modal"]').click();
    assert(await page.getByRole('checkbox',{name:'导入后自动生成中文教程'}).isChecked());
    await page.getByLabel('资料标题（可选）').fill('英文原声自动中文教程');
    await app.evaluate(({dialog},file)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[file]})},video);
    await page.locator('#local-media-form button[type="submit"]').click();
    await page.locator('.busy-mask').waitFor({state:'hidden'});
    await page.locator('.global-search input').fill('后台失败刷新时保留的输入');
    await page.getByRole('button',{name:'重试生成中文教程',exact:true}).waitFor({timeout:30000});
    assert.equal(await page.locator('.global-search input').inputValue(),'后台失败刷新时保留的输入');
    const failed = (await page.evaluate(()=>window.knowledge.call('media_jobs')))[0];
    assert.equal(failed.stage,'tutorial_failed');
    assert(failed.error.includes('中文讲解'));
    assert(failed.document_id);
    const original = await page.evaluate(id=>window.knowledge.call('document',{id}),failed.document_id);
    assert(original.document.content.includes('The model'));
    assert.equal(original.assets.length,2);
    assert(await page.getByRole('button',{name:'打开已保存资料 ↗',exact:true}).isVisible());
    await page.getByRole('button',{name:'重试生成中文教程',exact:true}).click();
    await page.locator('.busy-mask').waitFor({state:'hidden'});
    await page.getByRole('button',{name:'打开已保存资料 ↗',exact:true}).click();
    await page.getByRole('heading',{name:'英文原声自动中文教程',exact:true}).waitFor();
    await page.locator('.global-search input').fill('阅读原文时也保留搜索草稿和焦点');
    releaseSecond();
    await page.waitForFunction(()=>document.querySelector('#reading-content')?.textContent.includes('模型依据函数说明'),{},{timeout:30000});
    assert.equal(await page.locator('.global-search input').inputValue(),'阅读原文时也保留搜索草稿和焦点');
    assert(await page.locator('.global-search input').evaluate(el=>el===document.activeElement));
    await page.getByRole('button',{name:'← 我的知识库',exact:true}).click();
    await page.getByRole('button',{name:'打开中文教程 ↗',exact:true}).waitFor({timeout:30000});
    const finished = (await page.evaluate(()=>window.knowledge.call('media_jobs')))[0];
    assert.equal(finished.document_id,failed.document_id);
    assert.equal(finished.stage,'tutorial_completed');
    assert.equal(calls,2);
    assert(lastPayload.frames.length > 0);
    const detail = await page.evaluate(id=>window.knowledge.call('document',{id}),finished.document_id);
    assert.deepEqual(detail.segments.map(s=>s.id),original.segments.map(s=>s.id));
    assert(detail.document.content.includes('中文教程'));
    const exported = await page.evaluate(id=>window.knowledge.call('export_document',{id}),finished.document_id);
    assert(exported.content.includes('[shot]: data:image/jpeg;base64,'));
    assert(!exported.content.includes('[shot]: zhixu-asset:'));
    await page.getByRole('button',{name:'打开中文教程 ↗',exact:true}).click();
    assert((await page.locator('#reading-content').innerText()).includes('模型依据函数说明'));
    assert.equal(await page.locator('#reading-content img').count(),1);
    await page.getByRole('button',{name:'来源片段',exact:true}).click();
    assert((await page.locator('.paper').innerText()).includes('The model chooses'));
    assert.equal((await page.evaluate(()=>window.knowledge.call('bootstrap'))).documents.length,1);
    console.log('PASS: default Chinese tutorial, English-only response rejected without changing sources, retry without duplicate import, reference-image rendering/export, preserved source IDs and focused search drafts.');
  } finally {
    releaseSecond();
    if (app) await app.close();
    await new Promise(resolve=>server.close(resolve));
  }
}
main().catch(error=>{console.error(error);process.exitCode=1});
