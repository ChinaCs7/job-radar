---
name: 求职雷达（job-radar）
description: 在本机运行的多信源岗位聚合工具；Electron 桌面窗口 + 浏览器结果页，共用一套亮 / 暗 token。
colors:
  primary: "#3370ff"
  primary-hover: "#245bdb"
  primary-soft: "#eef3ff"
  primary-text: "#245bdb"
  on-primary: "#ffffff"
  bg: "#ffffff"
  bg-sunken: "#f5f6f7"
  bg-hover: "#f0f1f3"
  bg-active: "#e9eaed"
  panel: "#ffffff"
  border: "#e4e5e8"
  border-strong: "#d0d3d8"
  text: "#1f2329"
  text-2: "#51565d"
  text-3: "#80868e"
  ok: "#1f9d55"
  ok-soft: "#e8f6ee"
  warn: "#c76a00"
  warn-soft: "#fff4e5"
  danger: "#d83931"
  danger-soft: "#fdecec"
  dark-primary: "#4c84ff"
  dark-primary-hover: "#6b9aff"
  dark-primary-soft: "#1f2b45"
  dark-primary-text: "#84a9ff"
  dark-bg: "#1b1c1e"
  dark-bg-sunken: "#151617"
  dark-bg-hover: "#26282b"
  dark-bg-active: "#2e3034"
  dark-panel: "#212225"
  dark-border: "#2f3134"
  dark-border-strong: "#3d4044"
  dark-text: "#e8e9eb"
  dark-text-2: "#b0b4ba"
  dark-text-3: "#868b92"
  dark-ok: "#4cc27f"
  dark-ok-soft: "#17301f"
  dark-warn: "#f0a33a"
  dark-warn-soft: "#36280f"
  dark-danger: "#f2706a"
  dark-danger-soft: "#3a1c1b"
typography:
  headline:
    fontFamily: "\"Microsoft YaHei UI\", \"PingFang SC\", \"HarmonyOS Sans SC\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: "28px"
    letterSpacing: "-0.01em"
  title:
    fontFamily: "\"Microsoft YaHei UI\", \"PingFang SC\", \"HarmonyOS Sans SC\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: "22px"
  body:
    fontFamily: "\"Microsoft YaHei UI\", \"PingFang SC\", \"HarmonyOS Sans SC\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
    fontFeature: "tnum"
  body-sm:
    fontFamily: "\"Microsoft YaHei UI\", \"PingFang SC\", \"HarmonyOS Sans SC\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "\"Microsoft YaHei UI\", \"PingFang SC\", \"HarmonyOS Sans SC\", \"Segoe UI\", system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.6
  mono:
    fontFamily: "\"Cascadia Mono\", \"SF Mono\", Consolas, monospace"
    fontSize: "12px"
rounded:
  xs: "4px"
  radius: "6px"
  radius-lg: "8px"
  pill: "99px"
spacing:
  2xs: "4px"
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "18px"
  xl: "28px"
components:
  button:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.radius}"
    padding: "0 12px"
    height: "32px"
  button-hover:
    backgroundColor: "{colors.bg-hover}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.radius}"
    padding: "0 12px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-2}"
    rounded: "{rounded.radius}"
    padding: "0 12px"
    height: "32px"
  button-sm:
    padding: "0 8px"
    height: "26px"
    typography: "{typography.body-sm}"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.radius}"
    padding: "0 10px"
    height: "32px"
  chip:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text-2}"
    rounded: "{rounded.pill}"
    padding: "0 10px"
    height: "28px"
    typography: "{typography.body-sm}"
  chip-selected:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.primary-text}"
  seg-option:
    backgroundColor: "transparent"
    textColor: "{colors.text-2}"
    rounded: "{rounded.xs}"
    padding: "0 10px"
    height: "26px"
  seg-option-pressed:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
  badge:
    backgroundColor: "{colors.bg-active}"
    textColor: "{colors.text-2}"
    rounded: "{rounded.xs}"
    padding: "0 6px"
    height: "20px"
    typography: "{typography.label}"
  score-hi:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.primary-text}"
    rounded: "{rounded.xs}"
    padding: "0 6px"
    height: "22px"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.text-2}"
    rounded: "{rounded.radius}"
    padding: "0 10px"
    height: "34px"
  nav-item-active:
    backgroundColor: "{colors.bg-active}"
    textColor: "{colors.text}"
  panel:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.radius-lg}"
  notice:
    backgroundColor: "{colors.bg-sunken}"
    rounded: "{rounded.radius-lg}"
    padding: "10px 14px"
  source-cell:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.radius-lg}"
    padding: "10px 12px"
---

# Design System: 求职雷达（job-radar）

## Overview

**Creative North Star: "安静的值班台"**

这是一张一直开着、偶尔看一眼的工作台：白底或黑底，1px 细边线分区，一个蓝色负责「下一步做什么」，其余全部交给灰阶。参照飞书、Notion 的精致程度做常规后台：信息密度偏高（14px 正文、32px 控件高度），层级靠字重和三级文字灰拉开，而不是靠字号和色块。

亮色是默认主题，暗色在「跟随系统」与「手动选暗色」两种情况下都生效；侧栏底部的分段切换可选亮色 / 暗色 / 系统。两套主题共用同一组变量名，组件只引用变量，所以任何新界面天然支持切换。

使用者明确拒绝：装饰性渐变、玻璃效果、大数字统计卡模板（原话「简约而精巧」）。总览的统计是标题下的一行文字（「今天新增 N 条 · 高匹配 N 条 · 累计 N 条」），不是卡片。

**Key Characteristics:**
- 中性灰阶 + 一个蓝，亮 / 暗两套同名变量
- 系统中文字体，全局等宽数字（tabular-nums）
- 1px 边线分区，几乎不用阴影
- 4 / 6 / 8px 三级圆角，胶囊只给开关、筛选块和状态点
- 状态色（绿 / 琥珀 / 红）只表示状态

## Colors

一个蓝加一套偏冷的中性灰，状态色成对出现（实色 + 浅底），每个颜色都有暗色同名值（frontmatter 中 `dark-` 前缀）。

### Primary
- **飞书蓝**（primary）：主按钮、开关打开、焦点环、「检索中」圆点、选中导航项的图标。暗色下提亮为 dark-primary。
- **深一档蓝**（primary-hover / primary-text）：主按钮悬停；链接、选中筛选块文字、高匹配分文字等「蓝色文字」一律用 primary-text，不用 primary，保证浅底上的对比度。
- **浅蓝底**（primary-soft）：选中筛选块、高匹配分、AI 每日总结、用户聊天气泡、蓝色提示条、输入框焦点光圈、文字选区。

### Neutral
- **纸白 / 墨底**（bg / dark-bg）：页面底色；表头、吸顶栏、保存条也用它，盖住滚动内容。
- **凹陷灰**（bg-sunken）：侧栏、分段选择的槽、默认提示条、信源展开设置、分组标题。
- **悬停 / 按下灰**（bg-hover / bg-active）：所有可交互行和按钮的悬停、按下；bg-active 同时是当前导航项、标签、徽标的底色。
- **面板白**（panel）：卡片、表格容器、输入框、默认按钮的底。亮色下与 bg 相同，暗色下比 bg 高一档，靠这一档区分层次。
- **边线**（border / border-strong）：border 用于分区和行分隔；border-strong 用于控件描边（按钮、输入框、筛选块）和滚动条。
- **三级文字**（text / text-2 / text-3）：正文 / 次要说明 / 提示、表头、时间、占位符。

### Status
- **正常绿**（ok / ok-soft）、**琥珀**（warn / warn-soft）、**警示红**（danger / danger-soft）：信源健康度（状态点、状态徽标、暂停提示条、出错信源格的边线）、日志级别、测试结果文字，以及岗位操作的选中态（收藏为琥珀、已投为绿）。

### Named Rules
**The 一个蓝 Rule.** 界面里只有一个彩色强调色。实心蓝只给主按钮、开关、焦点和运行中状态；其余蓝色出现都用 primary-soft 底 + primary-text 字。一屏只有一个蓝色主按钮（总览是「打开结果页」）。

**The 状态色只表状态 Rule.** 绿、琥珀、红只在表达状态时出现（健康度、错误、日志级别、收藏 / 已投），从不作为装饰、分类色或图表配色。平台、类型这类分类用灰色徽标。

**The 成对主题 Rule.** 组件里不写颜色字面量，一律 `var(--token)`；新增颜色必须同时给出亮、暗两个值，并在三处主题声明里保持一致。

## Typography

**Body Font:** 微软雅黑 UI（Microsoft YaHei UI），回退 苹方 / HarmonyOS Sans SC / Segoe UI / system-ui
**Mono Font:** Cascadia Mono，回退 SF Mono / Consolas

**Character:** 工具型界面，用各平台的系统中文 UI 字体，读起来像操作系统本身；没有展示字体，也不需要。

### Hierarchy
- **Headline**（600，20px，28px 行高，-0.01em）：每页唯一的页标题（h1）。结果页顶栏标题降为 16px。
- **Title**（600，15px，22px）：区块标题（h2：信源、岗位、账号名）；结果页的日期分组标题为 14px。
- **Body**（400，14px，1.6）：正文、表格单元格、按钮、导航。岗位标题用 500 字重（结果页列表里 15px）。AI 回答与总结行高放宽到 1.75。
- **Body small**（400，13px）：页标题下的说明、表头（500，text-3）、提示条、字段提示、筛选块和分段选择的文字。
- **Label**（400，12px）：徽标、信源格的下次时间和新增数、计数、页脚。匹配分为 12px / 600。
- **Mono**（12px）：只用于日志、key、路径这类机器文本。

### Named Rules
**The 14 为本 Rule.** 全站最大字号 20px。层级靠字重（400 / 500 / 600）和三级文字灰拉开，不靠放大字号；不做大数字展示。

**The 等宽数字 Rule.** body 全局开启 `font-variant-numeric: tabular-nums`，表格里的分数、时间、薪资、计数纵向对齐。

## Layout

- **桌面应用：** 两栏网格，左侧 220px 侧栏（品牌、导航、底部运行开关和主题切换），右侧主区独立滚动。内容最大宽 1200px 居中，页内边距 22px / 28px / 40px（上 / 左右 / 下），区块间距 18px，区块内标题与内容间距 10px。
- **页头：** 标题 + 说明在左，按钮右对齐、底边对齐；次按钮在前，蓝色主按钮在最右。
- **信源状态带：** `repeat(auto-fill, minmax(128px, 1fr))`，格间 8px。
- **表单：** 「标签 160px + 控件」两列，行间以 border 分隔、上下 18px；底部吸顶保存条。
- **结果页：** 顶栏吸顶，内容最大宽 1080px，内边距 16px / 20px；日期标题吸顶在顶栏下方；岗位是一张连续列表，行间以 border 分隔。
- **节奏：** 4 / 6 / 8 / 12 / 18 / 28px，控件内间距 6–12px，行内元素间距 8px。
- **响应式：** 860px 以下侧栏收成 64px 纯图标栏、底部区隐藏，页内边距减为 18px / 16px；720px 以下表单改单列；结果页 640px 以下岗位行改为「标题 + 分数」两列，时间 / 状态这类分段筛选横向滚动。

## Elevation & Depth

平面为主、边线分层。层次来自 bg / panel / bg-sunken 三档底色加 1px 边线；阴影只出现在真正浮起或被按下的东西上。

### Shadow Vocabulary
- **浮层**（`box-shadow: var(--shadow-pop)`，亮 `0 6px 24px rgba(31,35,41,.1), 0 1px 3px rgba(31,35,41,.08)`，暗 `0 8px 28px rgba(0,0,0,.45), 0 1px 3px rgba(0,0,0,.4)`）：只用于 toast 这类脱离页面的浮层。
- **按下片**（`box-shadow: 0 1px 2px rgba(0,0,0,.08)`）：分段选择里被选中的那一片，像从槽里浮起一点。
- **开关钮**（`box-shadow: 0 1px 2px rgba(0,0,0,.25)`）：开关的白色圆钮。
- **焦点光圈**（`box-shadow: 0 0 0 3px var(--primary-soft)`，配合 border 变 primary）：输入框、标签输入、聊天输入框获得焦点。

### Named Rules
**The 边线先于阴影 Rule.** 卡片、面板、信源格、表格在静止和悬停时都不加阴影，悬停只换底色或边线色。

## Shapes

- **6px（radius）：** 按钮、输入框、下拉、导航项、分段选择的槽——所有「控件」。
- **8px（radius-lg）：** 面板、信源格、提示条、筛选卡、结果列表、AI 总结、toast——所有「容器」。
- **4px（xs）：** 容器里的小块：标签、徽标、匹配分、分段选择的选项。
- **胶囊 / 圆形：** 只给开关、可多选的筛选块和状态点（8px 圆）。
- 所有分隔都是 1px 实线；没有虚线、双线或粗描边。

## Components

### Buttons
精简、安静，像系统控件。
- **Shape:** 6px 圆角，高 32px（小号 26px），图标 16px，图标与文字间距 6px。
- **默认（次按钮）：** panel 底 + border-strong 描边 + text 字；悬停 bg-hover，按下 bg-active。
- **Primary：** primary 底与描边、on-primary 字；悬停 primary-hover。
- **Ghost：** 无底无边、text-2 字；悬停出 bg-hover 底、字变 text。区块头里的「管理信源 →」「全部结果」用 ghost 小号。
- **Danger：** 默认按钮换 danger 字色，不填红底。
- **Focus：** 全局 `outline: 2px solid primary`，偏移 2px。
- **Disabled：** 透明度 .5，not-allowed 光标。
- 过渡：背景、边线、文字颜色 .12s。

### Chips
- **Style:** 28px 高胶囊，panel 底 + border-strong 描边，text-2 字，可带 12px 的 text-3 计数。
- **State:** 选中（`aria-pressed`）为 primary 描边 + primary-soft 底 + primary-text 字；用于结果页按平台 / 类型 / 地区多选筛选。

### Segmented Control
- bg-sunken 槽 + border 描边 + 2px 内衬；选项 26px 高、4px 圆角、13px 字；选中片为 panel 底 + 按下片阴影 + 500 字重。用于单选筛选（时间范围、岗位范围）和主题切换。

### Cards / Containers
- **Corner Style:** 8px。
- **Background:** panel；默认提示条与展开区用 bg-sunken。
- **Shadow Strategy:** 无，见 Elevation。
- **Border:** 1px border；出错信源格边线为 danger 与 border 按 40% 混合。
- **Internal Padding:** 面板 4px 20px（内部行自带间距），信源格 10px 12px，列表行 14px 16px。

### Inputs / Fields
- **Style:** 32px 高，panel 底，border-strong 描边，6px 圆角，左右 10px；占位符 text-3；下拉用自绘的 12px 折角箭头。
- **Hover:** 描边变 text-3。
- **Focus:** 描边变 primary + 3px primary-soft 光圈；光标色 primary。
- **Tag input:** 与输入框同框，内部标签 22px 高、4px 圆角、bg-active 底，回车或逗号添加。
- **Switch:** 32×18 胶囊，关为 border-strong，开为 primary，圆钮滑动 .18s `cubic-bezier(.2,.8,.2,1)`。

### Navigation
- 侧栏底为 bg-sunken，右侧 1px 边线。导航项 34px 高、6px 圆角、14px、text-2 字、17px 图标。
- 悬停 bg-hover；当前页 bg-active 底 + text 字 + 500 字重，**只有图标变蓝**。
- 右侧可挂 12px 计数或 7px 红色提醒点（信源出问题）。
- 860px 以下只留图标。

### Badges, Score, Status Dot
- **徽标：** 20px 高、4px 圆角、12px；默认 bg-active 底 text-2 字，状态变体为「浅底 + 实色字」（blue / ok / warn / danger）。
- **匹配分：** 最小 30px 宽、22px 高、12px / 600；80 分及以上为 primary-soft 底 primary-text 字，60–79 为灰底 text 字，60 以下为灰底 text-2 字。没有分数显示「—」。
- **状态点：** 8px 圆，ok / warn / danger / 灰，「检索中」为 primary 并以 1.2s 呼吸闪动。

### Notice
- 一行可操作的提示：18px 图标 + 文字（加粗短句 + text-2 说明）+ 右侧小按钮。默认 bg-sunken 底带边线；warn / danger / blue 变体换浅底、去边线、图标着对应实色。用于首次使用引导、信源暂停、自动检索关闭、未填 key。

### Data Table
- 表头吸顶、bg 底、13px / 500 / text-3；单元格 10px 12px，行间 1px border，悬停整行 bg-hover。
- 行操作（收藏 / 已投 / 不合适，ghost 小号图标按钮）默认隐藏，行悬停或获得焦点时显示。
- 岗位标题是按钮，悬停变 primary-text 并加下划线，点击打开原始页面。

### Source Strip Cell（信源状态格）
- 每个信源一个紧凑格：名称（13px / 500）、状态点 + 状态文字、下次时间与新增数（12px，两端对齐）。整格可点，悬停换 border-strong 边线与 bg-hover 底。

### Empty State
- 居中，28px 线性图标 + 一句 500 字重的 text-2 说明 + 一句 text-3 下一步提示，上下 56px。

### Toast
- 底部居中、8px 圆角，反色（text 底、bg 字），13px，浮层阴影，.2s 自下而上淡入，2.4s 后消失。

### Motion
- 颜色类过渡 .12s；开关 .15s / .18s；出现类用 `cubic-bezier(.2,.8,.2,1)`。`prefers-reduced-motion: reduce` 时全部动画与过渡关闭。

## Do's and Don'ts

### Do:
- **Do** 所有颜色走 `var(--token)`，新颜色同时定义亮、暗两值。
- **Do** 每屏只放一个蓝色主按钮，其他操作用默认或 ghost 按钮。
- **Do** 控件用 6px 圆角、容器用 8px、容器内小块用 4px。
- **Do** 用 1px 边线和 bg / panel / bg-sunken 三档底色分层，悬停只换底色或边线。
- **Do** 状态用「浅底 + 实色字」的徽标或 8px 状态点表达，并配文字说明原因。
- **Do** 每条岗位都给出可点回原始页面的入口和信源徽标。
- **Do** 图标用 lucide 线性 SVG，按钮内 16px、导航 17px、提示条 18px。

### Don't:
- **Don't** 使用装饰性渐变、玻璃 / 毛玻璃（backdrop-filter）效果。唯一的渐变用途是窄屏横向滚动行右侧的渐隐遮罩，用来提示还有内容。
- **Don't** 做大数字统计卡；统计写成页标题下的一行文字。
- **Don't** 用超过 20px 的字号，或用字号代替字重来做层级。
- **Don't** 给卡片、面板、表格加阴影；阴影只给 toast、分段选中片和开关钮。
- **Don't** 引入第二个强调色，或把绿 / 琥珀 / 红用作分类色和装饰。
- **Don't** 用实心蓝写文字；蓝色文字一律用 primary-text。
