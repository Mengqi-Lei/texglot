const { contextBridge, ipcRenderer } = require('electron');

function subscribe(channel, callback) {
  const listener = (_event, value) => callback(value);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}
contextBridge.exposeInMainWorld('texglotDesktop', {
  updates: {
    status: () => ipcRenderer.invoke('texglot:updates', 'status'),
    check: () => ipcRenderer.invoke('texglot:updates', 'check'),
    download: () => ipcRenderer.invoke('texglot:updates', 'download'),
    cancel: () => ipcRenderer.invoke('texglot:updates', 'cancel'),
    install: () => ipcRenderer.invoke('texglot:updates', 'install'),
    setAutoCheck: value => ipcRenderer.invoke('texglot:updates', 'auto-check', value),
    onChange: callback => subscribe('texglot:update-state', callback),
    onOpen: callback => subscribe('texglot:update-open', callback),
  },
});
