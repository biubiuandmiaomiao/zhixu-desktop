const { contextBridge, ipcRenderer } = require('electron');
const actions = new Set(['bootstrap','document','import_text','import_video','tutorial','update_document',
  'delete_document','add_card','delete_card','save_memory','delete_memory','related','set_relation',
  'search','ask','generate_quiz','quiz','save_draft','submit_quiz','save_settings','test_model','test_search','build_index','sync_mem0',
  'resolve_note_link','note_graph','note_versions','restore_note_version','toggle_note_bookmark','map_card_sources','export_document',
  'start_video_job','media_jobs','retry_media_job','cancel_media_job']);
contextBridge.exposeInMainWorld('knowledge', {
  call: (action, args = {}) => {
    if (!actions.has(action)) return Promise.reject(new Error('不支持的操作'));
    return ipcRenderer.invoke('knowledge:call', action, args);
  },
  saveCredential: value => ipcRenderer.invoke('knowledge:credential', value),
  saveSearchCredential: value => ipcRenderer.invoke('knowledge:searchCredential', value),
  importFile: () => ipcRenderer.invoke('knowledge:importFile'),
  importVault: () => ipcRenderer.invoke('knowledge:importVault'),
  exportVault: () => ipcRenderer.invoke('knowledge:exportVault'),
  importMedia: options => ipcRenderer.invoke('knowledge:importMedia', options),
  exportDocument: id => ipcRenderer.invoke('knowledge:export', id),
  openLink: url => ipcRenderer.invoke('knowledge:openLink', url),
  onClosing: callback => {
    ipcRenderer.on('knowledge:prepareClose', () => callback());
    ipcRenderer.send('knowledge:closeReady');
  },
  finishClose: saved => ipcRenderer.invoke('knowledge:finishClose', saved)
});
