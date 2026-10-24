import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Ban, Check, ChevronDown, Download, ExternalLink, Globe, Inbox, Loader2, RefreshCw, Search, Sparkles, Star } from "lucide-react";
import { api, openExternal, type Job, type JobStatus } from "../../lib/api";
import {
  facetPlatform, JOB_TYPE_LABEL, localDate, platformOf, platformsOf, publishedAgo, timeAgo, today, VERDICT, verdictOf,
} from "../../lib/format";
import { AsyncButton, Seg } from "../../components/ui";
import type { PageProps } from "../App";

type Range = "1" | "3" | "7" | "30" | "all";
type Sort = "ai" | "published" | "new" | "salary";
type StatusF = "filtered" | "all" | "new" | "starred" | "applied" | "dismissed";

function toggle<T>(set: Set<T>, v: T): Set<T> {
  const n = new Set(set);
  if (n.has(v)) n.delete(v); else n.add(v);
  return n;
}

/** 用专用浏览器打开（带登录状态）；打不开就退回系统浏览器 */
export async function openJob(url: string, toast?: (m: string) => void) {
  try { await api.openLink(url); }
  catch { openExternal(url); toast?.("专用浏览器打不开，已改用系统浏览器"); }
}

const DEFAULT_VERDICTS = ["recommend", "maybe", ""];

export default function Jobs({ toast, overview }: PageProps) {
  const [all, setAll] = useState<Job[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [range, setRange] = useState<Range>("7");
  const [verdicts, setVerdicts] = useState<Set<string>>(new Set(DEFAULT_VERDICTS));
  const [regions, setRegions] = useState<Set<string>>(new Set());
  const [types, setTypes] = useState<Set<string>>(new Set());
  const [plats, setPlats] = useState<Set<string>>(new Set());
  const [multiOnly, setMultiOnly] = useState(false);
  const [statusF, setStatusF] = useState<StatusF>("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("ai");
  const [sel, setSel] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    setLoading(true);
    const days = range === "all" || range === "1" ? undefined : Number(range);
    api.jobs({ days, date: range === "1" ? today() : undefined, limit: 2000, status: statusF === "dismissed" || statusF === "filtered" ? statusF : undefined })
      .then((r) => setAll(r.jobs))
      .catch((e) => { toast((e as Error).message); setAll((x) => x ?? []); })
      .finally(() => setLoading(false));
  }, [range, statusF, toast]);
  // 新岗位进来（总数变化）时自动刷新，保留当前选中
  const total = overview?.stats.total;
  useEffect(load, [load, total]);

  const mRegion = (j: Job) => regions.size === 0 || (regions.has("domestic") && j.region === "domestic")
    || (regions.has("overseas") && j.region === "overseas") || (regions.has("remote") && j.remote);
  const mType = (j: Job) => types.size === 0 || types.has(j.job_type || "unknown");
  const mPlat = (j: Job) => plats.size === 0 || plats.has(facetPlatform(j));
  const mVerdict = (j: Job) => statusF === 'filtered' || verdicts.has(j.verdict || "");
  const mStatus = (j: Job) => statusF === "all" || statusF === "dismissed" || j.status === statusF;
  const mMulti = (j: Job) => !multiOnly || platformsOf(j).length > 1;
  const mQ = (j: Job) => {
    if (!q.trim()) return true;
    const t = `${j.title} ${j.title_zh || ""} ${j.company} ${j.city} ${j.description} ${j.tags.join(" ")}`.toLowerCase();
    return q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => t.includes(w));
  };

  const facets = useMemo(() => {
    const base = (all ?? []).filter((j) => mStatus(j) && mQ(j) && mMulti(j));
    const count = <K extends string>(keys: K[], pick: (j: Job) => K[], list: Job[]) => {
      const m = Object.fromEntries(keys.map((k) => [k, 0])) as Record<K, number>;
      for (const j of list) for (const k of pick(j)) if (k in m) m[k]++;
      return m;
    };
    const platCounts = new Map<string, { n: number; overseas: boolean }>();
    for (const j of base.filter((j) => mRegion(j) && mType(j) && mVerdict(j))) {
      const p = facetPlatform(j); const o = platCounts.get(p) ?? { n: 0, overseas: true };
      platCounts.set(p, { n: o.n + 1, overseas: o.overseas && j.region === "overseas" });
    }
    return {
      verdicts: count(["recommend", "maybe", "", "no"], (j) => [j.verdict || ""], base.filter((j) => mRegion(j) && mType(j) && mPlat(j))),
      regions: count(["domestic", "overseas", "remote"], (j) => [j.region, ...(j.remote ? ["remote"] : [])], base.filter((j) => mType(j) && mPlat(j) && mVerdict(j))),
      types: count(["parttime", "contract", "fulltime", "intern", "unknown"], (j) => [j.job_type || "unknown"], base.filter((j) => mRegion(j) && mPlat(j) && mVerdict(j))),
      plats: [...platCounts.entries()].map(([p, v]) => ({ p, ...v })).sort((a, b) => Number(a.overseas) - Number(b.overseas) || b.n - a.n),
    };
  }, [all, regions, types, plats, verdicts, statusF, q, multiOnly]); // eslint-disable-line react-hooks/exhaustive-deps

  const list = useMemo(() => {
    const l = (all ?? []).filter((j) => mRegion(j) && mType(j) && mPlat(j) && mVerdict(j) && mStatus(j) && mMulti(j) && mQ(j));
    const by: Record<Sort, (a: Job, b: Job) => number> = {
      ai: (a, b) => verdictOf(a).rank - verdictOf(b).rank || (b.score ?? -1) - (a.score ?? -1) || b.first_seen.localeCompare(a.first_seen),
      published: (a, b) => (b.published_at || "").slice(0, 10).localeCompare((a.published_at || "").slice(0, 10)) || (b.score ?? -1) - (a.score ?? -1),
      new: (a, b) => b.first_seen.localeCompare(a.first_seen),
      salary: (a, b) => (b.salary_min_k ?? -1) - (a.salary_min_k ?? -1),
    };
    return l.sort(by[sort]);
  }, [all, regions, types, plats, verdicts, statusF, q, multiOnly, sort]); // eslint-disable-line react-hooks/exhaustive-deps

  const hiddenNo = (all ?? []).filter((j) => j.verdict === "no").length;
  const merged = list.reduce((n, j) => n + j.also.length, 0);
  const cur = list.find((j) => j.id === sel) ?? null;

  // 列表变化后，选中项不在列表里了就选第一条
  useEffect(() => {
    if (list.length && !list.some((j) => j.id === sel)) setSel(list[0].id);
    if (!list.length) setSel(null);
  }, [list, sel]);

  const patchLocal = (id: string, status: JobStatus) => setAll((a) => (a ?? []).map((x) => (x.id === id ? { ...x, status } : x)));
  const setStatus = async (j: Job, s: JobStatus, quiet = false) => {
    const prev = j.status;
    patchLocal(j.id, s);   // 先改界面，再发请求
    try {
      await api.setStatus(j.id, s);
      if (!quiet) toast(s === "starred" ? "已收藏" : s === "applied" ? "已标记为已投" : s === "dismissed" ? "已标为不合适，可在状态「不合适」里找回" : "已取消");
    } catch (e) { patchLocal(j.id, prev); toast((e as Error).message); }
  };
  const toggleStatus = (j: Job, s: JobStatus) => setStatus(j, j.status === s ? "seen" : s);

  // 选中一条未读的，标记为已看（列表里的蓝点消失）
  useEffect(() => {
    if (cur && cur.status === "new" && statusF !== "new") setStatus(cur, "seen", true);
  }, [cur?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // 键盘：↑↓ / j k 切换，Enter 用专用浏览器打开，s 收藏
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select")) return;
      const i = list.findIndex((j) => j.id === sel);
      if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); const n = list[Math.min(i + 1, list.length - 1)]; if (n) setSel(n.id); }
      else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); const n = list[Math.max(i - 1, 0)]; if (n) setSel(n.id); }
      else if (e.key === "Enter" && cur) openJob(cur.url, toast);
      else if (e.key === "s" && cur) toggleStatus(cur, "starred");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [list, sel, cur]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-id="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  const exportHtml = async () => {
    const days = range === "all" ? 3650 : range === "1" ? 1 : Number(range);
    try {
      const r = await api.exportHtml(days);
      toast(`已导出 ${r.count} 条：${r.name}`);
      window.desktop?.showItem(r.path);
    } catch (e) { toast((e as Error).message); }
  };

  const anyFilter = regions.size + types.size + plats.size > 0 || multiOnly || q || statusF !== "all"
    || verdicts.size !== 3 || verdicts.has("no");
  const clear = () => { setRegions(new Set()); setTypes(new Set()); setPlats(new Set()); setMultiOnly(false); setQ(""); setStatusF("all"); setVerdicts(new Set(DEFAULT_VERDICTS)); };

  return (
    <div className="jobs">
      <header className="jobs-head">
        <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
          <h1>岗位</h1>
          <span className="muted" style={{ fontSize: 13 }}>
            {list.length} 条{merged > 0 && ` · 已合并 ${merged} 条重复`}
            {hiddenNo > 0 && !verdicts.has("no") && <> · <button className="link-btn" onClick={() => setVerdicts(toggle(verdicts, "no"))}>另有 {hiddenNo} 条 AI 判为不合适</button></>}
          </span>
          {loading && all !== null && <Loader2 size={14} className="spin faint" />}
          <span className="grow" />
          <Seg<Range> label="时间范围" value={range} onChange={setRange} options={[
            { value: "1", label: "今天" }, { value: "3", label: "3 天" }, { value: "7", label: "7 天" }, { value: "30", label: "30 天" }, { value: "all", label: "全部" }]} />
          <button className="btn icon" title="刷新" aria-label="刷新" onClick={load}>{loading ? <Loader2 className="spin" /> : <RefreshCw />}</button>
          <AsyncButton icon={<Download />} onClick={exportHtml} title="导出成一个 HTML 文件，可以发到手机上看">导出</AsyncButton>
        </div>
        <div className="jobs-filters">
          <div className="search"><Search />
            <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜岗位、公司、技能" aria-label="搜索" />
          </div>
          {(["recommend", "maybe", "", "no"] as const).map((v) => (
            <button key={v} className={`chip v-${v || "none"}`} aria-pressed={verdicts.has(v)} onClick={() => setVerdicts(toggle(verdicts, v))}>
              {VERDICT[v].label}<span className="n">{facets.verdicts[v]}</span>
            </button>
          ))}
          <span className="sep-v" />
          {([["remote", "远程"], ["domestic", "国内"], ["overseas", "海外"]] as const).map(([k, l]) => (
            <button key={k} className="chip" aria-pressed={regions.has(k)} onClick={() => setRegions(toggle(regions, k))}>{l}<span className="n">{facets.regions[k]}</span></button>
          ))}
          <span className="sep-v" />
          {(["parttime", "contract", "fulltime", "unknown"] as const).filter((t) => facets.types[t] > 0 || types.has(t)).map((t) => (
            <button key={t} className="chip" aria-pressed={types.has(t)} onClick={() => setTypes(toggle(types, t))}>
              {JOB_TYPE_LABEL[t] || "未注明"}<span className="n">{facets.types[t]}</span>
            </button>
          ))}
          <span className="sep-v" />
          <PlatformPicker plats={facets.plats} value={plats} onChange={setPlats} />
          <button className="chip" aria-pressed={multiOnly} onClick={() => setMultiOnly(!multiOnly)} title="同一个岗位在两个以上平台都出现过">多平台都有</button>
          <span className="grow" />
          <select className="select" style={{ width: "auto" }} value={statusF} onChange={(e) => setStatusF(e.target.value as StatusF)} aria-label="状态">
            <option value="all">全部状态</option><option value="new">未读</option><option value="starred">收藏</option>
            <option value="applied">已投</option><option value="dismissed">标为不合适的</option><option value="filtered">已过滤（检查原因）</option>
          </select>
          <select className="select" style={{ width: "auto" }} value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="排序">
            <option value="ai">AI 推荐优先</option><option value="published">最新发布</option><option value="new">最新发现</option><option value="salary">薪资</option>
          </select>
        </div>
      </header>

      <div className="jobs-body">
        <div className="jobs-list" ref={listRef} role="listbox" aria-label="岗位列表">
          {all === null ? <div className="empty"><Loader2 className="spin" /></div> :
            list.length === 0 ? (
              <div className="empty"><Inbox /><b>{all.length ? "没有符合筛选的岗位" : "这段时间还没有岗位"}</b>
                {anyFilter && <button className="btn sm" onClick={clear}>清除筛选</button>}</div>
            ) : list.map((j) => {
              const v = verdictOf(j); const pub = publishedAgo(j.published_at);
              return (
                <button key={j.id} data-id={j.id} role="option" aria-selected={j.id === sel}
                  className={`jrow ${j.id === sel ? "on" : ""} ${j.status === "new" ? "unread" : ""} ${j.verdict === "no" || j.status === "dismissed" ? "dim" : ""}`}
                  onClick={() => setSel(j.id)} onDoubleClick={() => openJob(j.url, toast)}>
                  <span className="jrow-top">
                    <i className={`vdot ${v.cls}`} title={v.label} />
                    <span className="jrow-title ellipsis">{j.title_zh || j.title}</span>
                    {j.status === "starred" && <Star size={13} className="star" fill="currentColor" />}
                    {j.status === "applied" && <Check size={13} className="applied" />}
                    <span className="jrow-sal">{j.salary}</span>
                  </span>
                  <span className="jrow-meta ellipsis">
                    {[j.company, j.remote ? "远程" : j.city, JOB_TYPE_LABEL[j.job_type]].filter(Boolean).join(" · ") || "—"}
                  </span>
                  <span className="jrow-foot">
                    <span>{platformOf(j)}</span>
                    {platformsOf(j).length > 1 && <span className="badge blue">{platformsOf(j).length} 个平台</span>}
                    {j.region === "overseas" && <span className="badge blue">海外</span>}
                    <span className="grow" />
                    <span className={pub && pub.days > 30 ? "old" : ""}>{pub ? `${pub.text}发布` : `发现于${timeAgo(j.first_seen)}`}</span>
                  </span>
                </button>
              );
            })}
        </div>
        <Detail j={cur} toast={toast} onStatus={toggleStatus} />
      </div>
    </div>
  );
}

function PlatformPicker({ plats, value, onChange }: {
  plats: { p: string; n: number; overseas: boolean }[]; value: Set<string>; onChange: (v: Set<string>) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const label = value.size === 0 ? "全部平台" : value.size === 1 ? [...value][0] : `${value.size} 个平台`;
  return (
    <div className="picker" ref={ref}>
      <button className="chip" aria-pressed={value.size > 0} aria-expanded={open} onClick={() => setOpen(!open)}>
        {label}<ChevronDown size={14} />
      </button>
      {open && (
        <div className="picker-pop" role="dialog" aria-label="选择平台">
          <div className="row" style={{ justifyContent: "space-between", padding: "4px 8px 8px" }}>
            <span className="faint" style={{ fontSize: 12 }}>按平台筛选</span>
            {value.size > 0 && <button className="link-btn" onClick={() => onChange(new Set())}>清除</button>}
          </div>
          {plats.map(({ p, n, overseas }) => (
            <label key={p} className="picker-item">
              <input type="checkbox" checked={value.has(p)} onChange={() => onChange(toggle(value, p))} />
              <span className="grow">{p}</span>
              {overseas && <span className="badge blue">海外</span>}
              <span className="faint">{n}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function Detail({ j, toast, onStatus }: { j: Job | null; toast: (m: string) => void; onStatus: (j: Job, s: JobStatus) => void }) {
  if (!j) return <div className="jobs-detail"><div className="empty"><Inbox /><b>选一条岗位查看详情</b><span>↑ ↓ 切换，Enter 用专用浏览器打开</span></div></div>;
  const v = verdictOf(j);
  const pub = publishedAgo(j.published_at);
  const incomplete = !j.published_at || (j.description || "").length < 180;
  const facts: [string, string][] = [
    ["公司", j.company], ["地点", j.remote ? (j.city && j.city !== "远程" ? `${j.city}（可远程）` : "远程") : j.city],
    ["薪资", j.salary], ["类型", JOB_TYPE_LABEL[j.job_type] || ""], ["经验", j.experience], ["学历", j.education],
    ["发布", j.published_at ? `${j.published_at.slice(0, 10)}（${pub?.text}）` : "未知"],
    ["发现", `${j.first_seen.replace("T", " ").slice(0, 16)}`],
  ];
  return (
    <article className="jobs-detail">
      <div className="d-head">
        <div className="row" style={{ gap: 8, alignItems: "flex-start" }}>
          <h2 className="d-title grow">{j.title_zh || j.title}</h2>
          {j.verdict && <span className={`badge ${v.cls}`} style={{ marginTop: 4 }}>{v.label}</span>}
        </div>
        {j.title_zh && <div className="faint" style={{ fontSize: 13 }}>{j.title}</div>}
        <div className="d-actions">
          <button className="btn primary" onClick={() => openJob(j.url, toast)} title="带着登录状态打开，详情看得全（Enter）">
            <ExternalLink />打开原页面</button>
          <button className="btn" onClick={() => openExternal(j.url)} title="用系统默认浏览器打开"><Globe />系统浏览器</button>
          <span className="grow" />
          <button className={`btn icon ${j.status === "starred" ? "is-on star" : ""}`} title="收藏（S）" aria-pressed={j.status === "starred"} onClick={() => onStatus(j, "starred")}>
            <Star fill={j.status === "starred" ? "currentColor" : "none"} /></button>
          <button className={`btn icon ${j.status === "applied" ? "is-on applied" : ""}`} title="标记已投" aria-pressed={j.status === "applied"} onClick={() => onStatus(j, "applied")}>
            <Check /></button>
          <button className={`btn icon ${j.status === "dismissed" ? "is-on" : ""}`} title="不合适，隐藏" aria-pressed={j.status === "dismissed"} onClick={() => onStatus(j, "dismissed")}>
            <Ban /></button>
        </div>
      </div>

      <div className="d-scroll">
        {incomplete && <div className="quality-note">待核验：{!j.published_at ? "发布时间未知。" : ""}{(j.description || "").length < 180 ? "正文尚不完整。" : ""}请核实原页面后再决定是否投递。</div>}
        {(j.verdict_reason || j.ai_summary) && (
          <section className={`d-ai ${v.cls}`}>
            <b><Sparkles size={14} />{j.verdict === "no" ? "AI 判为不合适" : j.verdict ? `AI：${v.label}` : "AI"}{j.score != null && <span className="faint">　匹配 {j.score}</span>}</b>
            {j.verdict_reason && <p>{j.verdict_reason}</p>}
            {j.ai_summary && <p className="muted">{j.ai_summary}</p>}
          </section>
        )}
        <dl className="d-facts">
          {facts.filter(([, val]) => val).map(([k, val]) => (<div key={k}><dt>{k}</dt><dd>{val}</dd></div>))}
        </dl>
        <section className="d-src">
          <span className="faint">信源</span>
          <button className="link-btn" onClick={() => openJob(j.url, toast)}>{platformOf(j)}</button>
          {j.also.map((a) => (
            <button key={a.id} className="link-btn" onClick={() => openJob(a.url, toast)} title={a.url}>{platformOf(a)}</button>
          ))}
          {j.also.length > 0 && <span className="faint">（同一岗位在 {platformsOf(j).length} 个平台出现）</span>}
        </section>
        {j.tags.length > 0 && <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>{j.tags.map((t) => <span key={t} className="badge">{t}</span>)}</div>}
        {j.description && (
          <section>
            <h3 className="d-h3">原文</h3>
            <div className="d-desc">{j.description}</div>
            <p className="faint" style={{ fontSize: 12, marginTop: 8 }}>
              这里保留已采集的正文；部分平台仅提供列表摘要，可打开原页面核实。最后看到这个岗位：{localDate(new Date(j.last_seen))}
            </p>
          </section>
        )}
      </div>
    </article>
  );
}
