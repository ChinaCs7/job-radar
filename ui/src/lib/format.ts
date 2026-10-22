import type { Job } from "./api";

export const SOURCE_LABEL: Record<string, string> = {
  boss: "Boss 直聘", liepin: "猎聘", "51job": "前程无忧", zhilian: "智联招聘", lagou: "拉勾", "58": "58 同城",
  nowcoder: "牛客", company: "公司官网", xhsjobs: "小红书官网", tencent: "腾讯招聘", v2ex: "V2EX", eleduck: "电鸭",
  xiaohongshu: "小红书", zhihu: "知乎", weibo: "微博", maimai: "脉脉", jike: "即刻",
  bing: "全网搜索（必应）", websearch: "全网搜索（DeepSeek）",
  jobspy: "LinkedIn / Indeed", remoteok: "RemoteOK", remotive: "Remotive", himalayas: "Himalayas",
  wwr: "We Work Remotely", hn: "Hacker News", llm: "AI",
};

/** 结果页「平台」筛选用：没有名字的零散网站（显示成域名的）合并成「其他网站」 */
export function facetPlatform(j: Pick<Job, "source" | "platform">): string {
  const p = platformOf(j);
  return /\.[a-z]{2,}$/i.test(p) ? "其他网站" : p;
}

/** 一条岗位在几个不同平台出现过（自己 + 「另见」），用于「多平台」标记 */
export function platformsOf(j: Pick<Job, "source" | "platform" | "also">): string[] {
  return [...new Set([platformOf(j), ...j.also.map((a) => platformOf(a))])];
}

export const JOB_TYPE_LABEL: Record<string, string> = {
  fulltime: "全职", parttime: "兼职", intern: "实习", contract: "合同 / 外包",
};

/** 信源显示名：全网搜索来的显示实际平台（小红书、脉脉……），其他显示信源名 */
export function platformOf(j: Pick<Job, "source" | "platform">): string {
  return j.platform || SOURCE_LABEL[j.source] || j.source;
}

const WEEK = ["日", "一", "二", "三", "四", "五", "六"];

export function today(): string {
  return localDate(new Date());
}

export function localDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function dayLabel(day: string): string {
  const t = today();
  const y = localDate(new Date(Date.now() - 864e5));
  const d = new Date(day + "T00:00:00");
  const base = `${d.getMonth() + 1}月${d.getDate()}日 周${WEEK[d.getDay()]}`;
  if (day === t) return `今天 · ${base}`;
  if (day === y) return `昨天 · ${base}`;
  return base;
}

/** 「3 分钟前」「14:32」「10-19 14:32」 */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (localDate(d) === today()) return hm(d);
  return `${d.getMonth() + 1}-${d.getDate()} ${hm(d)}`;
}

export function hm(d: Date | string): string {
  const x = typeof d === "string" ? new Date(d) : d;
  return `${String(x.getHours()).padStart(2, "0")}:${String(x.getMinutes()).padStart(2, "0")}`;
}

/** 下次检索：「14:32」或「18 分钟后」 */
export function untilLabel(iso: string | null): string {
  if (!iso) return "—";
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  if (diff <= 30) return "即将开始";
  if (diff < 3600) return `${Math.ceil(diff / 60)} 分钟后`;
  return hm(iso);
}

export function scoreClass(s: number | null): string {
  if (s == null) return "";
  return s >= 80 ? "hi" : s >= 60 ? "mid" : "";
}

export const VERDICT: Record<string, { label: string; cls: string; rank: number }> = {
  recommend: { label: "AI 推荐", cls: "ok", rank: 0 },
  maybe: { label: "可以看看", cls: "warn", rank: 1 },
  "": { label: "未判断", cls: "", rank: 2 },
  no: { label: "不合适", cls: "", rank: 3 },
};
export const verdictOf = (j: Pick<Job, "verdict">) => VERDICT[j.verdict || ""] ?? VERDICT[""];

/** 发布时间：「3 天前」「2 个月前」「1 年前」；太旧的标红 */
export function publishedAgo(p: string | null | undefined): { text: string; days: number } | null {
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(p || "");
  if (!m) return null;
  const d = Math.floor((Date.now() - new Date(+m[1], +m[2] - 1, +m[3]).getTime()) / 864e5);
  if (d < 0) return { text: "今天", days: 0 };
  const text = d === 0 ? "今天" : d < 30 ? `${d} 天前` : d < 365 ? `${Math.floor(d / 30)} 个月前` : `${Math.floor(d / 365)} 年前`;
  return { text, days: d };
}

export function regionLabel(j: Pick<Job, "region" | "remote">): string {
  const r = j.region === "overseas" ? "海外" : "国内";
  return j.remote ? `${r} · 远程` : r;
}
