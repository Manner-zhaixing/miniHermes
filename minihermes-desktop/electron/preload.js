/**
 * preload：通过 contextBridge 安全暴露 IPC API 给渲染进程。
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  getBackendUrl: () => ipcRenderer.invoke('backend:url'),
  openPath: (p) => ipcRenderer.invoke('shell:openPath', p),
  openFileDialog: () => ipcRenderer.invoke('dialog:openFile'),
  openDirectoryDialog: () => ipcRenderer.invoke('dialog:openDirectory'),
  quit: () => ipcRenderer.send('app:quit'),
  checkUpdate: () => ipcRenderer.invoke('app:checkUpdate'),
  downloadUpdate: (url, fileName) => ipcRenderer.invoke('app:downloadUpdate', url, fileName),
  installUpdate: (dmgPath) => ipcRenderer.invoke('app:installUpdate', dmgPath),
  platform: process.platform,
});
