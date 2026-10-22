import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// 两个入口：index.html 是 Electron 窗口里的桌面界面，report.html 是在浏览器里打开的结果页
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    rollupOptions: {
      input: { index: fileURLToPath(new URL("index.html", import.meta.url)), report: fileURLToPath(new URL("report.html", import.meta.url)) },
    },
  },
  server: { port: 5173, strictPort: true },
});
