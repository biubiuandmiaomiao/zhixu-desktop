const { _electron: electron } = require('playwright');
const { strict: assert } = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');

async function main() {
  const root = path.resolve(__dirname, '..');
  const env = {...process.env, ZHIXU_DATA_DIR:path.join(root,'.test-data','notebook-'+Date.now())};
  fs.mkdirSync(env.ZHIXU_DATA_DIR,{recursive:true});
  if (process.env.ZHIXU_REAL_MEDIA) fs.cpSync(path.join(root,'data','models'),path.join(env.ZHIXU_DATA_DIR,'models'),{recursive:true});
  delete env.ELECTRON_RUN_AS_NODE;
  const app = await electron.launch({args:process.env.ZHIXU_EXECUTABLE ? [] : [root], executablePath:process.env.ZHIXU_EXECUTABLE || undefined,env});
  try {
    const page = await app.firstWindow();
    await page.getByRole('heading',{name:'让知识，在这里生长。'}).waitFor();
    const docs = await page.evaluate(async () => {
      const b = await window.knowledge.call('import_text',{title:'变量生命周期',content:'# 机制\n\n变量随引用存活。 #python/closure\n\n引用依然存在。 ^lifetime\n\n`^fake`'});
      const a = await window.knowledge.call('import_text',{title:'闭包手册',content:'# 闭包手册\n\n| 概念 | 说明 |\n|---|---|\n| 闭包 | 捕获变量 |\n\n[[变量生命周期#机制|查看机制]]\n\n[普通内部链接](变量生命周期.md)\n\n[外部文档](https://example.com/docs)\n\n<script>window.__unsafeNote = true</script>\n\n<button data-action="delete-document">恶意按钮</button>\n\n#python/closure'});
      return {a,b};
    });
    await page.reload();
    await page.locator(`.document-card[data-id="${docs.a.id}"]`).click();
    await page.locator('.page-heading').getByRole('heading',{name:'闭包手册',exact:true}).waitFor();
    assert.equal(await page.locator('#reading-content table').count(),1,'Markdown table must render');
    assert.equal(await page.locator('#reading-content script').count(),0);
    assert.equal(await page.locator('#reading-content [data-action="delete-document"]').count(),0);
    assert.equal(await page.evaluate(()=>window.__unsafeNote),undefined);
    await page.locator('#reading-content [data-action="note-link"]').filter({hasText:'查看机制'}).click();
    await page.locator('.page-heading').getByRole('heading',{name:'变量生命周期',exact:true}).waitFor();
    assert(await page.locator('[data-testid="backlinks"]').innerText().then(t=>t.includes('闭包手册')));
    await page.evaluate(async ({a,b})=>{
      const block=await window.knowledge.call('resolve_note_link',{id:a.id,target:'变量生命周期#^lifetime'});
      if(!block.heading_found)throw new Error('Missing canonical block');
    },docs);
    assert.equal(await page.locator('#reading-content #block-lifetime').count(),1,'Block references need a real rendered destination');
    assert.equal(await page.locator('#reading-content #block-fake').count(),0,'Code must not become a block reference');
    await page.locator('[data-action="toggle-note-bookmark"]').click();
    await page.locator('.busy-mask').waitFor({state:'hidden'});
    await page.locator('[data-action="back-library"]').click();
    await page.locator('#bookmark-filter').check();
    assert.equal(await page.locator('.document-card').count(),1);
    await page.locator('#tag-filter').selectOption('python/closure');
    assert.equal(await page.locator('.document-card').count(),1);
    await page.locator('[data-action="clear-filters"]').click();
    await page.locator('[data-action="nav"][data-view="graph"]').first().click();
    await page.locator('[data-testid="note-graph"]').waitFor();
    assert.equal(await page.locator('.graph-node').count(),2);
    assert(await page.locator('.graph-edge').count() >= 1);
    await page.locator(`.graph-node[data-id="${docs.a.id}"]`).press('Enter');
    await page.locator('.page-heading').getByRole('heading',{name:'闭包手册',exact:true}).waitFor();
    const old = await page.evaluate(async id => {
      const versions = await window.knowledge.call('note_versions',{id});
      await window.knowledge.call('update_document',{id,title:'闭包手册',content:'修改后的版本，原始内容仍在历史中。'});
      return versions[0];
    },docs.a.id);
    await page.reload();
    await page.locator(`.document-card[data-id="${docs.a.id}"]`).click();
    await page.locator('[data-action="versions"]').click();
    await page.locator('.version-list').waitFor();
    await page.evaluate(()=>{window.confirm=()=>true});
    const restore = page.locator(`[data-action="restore-version"][data-id="${old.id}"]`);
    await restore.evaluate(el=>{el.closest('details').open=true});
    await restore.click();
    await page.locator('.busy-mask').waitFor({state:'hidden'});
    assert.equal(await page.locator('#reading-content table').count(),1);

    const exportPath = path.join(env.ZHIXU_DATA_DIR,'exported.md');
    await app.evaluate(({dialog},file)=>{dialog.showSaveDialog=async()=>({canceled:false,filePath:file})},exportPath);
    assert(await page.evaluate(id=>window.knowledge.exportDocument(id),docs.a.id));
    assert(fs.readFileSync(exportPath,'utf8').includes('<!-- zhixu-notebook:v1'));
    const vault = path.join(env.ZHIXU_DATA_DIR,'incoming-vault');
    fs.mkdirSync(vault); fs.writeFileSync(path.join(vault,'一.md'),'# 一\n\n[[二]] #vault');fs.writeFileSync(path.join(vault,'二.md'),'# 二\n\n可以回链。');
    await app.evaluate(({dialog},directory)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[directory]})},vault);
    assert.equal((await page.evaluate(()=>window.knowledge.importVault())).imported,2);
    const out = path.join(env.ZHIXU_DATA_DIR,'outgoing-vault');fs.mkdirSync(out);
    await app.evaluate(({dialog},directory)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[directory]})},out);
    assert((await page.evaluate(()=>window.knowledge.exportVault())).exported >= 4);

    const card = await page.evaluate(async () => {
      const d = await window.knowledge.call('import_text',{title:'收藏证据',content:'**闭包**捕获外部变量，保存当前引用。'.repeat(20)});
      const detail = await window.knowledge.call('document',{id:d.id});
      const card = await window.knowledge.call('add_card',{document_id:d.id,text:'闭包捕获外部变量，保存当前引用。',source_ids:[detail.segments[0].id]});
      await window.knowledge.call('update_document',{id:d.id,title:d.title,content:'闭包捕获引用，来源经过了核对后的更新。'.repeat(20)});
      return card;
    });
    await page.reload();
    await page.locator('[data-action="nav"][data-view="cards"]').click();
    const cardRow=page.locator(`[data-card-id="${card.id}"]`);
    assert((await cardRow.innerText()).includes('来源已更新'));
    await cardRow.locator('[data-action="map-card-sources"]').click();
    await page.locator('#source-map-form input[name="source_ids"]').first().check();
    await page.locator('#source-map-form button[type="submit"]').click();
    await page.locator('.busy-mask').waitFor({state:'hidden'});
    assert((await cardRow.innerText()).includes('有效原文出处'));

    if(process.env.ZHIXU_REAL_MEDIA) {
      await app.evaluate(({dialog},file)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[file]})},process.env.ZHIXU_REAL_MEDIA);
      const job = await page.evaluate(()=>window.knowledge.importMedia({screenshots:true,language:'en',title:'真实本地媒体验证'}));
      await page.reload();
      await page.locator('.global-search input').fill('后台完成后也要保留的输入');
      let latest; const deadline=Date.now()+120000;
      while(Date.now()<deadline) {
        latest=await page.evaluate(id=>window.knowledge.call('media_jobs',{id}),job.id);
        if(['completed','failed','cancelled'].includes(latest.status))break;
        await new Promise(resolve=>setTimeout(resolve,500));
      }
      assert.equal(latest.status,'completed',latest.error || 'Media did not complete');
      await new Promise(resolve=>setTimeout(resolve,2300));
      assert.equal(await page.locator('.global-search input').inputValue(),'后台完成后也要保留的输入');
      await page.locator(`.document-card[data-id="${latest.document_id}"]`).click();
      await page.locator('.screenshot-gallery img').first().waitFor();
      const detail=await page.evaluate(id=>window.knowledge.call('document',{id}),latest.document_id);
      assert(detail.segments.length > 0 && detail.segments.some(s=>s.start != null));
      assert(detail.assets.length > 0 && detail.assets.length <= 6);
      const exported=await page.evaluate(id=>window.knowledge.call('export_document',{id}),latest.document_id);
      assert(exported.content.includes('data:image/jpeg;base64,'));
    }
    console.log('PASS: safe Markdown, wiki/backlinks, tags/bookmarks, keyboard graph, version restore, native vault/portable export, stale-source repair'+(process.env.ZHIXU_REAL_MEDIA?', actual Whisper/video/screenshots and input-preserving progress.':'.'));
  } finally { await app.close(); }
}
main().catch(e=>{console.error(e);process.exitCode=1});
