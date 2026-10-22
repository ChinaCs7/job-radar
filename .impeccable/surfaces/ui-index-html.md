---
version: 1
slug: "ui-index-html"
primary_target: "ui/index.html"
related_targets: ["ui/report.html"]
---

# 桌面应用 + 结果页

Scope: Electron 桌面窗口（ui/index.html）与浏览器结果页（ui/report.html），共用一套组件和 token。Mode: Operate。

Audience / job: 本人和身边朋友；设好条件 → 让它跑 → 回来看新岗位 → 点原始链接去投。States 重点：信源需要登录 / 被风控、首次使用没有任何配置、没有 AI key、结果为空。

## Direction contract

THESIS: 这类工具的标准做法，按飞书 / Notion 的精致程度做到位：白底或黑底、细边线、蓝色主按钮。拒绝装饰、渐变、玻璃效果和大数字统计卡模板。

OWN-WORLD: 中性灰阶 + 一个蓝（#2563EB 一类），亮暗两套 token 可切换；系统中文字体（微软雅黑 UI / 苹方）；6px 圆角、1px 边线、几乎不用阴影；状态色只用于信源健康度（绿 / 琥珀 / 红）；表格数字等宽。

STORY: 打开就知道：今天新增多少、哪个信源出问题、下一次检索什么时候；点一下就能在浏览器看全部结果，并按天 / 平台 / 类型 / 地区筛选；每条都能点回原始页面。

FIRST VIEWPORT: 左侧 220px 导航（总览、搜索条件、信源与频率、账号与密钥、AI 助手、运行日志，底部是运行开关和主题切换）；主区顶栏为标题 + 「立即检索」次按钮 + 「打开结果页」蓝色主按钮；下面一条信源状态带（每个信源一个紧凑格：名称、状态点、下次时间、新增数），出问题时上方出一条可操作的提示；再下面是最新岗位表格（匹配分、岗位、公司、地点、薪资、信源、发现时间）。

FORM: 常规后台，canon（用户选择的标准方向）；seed key fcada493。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
