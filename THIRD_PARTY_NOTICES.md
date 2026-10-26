# 第三方依赖与引用

本项目 MIT 许可证适用于自身代码，不替代第三方许可证，也不覆盖招聘网站内容、商标或使用条款。

## 参考实现

[eatmoreduck/boss-zhipin-scraper](https://github.com/eatmoreduck/boss-zhipin-scraper)：Boss 专用浏览器与 CDP 思路参考，上游采用 [MIT](https://github.com/eatmoreduck/boss-zhipin-scraper/blob/master/LICENSE)。当前仓库没有旧 README 提到的 boss_city_codes.json，城市解析以当前代码为准。

## 运行依赖

- [JobSpy](https://github.com/speedyapply/JobSpy)：海外采集依赖，上游 [MIT](https://github.com/speedyapply/JobSpy/blob/main/LICENSE)。
- React、Vite、TypeScript、Electron、Lucide、FastAPI、Uvicorn、httpx、websockets、lxml、pypdf 和 python-multipart 等由包管理器安装，各自许可证以实际安装版本为准。
- package-lock.json 记录前端和桌面依赖；Python 依赖目前未锁定精确版本，解析结果可能随时间变化。

发布捆绑安装包时，应另行收集随包依赖的许可证与版权声明；本文不替代安装包的完整许可清单。
