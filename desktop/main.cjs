const { app, BrowserWindow, Menu, dialog, shell, session } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { startService, requestJSON, activeStatuses } = require('./service.cjs');

let window, service, quitting = false, readyToQuit = false;
const dataDir = path.resolve(process.env.TEXGLOT_DATA_DIR || path.join(os.homedir(), '.texglot'));
// Chromium's profile is separate from documents and persists across upgrades.
app.setPath('userData', path.join(dataDir, 'desktop-profile'));
const single = app.requestSingleInstanceLock();
if (!single) { app.quit(); } else {
  app.on('second-instance', () => { if (window) { if (window.isMinimized()) window.restore(); window.show(); window.focus(); } });
  app.whenReady().then(launch).catch(fail);
}

function t(zh, en) { return app.getLocale().toLowerCase().startsWith('zh') ? zh : en; }
function showWindow() { window?.show(); window?.focus(); }
function external(url) {
  try { const u = new URL(url); if (['https:', 'http:'].includes(u.protocol)) return shell.openExternal(url); } catch {}
}
async function fail(error) {
  dialog.showErrorBox('TeXGlot', `${t('启动失败。详细信息：', 'Could not start TeXGlot:')}\n${error.message || error}`);
  await service?.close(); readyToQuit = true; app.quit();
}
async function launch() {
  window = new BrowserWindow({
    width: 1280, height: 940, minWidth: 760, minHeight: 560,
    title: 'TeXGlot', backgroundColor: '#f5f5f7', show: false,
    icon: path.join(__dirname, 'build', 'icon.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, spellcheck: false },
  });
  window.once('ready-to-show', showWindow);
  window.on('close', event => {
    if (readyToQuit) return;
    event.preventDefault();
    if (process.platform === 'darwin') window.hide(); else app.quit();
  });
  window.webContents.setWindowOpenHandler(({ url }) => { external(url); return { action: 'deny' }; });
  window.webContents.on('will-navigate', (event, url) => {
    if (!service || new URL(url).origin !== service.url) { event.preventDefault(); external(url); }
  });
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  session.defaultSession.on('will-download', (_event, item) => item.setSaveDialogOptions({ defaultPath: item.getFilename() }));
  await window.loadFile(path.join(__dirname, 'loading.html'), { query: { lang: t('zh', 'en') } });
  const engineRoot = app.isPackaged ? path.join(process.resourcesPath, 'engine') : path.join(__dirname, 'engine-dist', 'texglot-engine');
  const executable = path.join(engineRoot, process.platform === 'win32' ? 'texglot-engine.exe' : 'texglot-engine');
  if (!fs.existsSync(executable)) throw new Error(t('应用缺少翻译引擎，请重新安装。', 'The translation engine is missing. Please reinstall the app.'));
  service = await startService({
    executable, dataDir, preferredPort: Number(process.env.TEXGLOT_PORT || 8765),
    logPath: path.join(dataDir, 'desktop-service.log'),
    onExit: () => {
      if (quitting) return;
      dialog.showErrorBox('TeXGlot', t('本地翻译服务已停止，请重新打开应用。已完成的任务会保留。', 'The local service stopped. Reopen TeXGlot to continue; saved tasks are retained.'));
      readyToQuit = true; app.quit();
    },
  });
  const items = [];
  if (process.platform === 'darwin') items.push({ role: 'appMenu' });
  items.push({ label: t('文件', 'File'), submenu: [
    { label: t('打开主窗口', 'Open TeXGlot'), click: showWindow },
    { label: t('在浏览器中打开', 'Open in Browser'), click: () => external(service.url) },
    { type: 'separator' },
    { label: t('打开数据文件夹', 'Open Data Folder'), click: () => shell.openPath(dataDir) },
    { type: 'separator' }, { role: 'quit', label: t('退出 TeXGlot', 'Quit TeXGlot') },
  ]});
  items.push({ role: 'editMenu' }, { role: 'viewMenu' }, { role: 'windowMenu' });
  items.push({ label: t('帮助', 'Help'), submenu: [
    { label: t('使用说明', 'User Guide'), click: () => external('https://github.com/Mengqi-Lei/texglot#quick-start') },
    { label: t('第三方许可', 'Third-party Licenses'), click: () => shell.openPath(path.join(process.resourcesPath, 'THIRD_PARTY_NOTICES.txt')) },
    { label: t('Chromium 许可', 'Chromium Licenses'), click: () => shell.openPath(path.join(process.resourcesPath, 'LICENSES.chromium.html')) },
    { label: t('关于 TeXGlot', 'About TeXGlot'), click: () => app.showAboutPanel() },
  ]});
  app.setAboutPanelOptions({ applicationName: 'TeXGlot', applicationVersion: app.getVersion(), copyright: 'Apache License 2.0', website: 'https://github.com/Mengqi-Lei/texglot' });
  Menu.setApplicationMenu(Menu.buildFromTemplate(items));
  await window.loadURL(service.url);
}

app.on('activate', showWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', event => {
  if (readyToQuit || !single) return;
  event.preventDefault();
  if (quitting) return;
  quitting = true;
  (async () => {
    if (service?.owned) {
      const jobs = await requestJSON(`${service.url}/api/jobs`).catch(() => []);
      if (jobs.some(job => activeStatuses.has(job.status))) {
        const choice = await dialog.showMessageBox(window, {
          type: 'question', title: 'TeXGlot',
          message: t('仍有论文正在处理', 'Papers are still being processed'),
          detail: t('退出会暂停当前任务，已完成的译文会保留，下次可以继续。', 'Quitting stops the current task. Completed translations are saved and can be resumed next time.'),
          buttons: [t('继续运行', 'Keep Running'), t('退出', 'Quit')], defaultId: 0, cancelId: 0,
        });
        if (choice.response === 0) { quitting = false; showWindow(); return; }
      }
    }
    await service?.close(); readyToQuit = true; app.quit();
  })().catch(() => { readyToQuit = true; app.quit(); });
});
