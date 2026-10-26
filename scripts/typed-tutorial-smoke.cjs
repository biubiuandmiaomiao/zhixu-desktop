const { _electron:electron }=require('playwright');
const http=require('node:http');const path=require('node:path');const fs=require('node:fs');const assert=require('node:assert/strict');
(async()=>{
 let calls=0;
 const server=http.createServer(async(req,res)=>{
  let body='';for await(const c of req)body+=c;
  const request=JSON.parse(body);const user=JSON.parse(request.messages[1].content);calls++;
  assert.equal(user.sources[0].ref,'S1');
  const result={title:'结构化教程',sections:[{heading:'概述',content:'模型负责生成计划，应用程序负责执行工具。这份结构化讲解保留真实原文来源。'.repeat(3),source_ids:['S1'],frame_ids:[]}]};
  res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({choices:[{message:{content:calls===2?'{'+'"title":"中文草稿':JSON.stringify(result)},finish_reason:calls===2?'length':'stop'}]}));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const root=path.resolve(__dirname,'..');const data=path.join(root,'.test-data','typed-'+Date.now());fs.mkdirSync(data,{recursive:true});
 const env={...process.env,ZHIXU_DATA_DIR:data};delete env.ELECTRON_RUN_AS_NODE;let app;
 try{
  app=await electron.launch({args:process.env.ZHIXU_EXECUTABLE?[]:[root],executablePath:process.env.ZHIXU_EXECUTABLE||undefined,env});const page=await app.firstWindow();
  await page.getByRole('heading',{name:'让知识，在这里生长。'}).waitFor();
  const result=await page.evaluate(async url=>{
   await window.knowledge.call('save_settings',{base_url:url,model:'typed-fixture'});await window.knowledge.saveCredential('typed-fixture');
   const d=await window.knowledge.call('import_text',{title:'结构化证据测试',content:'模型生成计划，应用负责执行工具。'.repeat(8)});
   await window.knowledge.call('tutorial',{id:d.id});return window.knowledge.call('document',{id:d.id});
  },`http://127.0.0.1:${server.address().port}/v1`);
  assert.equal(calls,1);assert(result.document.content.includes(`[来源:${result.segments[0].id}]`));assert(!result.document.content.includes('[来源:S1]'));
  assert.equal(result.tutorial_attempts[0].raw_result.sections[0].source_ids[0],'S1');assert.equal(result.tutorial_attempts[0].status,'saved');
  await page.reload();await page.locator(`.document-card[data-id="${result.document.id}"]`).click();
  await page.getByRole('heading',{name:'教程生成记录',exact:true}).waitFor();assert((await page.locator('#reading-content').innerText()).includes('模型负责生成计划'));
  const repaired=await page.evaluate(async()=>{
   const d=await window.knowledge.call('import_text',{title:'坏JSON留存测试',content:'模型生成计划，应用负责执行工具。'.repeat(8)});
   await window.knowledge.call('tutorial',{id:d.id});return window.knowledge.call('document',{id:d.id});
  });
  assert.equal(calls,3);assert.equal(repaired.tutorial_attempts.length,2);
  assert.equal(repaired.tutorial_attempts[0].status,'saved');
  assert.equal(repaired.tutorial_attempts[1].errors[0].code,'output_truncated');
  assert.equal(repaired.tutorial_attempts[1].raw_result.finish_reason,'length');
  assert(repaired.tutorial_attempts[1].content.includes('中文草稿'));
  await page.reload();
  const persisted=await page.evaluate(id=>window.knowledge.call('document',{id}),repaired.document.id);
  assert.equal(persisted.tutorial_attempts[1].raw_result.response_text,repaired.tutorial_attempts[1].raw_result.response_text);
  console.log('PASS: typed evidence first-call save and actual UI; malformed/truncated JSON draft retained, one bounded repair, exact diagnostics persist after reload.');
 }finally{if(app)await app.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
