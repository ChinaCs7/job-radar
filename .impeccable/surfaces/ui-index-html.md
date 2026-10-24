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


## 2026-10-24 方案管理扩展（Operate）

延续既有黑白主题、蓝色主操作、系统中文字体和紧凑工具布局。本轮扩展不替换视觉系统。

THESIS: 一个人可以拥有多个独立求职目标；方案是条件、任务和匹配结果的边界。
OWN-WORLD: 沿用 DESIGN.md 的中性灰、一个蓝、细分隔线，不增加装饰。
STORY: 方案列表是主入口（使用者已确认），聊天助手保持可访问。进入列表 → 按求职者筛选 → 按求职者、方向、城市与工作类型建立独立方案 → 选择方案 → 编辑条件 / 检索 / 查看独立结果；方向×城市组合在创建前预览。
FIRST VIEWPORT: 顶部持续显示当前求职者与方案；主区采用连续方案行，显示条件、候选与推荐数量、编辑/复制/归档。创建使用行内表单，实时预览方向×城市组合。
FORM: 继承既有 canon，原 seed fcada493；这是已明确业务结构的功能扩展，不进行新视觉方向选择。
FINISH: 空状态、错误、提交状态、删除可恢复、主题切换和方案隔离均需验证；独立复核扩展对既有系统的符合性。

## 2026-10-24 扩展完成记录

本轮为代码驱动的 Operate 扩展，无批准的视觉效果图。DESIGN.md 与 .impeccable/design.json 保持既有系统；新增方案页使用既有亮暗颜色变量、15/13/12px 文字层级、32px 控件、6/8px 圆角与细分隔线。720px 以下方案标题和操作分行、表单单列；960px 以下行操作换行。当前方案上下文、顶部任务进度与取消入口、轮询计数刷新及筛选无结果后的清除筛选属于本表面行为，不提升为全局视觉规则。

完成复核结论：ship；窄屏页头、顶部进度、轮询计数与空状态四项修正已解决（复核代理报告）。证据：review/plans/final-light.png、review/plans/final-dark.png（1280×720），review/mobile.png（390×844），review/plans/filtered-empty.png、review/plans/running-fixture.png、review/plans/count-before.png、review/plans/count-after.png；路径相对 .impeccable。
