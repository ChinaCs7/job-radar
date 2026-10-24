// 只暴露三个能力给界面，界面拿不到 Node / Electron 的其他接口
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  openExternal: (url) => ipcRenderer.send("open-external", String(url)),
  openReport: (planId) => ipcRenderer.send("open-report", planId),
  showItem: (p) => ipcRenderer.send("show-item", String(p)),
});
