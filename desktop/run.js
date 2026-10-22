// 启动 Electron 前去掉 ELECTRON_RUN_AS_NODE：VS Code 等编辑器的宿主进程会带上这个变量，
// 它会让 Electron 以纯 Node 模式运行，app 对象拿不到。
const { spawn } = require("node:child_process");
const electron = require("electron");

const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;
const child = spawn(electron, [".", ...process.argv.slice(2)], { cwd: __dirname, env, stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 0));
