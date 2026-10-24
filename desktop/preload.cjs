const { contextBridge, ipcRenderer } = require('electron');
const actions = new Set(['bootstrap','document','import_text','import_video','tutorial','update_document',
  'delete_document','add_card','delete_card','save_memory','delete_memory','related','set_relation',
  'search','ask','generate_quiz','quiz','save_draft','submit_quiz','save_settings','test_model','build_index']);
contextBridge.exposeInMainWorld('knowledge', {
  call: (action, args = {}) => {
    if (!actions.has(action)) return Promise.reject(new Error('不支持的操作'));
    return ipcRenderer.invoke('knowledge:call', action, args);
  },
  saveCredential: value => ipcRenderer.invoke('knowledge:credential', value),
  importFile: () => ipcRenderer.invoke('knowledge:importFile'),
  exportDocument: id => ipcRenderer.invoke('knowledge:export', id),
  openLink: url => ipcRenderer.invoke('knowledge:openLink', url),
  onClosing: callback => {
    ipcRenderer.on('knowledge:prepareClose', () => callback());
    ipcRenderer.send('knowledge:closeReady');
  },
  finishClose: saved => ipcRenderer.invoke('knowledge:finishClose', saved)
});
