// Decrypt only inside Electron; pass the existing credential to Python through stdin.
const { _electron: electron } = require('playwright');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

(async () => {
  const root = path.resolve(__dirname, '..');
  const directory = path.join(root, '.test-data', 'p19-auth-' + Date.now());
  fs.mkdirSync(directory, {recursive:true});
  fs.mkdirSync(path.join(directory,'app-state'), {recursive:true});
  fs.copyFileSync(path.join(root,'data','app-state','Local State'), path.join(directory,'app-state','Local State'));
  fs.mkdirSync(path.join(directory,'app-state','session'), {recursive:true});
  fs.copyFileSync(path.join(root,'data','app-state','session','Local State'), path.join(directory,'app-state','session','Local State'));
  const env = {...process.env, ZHIXU_DATA_DIR:directory};
  delete env.ELECTRON_RUN_AS_NODE;
  // Use the existing encrypted session keys with the same packaged Electron runtime.
  const app = await electron.launch({args:[], executablePath:path.join(root,'release','win-unpacked','Zhixu.exe'),env});
  let key;
  try {
    key = await app.evaluate(({safeStorage}, bytes) => safeStorage.decryptString(Buffer.from(bytes)),
      [...fs.readFileSync(path.join(root, 'data', 'credential.bin'))]);
  } finally { await app.close(); }
  const child = spawn(path.join(root,'.venv','Scripts','python.exe'),
    ['-X','utf8',path.join(__dirname,'validate-p19-citation-repair.py')],
    {cwd:root,windowsHide:true,stdio:['pipe','inherit','inherit'],env:{...process.env,PYTHONIOENCODING:'utf-8'}});
  child.stdin.end(JSON.stringify({api_key:key}) + '\n');
  key = undefined;
  child.on('exit', code => {process.exitCode = code || 0;});
})().catch(error => { console.error(error.message); process.exitCode=1; });
