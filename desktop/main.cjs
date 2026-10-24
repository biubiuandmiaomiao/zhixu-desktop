const { app, BrowserWindow, ipcMain, dialog, safeStorage, shell, Menu } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const { randomUUID } = require('node:crypto');

let win, backend, dataDir, apiKey = '', closeReady = false, allowClose = false, closing = false;
const pending = new Map();
const allowed = new Set(['bootstrap','document','import_text','import_video','tutorial','update_document',
  'delete_document','add_card','delete_card','save_memory','delete_memory','related','set_relation',
  'search','ask','generate_quiz','quiz','save_draft','submit_quiz','save_settings','test_model','build_index']);

function rpc(action, args = {}) {
  return new Promise((resolve, reject) => {
    if (!backend || backend.exitCode !== null) return reject(new Error('后台服务未启动，请重启应用'));
    const id = randomUUID();
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error('处理超时，请稍后查看结果或重试')); }, 300000);
    pending.set(id, { resolve, reject, timeout });
    backend.stdin.write(JSON.stringify({ id, action, args, api_key: apiKey }) + '\n', 'utf8', error => {
      if (error && pending.has(id)) { clearTimeout(timeout); pending.delete(id); reject(new Error('后台连接已断开')); }
    });
  });
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const root = path.resolve(__dirname, '..');
    const exe = app.isPackaged ? path.join(process.resourcesPath, 'backend', 'zhixu-backend.exe') : path.join(root, '.venv', 'Scripts', 'python.exe');
    const args = app.isPackaged ? [] : ['-X', 'utf8', '-m', 'backend.main'];
    backend = spawn(exe, args, { cwd: app.isPackaged ? process.resourcesPath : root,
      windowsHide: true, stdio: ['pipe','pipe','pipe'], env: { ...process.env, ZHIXU_DATA_DIR: dataDir, PYTHONIOENCODING: 'utf-8' } });
    const timeout = setTimeout(() => reject(new Error('后台启动超时')), 30000);
    readline.createInterface({ input: backend.stdout }).on('line', line => {
      try {
        const value = JSON.parse(line);
        if (value.ready) { clearTimeout(timeout); resolve(); return; }
        const task = pending.get(value.id);
        if (!task) return;
        clearTimeout(task.timeout); pending.delete(value.id);
        value.error ? task.reject(new Error(value.error)) : task.resolve(value.result);
      } catch { /* third-party output must not break the protocol */ }
    });
    backend.stderr.on('data', () => {});
    backend.on('error', () => { clearTimeout(timeout); reject(new Error('后台服务无法启动，请检查安装文件')); });
    backend.on('exit', () => {
      clearTimeout(timeout);
      reject(new Error('后台服务启动失败'));
      for (const task of pending.values()) { clearTimeout(task.timeout); task.reject(new Error('后台服务已退出，请重启应用')); }
      pending.clear();
    });
  });
}

function assertSender(event) {
  if (!win || event.sender !== win.webContents || event.senderFrame !== win.webContents.mainFrame) throw new Error('无效的界面请求');
}

app.whenReady().then(async () => {
  if (!app.requestSingleInstanceLock()) return app.quit();
  dataDir = process.env.ZHIXU_DATA_DIR || path.join(app.getPath('userData'), 'knowledge');
  fs.mkdirSync(dataDir, { recursive: true });
  const secretPath = path.join(dataDir, 'credential.bin');
  try { if (fs.existsSync(secretPath)) apiKey = safeStorage.decryptString(fs.readFileSync(secretPath)); } catch {}
  Menu.setApplicationMenu(null);
  ipcMain.handle('knowledge:call', async (event, action, args) => {
    assertSender(event);
    if (!allowed.has(action) || (args && (typeof args !== 'object' || Array.isArray(args)))) throw new Error('无效操作');
    const result = await rpc(action, args);
    if (action === 'bootstrap') result.has_api_key = Boolean(apiKey);
    return result;
  });
  ipcMain.handle('knowledge:credential', (event, value) => {
    assertSender(event);
    if (typeof value !== 'string' || value.length > 4096 || /[\r\n]/.test(value)) throw new Error('API Key 格式无效');
    if (value && !safeStorage.isEncryptionAvailable()) throw new Error('系统凭据保护不可用，无法安全保存密钥');
    apiKey = value.trim();
    if (apiKey) fs.writeFileSync(secretPath + '.tmp', safeStorage.encryptString(apiKey));
    if (apiKey) fs.renameSync(secretPath + '.tmp', secretPath);
    else if (fs.existsSync(secretPath)) fs.unlinkSync(secretPath);
    return { saved: Boolean(apiKey) };
  });
  ipcMain.handle('knowledge:importFile', async event => {
    assertSender(event);
    const result = await dialog.showOpenDialog(win, { title: '导入学习资料', properties: ['openFile'], filters: [{ name: '文本与字幕', extensions: ['md','txt','srt','vtt','json'] }] });
    if (result.canceled) return null;
    const filename = result.filePaths[0];
    if (fs.statSync(filename).size > 8_000_000) throw new Error('文件过大，请拆分后导入');
    return { title: path.basename(filename, path.extname(filename)), content: fs.readFileSync(filename, 'utf8'), subtitle: ['.srt','.vtt','.json'].includes(path.extname(filename).toLowerCase()) };
  });
  ipcMain.handle('knowledge:export', async (event, documentId) => {
    assertSender(event);
    const data = await rpc('document', { id: documentId });
    const filename = data.document.title.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 100) + '.md';
    const result = await dialog.showSaveDialog(win, { defaultPath: filename, filters: [{ name: 'Markdown', extensions: ['md'] }] });
    if (result.canceled) return false;
    fs.writeFileSync(result.filePath, data.document.content, 'utf8');
    return true;
  });
  ipcMain.handle('knowledge:openLink', async (event, value) => {
    assertSender(event);
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password) throw new Error('只允许打开 HTTPS 网页');
    await shell.openExternal(url.toString());
  });
  ipcMain.on('knowledge:closeReady', event => { assertSender(event); closeReady = true; });
  ipcMain.handle('knowledge:finishClose', async (event, saved) => {
    assertSender(event);
    if (!closing) return;
    if (!saved) {
      const choice = await dialog.showMessageBox(win, { type:'warning', title:'练习尚未保存',
        message:'最新作答保存失败。退出会丢失这部分草稿。', buttons:['返回继续', '仍然退出'], defaultId:0, cancelId:0 });
      if (choice.response !== 1) { closing = false; return; }
    }
    allowClose = true;
    setImmediate(() => win.close());
  });
  try { await startBackend(); } catch (error) { dialog.showErrorBox('知序启动失败', error.message); return app.quit(); }
  win = new BrowserWindow({ width: 1440, height: 960, minWidth: 1100, minHeight: 720, title: '知序 · 学习工作台', backgroundColor: '#f7f8f5',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false } });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', event => event.preventDefault());
  win.on('close', event => {
    if (allowClose || !closeReady) return;
    event.preventDefault();
    if (!closing) { closing = true; win.webContents.send('knowledge:prepareClose'); }
  });
  await win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
});
app.on('window-all-closed', () => app.quit());
app.on('will-quit', () => { if (backend) backend.stdin.end(); });
