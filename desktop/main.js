// Electron 主进程：负责三件事
// 1. 拉起 Python 后端（采集、调度、数据库都在后端），等它就绪
// 2. 打开桌面窗口；关窗口时缩到托盘，后台继续按计划检索（24 小时不间断就靠这个）
// 3. 给界面提供「在系统浏览器打开链接 / 结果页」的能力
const { app, BrowserWindow, Tray, Menu, shell, ipcMain, dialog, nativeImage } = require("electron");
const { spawn, execFile } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const net = require("node:net");
const http = require("node:http");

const DEV = process.argv.includes("--dev");
const ROOT = path.resolve(__dirname, "..");
let port = 17860;
let backend = null;
let win = null;
let tray = null;
let quitting = false;

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => showWindow());
}

function freePort(start) {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once("error", () => resolve(freePort(start + 1)));
    s.once("listening", () => s.close(() => resolve(start)));
    s.listen(start, "127.0.0.1");
  });
}

function backendCommand() {
  if (app.isPackaged) {
    // 打包后：PyInstaller 生成的后端可执行文件放在 resources/backend/
    const exe = path.join(process.resourcesPath, "backend", process.platform === "win32" ? "job-radar-backend.exe" : "job-radar-backend");
    return { cmd: exe, args: [], cwd: path.dirname(exe) };
  }
  const py = process.platform === "win32"
    ? path.join(ROOT, "backend", ".venv", "Scripts", "python.exe")
    : path.join(ROOT, "backend", ".venv", "bin", "python");
  return { cmd: py, args: ["-m", "app"], cwd: path.join(ROOT, "backend") };
}

function startBackend() {
  const { cmd, args, cwd } = backendCommand();
  if (!fs.existsSync(cmd)) {
    dialog.showErrorBox("求职雷达", `找不到后端程序：\n${cmd}`);
    app.exit(1);
    return;
  }
  const env = { ...process.env, JOB_RADAR_PORT: String(port), PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" };
  if (app.isPackaged) {
    // 打包后数据放在用户目录（%APPDATA%/求职雷达/data），开发时用项目下的 data/
    env.JOB_RADAR_DATA = path.join(app.getPath("userData"), "data");
    env.JOB_RADAR_UI = path.join(process.resourcesPath, "ui");
  }
  backend = spawn(cmd, args, { cwd, env, windowsHide: true });
  const logFile = fs.createWriteStream(path.join(app.getPath("userData"), "backend.log"), { flags: "a" });
  backend.stdout.pipe(logFile);
  backend.stderr.pipe(logFile);
  backend.on("exit", (code) => {
    backend = null;
    if (!quitting) {
      dialog.showErrorBox("求职雷达", `后端意外退出（代码 ${code}）。日志在：\n${path.join(app.getPath("userData"), "backend.log")}`);
      app.exit(1);
    }
  });
}

function stopBackend() {
  if (!backend) return;
  if (process.platform === "win32") execFile("taskkill", ["/pid", String(backend.pid), "/T", "/F"]);
  else backend.kill();
}

function waitHealthy(timeoutMs = 30000) {
  const end = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
        res.resume();
        if (res.statusCode === 200) resolve();
        else retry();
      }).on("error", retry);
    };
    const retry = () => (Date.now() > end ? reject(new Error("后端启动超时")) : setTimeout(tryOnce, 300));
    tryOnce();
  });
}

const uiUrl = () => (DEV ? "http://localhost:5173/" : `http://127.0.0.1:${port}/`);
const reportUrl = () => `http://127.0.0.1:${port}/report`;

function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 820, minWidth: 900, minHeight: 600,
    title: "求职雷达",
    icon: path.join(__dirname, "assets", "icon.png"),
    autoHideMenuBar: true,
    backgroundColor: "#ffffff",
    show: false,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true },
  });
  win.loadURL(uiUrl());
  win.once("ready-to-show", () => win.show());
  // 界面里的外部链接一律交给系统浏览器，不在应用窗口里打开
  win.webContents.setWindowOpenHandler(({ url }) => { openSafe(url); return { action: "deny" }; });
  win.on("close", (e) => {
    if (quitting) return;
    e.preventDefault();
    win.hide();
    if (!app.__trayHinted && tray) {
      tray.displayBalloon?.({ title: "求职雷达还在后台运行", content: "会继续按计划检索。右键托盘图标可以退出。" });
      app.__trayHinted = true;
    }
  });
}

function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function openSafe(url) {
  try {
    const u = new URL(url);
    if (u.protocol === "http:" || u.protocol === "https:") shell.openExternal(url);
  } catch { /* 不是合法链接就忽略 */ }
}

function createTray() {
  tray = new Tray(nativeImage.createFromPath(path.join(__dirname, "assets", "tray.png")));
  tray.setToolTip("求职雷达");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "打开求职雷达", click: showWindow },
    { type: "separator" },
    { label: "退出", click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on("click", showWindow);
}

ipcMain.on("open-external", (_e, url) => openSafe(url));
ipcMain.on("open-report", (_event, planId) => openSafe(`${reportUrl()}?plan_id=${encodeURIComponent(typeof planId === 'string' ? planId : 'legacy')}`));
ipcMain.on("show-item", (_e, p) => { if (typeof p === "string" && fs.existsSync(p)) shell.showItemInFolder(p); });

app.whenReady().then(async () => {
  port = DEV ? 17860 : await freePort(17860);
  startBackend();
  try {
    await waitHealthy();
  } catch (e) {
    dialog.showErrorBox("求职雷达", String(e.message || e));
    quitting = true;
    stopBackend();
    app.exit(1);
    return;
  }
  createTray();
  createWindow();
});

app.on("before-quit", () => { quitting = true; stopBackend(); });
app.on("window-all-closed", (e) => e.preventDefault?.());
