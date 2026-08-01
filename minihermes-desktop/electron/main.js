/**
 * Electron 主进程：窗口管理 + Python 子进程生命周期 + 应用更新。
 */
const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const PythonBridge = require('./python-bridge');

const isDev = !app.isPackaged;
const bridge = new PythonBridge();

// GitHub 仓库（owner/repo），应用内"检查更新"拉取 Releases 用；
// 可用环境变量 MH_GITHUB_REPO 覆盖（打包时临时指向其他仓库）
const GITHUB_REPO = process.env.MH_GITHUB_REPO || 'Manner-zhaixing/miniHermesCode';

// AI 应用不依赖 GPU 硬件加速；禁用可避免无 GPU 环境下崩溃
app.disableHardwareAcceleration();

/** 比较语义化版本号：a > b 返回 1，相等 0，a < b 返回 -1 */
function compareVersions(a, b) {
  const pa = String(a || '').replace(/^v/, '').split('.').map(Number);
  const pb = String(b || '').replace(/^v/, '').split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0, y = pb[i] || 0;
    if (x > y) return 1;
    if (x < y) return -1;
  }
  return 0;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 980,
    minHeight: 640,
    title: 'MiniHermes Desktop',
    backgroundColor: '#f7f7f8',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  // 外部链接交给系统浏览器
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  if (isDev) {
    win.loadURL('http://localhost:5173');
    win.webContents.openDevTools({ mode: 'detach' });
  } else {
    win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }
  return win;
}

// ── 更新相关 ─────────────────────────────────────────────
async function checkForUpdates() {
  const current = app.getVersion();
  if (GITHUB_REPO === 'OWNER/REPO') {
    return { ok: false, error: '未配置 GitHub 仓库地址（main.js 的 GITHUB_REPO）', current };
  }
  try {
    const res = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/releases/latest`, {
      headers: { 'User-Agent': 'MiniHermes-Desktop', Accept: 'application/vnd.github+json' },
      timeout: 15000,
    });
    if (!res.ok) return { ok: false, error: `GitHub API 返回 ${res.status}`, current };
    const rel = await res.json();
    const latest = String(rel.tag_name || '').replace(/^v/, '');
    const dmg = (rel.assets || []).find((a) => /\.dmg$/i.test(a.name));
    return {
      ok: true,
      current,
      latest,
      hasUpdate: compareVersions(latest, current) > 0,
      notes: rel.body || '',
      dmgUrl: dmg ? dmg.browser_download_url : null,
      assetName: dmg ? dmg.name : '',
    };
  } catch (e) {
    return { ok: false, error: e.message, current };
  }
}

async function downloadUpdate(url, fileName) {
  if (!url) return { ok: false, error: '没有可用的安装包下载地址' };
  try {
    const res = await fetch(url, { timeout: 600000 });
    if (!res.ok) return { ok: false, error: `下载失败 HTTP ${res.status}` };
    const buffer = Buffer.from(await res.arrayBuffer());
    const dest = path.join(app.getPath('downloads'), fileName);
    fs.writeFileSync(dest, buffer);
    return { ok: true, path: dest, size: buffer.length };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

app.whenReady().then(() => {
  // 先启动 Python 后端子进程
  bridge.start();

  ipcMain.handle('backend:url', () => bridge.getUrl());

  // 成果面板：用系统默认应用打开文件
  ipcMain.handle('shell:openPath', async (_e, p) => {
    if (typeof p !== 'string' || !p) return { ok: false, error: 'empty path' };
    const err = await shell.openPath(p);
    return err ? { ok: false, error: err } : { ok: true };
  });

  // 上传文件：系统文件选择器（@file 引用用）
  ipcMain.handle('dialog:openFile', async (e) => {
    const win = BrowserWindow.fromWebContents(e.sender);
    const res = await dialog.showOpenDialog(win, {
      title: '选择要引用的文件',
      properties: ['openFile'],
    });
    return { canceled: res.canceled, paths: res.filePaths || [] };
  });

  // 工作目录：系统目录选择器（切换 cwd 用）
  ipcMain.handle('dialog:openDirectory', async (e) => {
    const win = BrowserWindow.fromWebContents(e.sender);
    const res = await dialog.showOpenDialog(win, {
      title: '选择工作目录',
      properties: ['openDirectory', 'createDirectory'],
    });
    return { canceled: res.canceled, paths: res.filePaths || [] };
  });

  // 应用更新：检查最新版本
  ipcMain.handle('app:checkUpdate', async () => {
    const info = await checkForUpdates();
    return {
      ...info,
      repoConfigured: GITHUB_REPO !== 'OWNER/REPO',
    };
  });

  // 应用更新：下载安装包到下载目录
  ipcMain.handle('app:downloadUpdate', async (_e, url, fileName) => downloadUpdate(url, fileName));

  // 应用更新：打开 dmg 引导安装（macOS）
  ipcMain.handle('app:installUpdate', async (_e, dmgPath) => {
    const err = await shell.openPath(dmgPath);
    return err ? { ok: false, error: err } : { ok: true };
  });

  // /exit 命令：退出应用
  ipcMain.on('app:quit', () => app.quit());

  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('will-quit', () => {
  bridge.stop();
});
