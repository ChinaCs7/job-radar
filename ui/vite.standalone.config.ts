import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// 「导出」用的结果页：所有 JS / CSS 内联成一个 HTML 文件，可以离线打开、发到手机上看。
// 后端导出时把数据嵌进 window.__SNAPSHOT__。
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: "dist/standalone",
    emptyOutDir: true,
    rollupOptions: { input: "report.html" },
  },
});
