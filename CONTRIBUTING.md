# 开发与贡献

欢迎文档修正、错误复现、采集器适配和测试。较大改动可先开 Issue 说明目标。

## 本地开发

先按 [README](README.md) 创建 backend/.venv，安装 Python 与两处 npm 依赖。

热更新使用两个终端，先退出已有桌面实例，避免单实例锁或端口占用：

```powershell
# 终端一
cd ui
npm run dev
```

```powershell
# 终端二
cd desktop
npm run dev
```

开发模式加载 localhost:5173，后端固定使用 127.0.0.1:17860。普通源码启动使用已编译的 ui/dist。

单独启动后端，从仓库根目录执行：

```powershell
cd backend
./.venv/Scripts/python.exe -m app
```

macOS / Linux 可用以下路径安装与启动，但尚未完成端到端验收：

```bash
python3.11 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd ui
npm ci
npm run build
cd ../desktop
npm ci
npm start
```

Electron 中已有打包资源路径分支，但没有完整打包配置或可复现安装包流程。

## 环境变量

| 变量 | 默认行为 |
| --- | --- |
| JOB_RADAR_DATA | 项目根目录 data，保存设置、数据库和专用浏览器配置 |
| JOB_RADAR_PORT | 后端直接启动默认 17860，桌面启动由 Electron 设置 |
| JOB_RADAR_CDP_PORT | 浏览器调试端口 9333 |
| JOB_RADAR_UI | 项目根目录 ui/dist |

key 在界面填写，不需要 .env。后端没有公网认证体系，不要直接暴露到互联网。

## 验证

Windows PowerShell：

```powershell
cd backend
./.venv/Scripts/python.exe -m unittest discover -s tests -q
cd ../ui
npm run build
cd ..
git diff --check
```

其他系统将解释器换成 .venv/bin/python。测试使用 work 下的临时数据库和模拟模型；通过不代表招聘网站当前可访问。实站验证应使用独立数据目录与有限预算，记录城市、分页、日期、详情完整度和失败原因。

## 采集器约定

- 不把登录失败、验证码或响应不匹配当作搜索成功。
- 核对实际请求的关键词、城市和分页，保存部分结果并说明停止原因。
- 原始链接、信源与日期来源可追溯，未知日期不能用采集时间替代。
- 遵守全局预算、浏览器串行和取消约束，不绕过验证码。
- 方案条件与匹配判断隔离；账号健康和平台预算保持全局一致。
- 添加有业务意义的测试，不使用真实账号、简历或 key 作为夹具。

提交说明问题、最终行为与验证结果。PR 中注明相关平台边界，界面截图使用虚构数据。不要提交 data、work、登录态、个人简历或未脱敏日志。

安全问题见 [SECURITY.md](SECURITY.md)。贡献按项目 MIT 许可证提供；引入第三方代码应保留原许可证和来源。
