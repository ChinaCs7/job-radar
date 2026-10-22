import { useEffect, useMemo, useState } from "react";
import { Download, ExternalLink, Inbox, Loader2, RefreshCw, Search, Sparkles } from "lucide-react";
import { api, type Job, type JobStatus } from "../lib/api";
import { dayLabel, facetPlatform, JOB_TYPE_LABEL, localDate, platformOf, platformsOf, publishedAgo, timeAgo, today, VERDICT, verdictOf } from "../lib/format";
import { useTheme } from "../lib/theme";
import { AsyncButton, JobActions, Score, Seg, ThemeToggle, useToast } from "../components/ui";

// 导出的单文件 H5 把数据嵌在 window.__SNAPSHOT__ 里：这时不请求接口，也不显示需要接口的操作
const SNAP = window.__SNAPSHOT__;

type Range = "1" | "2" | "3" | "7" | "30" | "all";
type StatusF = "all" | "new" | "starred" | "applied" | "dismissed";
type RegionKey = "domestic" | "overseas" | "remote";
type Sort = "ai" | "new" | "published" | "salary";

const PAGE = 60;

function toggle<T>(set: Set<T>, v: T): Set<T> {
  const n = new Set(set);
  if (n.has(v)) n.delete(v); else n.add(v);
  return n;
}

export default function Report() {
  const [theme, setTheme] = useTheme();
  const [toastNode, toast] = useToast();
  const [all, setAll] = useState<Job[] | null>(SNAP ? SNAP.jobs : null);
  const [error, setError] = useState("");
  const [range, setRange] = useState<Range>(SNAP ? "all" : "7");
  const [regions, setRegions] = useState<Set<RegionKey>>(new Set());
  const [plats, setPlats] = useState<Set<string>>(new Set());
  const [types, setTypes] = useState<Set<string>>(new Set());
  // AI 判断：默认不看「不合适」
  const [verdicts, setVerdicts] = useState<Set<string>>(new Set(["recommend", "maybe", ""]));
  const [statusF, setStatusF] = useState<StatusF>("all");
  const [q, setQ] = useState("");
  const [multiOnly, setMultiOnly] = useState(false);
  const [sort, setSort] = useState<Sort>("ai");
  const [shown, setShown] = useState(PAGE);
  const [summaries, setSummaries] = useState<Record<string, string>>({});
  const [busySum, setBusySum] = useState("");
  const [loading, setLoading] = useState(false);

  // 时间范围在服务端筛（数据量最大的维度），其余维度在页面里筛，这样每个筛选项都能显示数量
  const load = () => {
    if (SNAP) return;
    setLoading(true);
    const days = range === "all" || range === "1" || range === "2" ? undefined : Number(range);
    const date = range === "1" ? today() : range === "2" ? localDate(new Date(Date.now() - 864e5)) : undefined;
    api.jobs({ days, date, limit: 2000, status: statusF === "dismissed" ? "dismissed" : undefined })
      .then((r) => { setAll(r.jobs); setError(""); })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  };
  useEffect(load, [range, statusF === "dismissed"]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setShown(PAGE), [range, regions, plats, types, verdicts, statusF, q, sort, multiOnly]);

  const matchRegion = (j: Job) => regions.size === 0 ||
    (regions.has("domestic") && j.region === "domestic") || (regions.has("overseas") && j.region === "overseas") ||
    (regions.has("remote") && j.remote);
  const matchPlat = (j: Job) => plats.size === 0 || plats.has(facetPlatform(j));
  const matchType = (j: Job) => types.size === 0 || types.has(j.job_type || "unknown");
  const matchVerdict = (j: Job) => verdicts.has(j.verdict || "");
  const matchStatus = (j: Job) => statusF === "all" || statusF === "dismissed" || (statusF === "new" ? j.status === "new" : j.status === statusF);
  const matchMulti = (j: Job) => !multiOnly || platformsOf(j).length > 1;
  const matchQ = (j: Job) => {
    if (!q.trim()) return true;
    const t = `${j.title} ${j.company} ${j.city} ${j.description} ${j.tags.join(" ")}`.toLowerCase();
    return q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => t.includes(w));
  };

  // 每个维度的计数，按「其他维度都已生效」来算，所以点了一个平台以后，地区的数字会跟着变
  const facets = useMemo(() => {
    const base = (all ?? []).filter((j) => matchVerdict(j) && matchStatus(j) && matchQ(j) && matchMulti(j));
    const count = (pred: (j: Job) => boolean, list: Job[]) => list.filter(pred).length;
    const forPlat = base.filter((j) => matchRegion(j) && matchType(j));
    const platCounts = new Map<string, number>();
    const domesticPlat = new Set<string>();
    for (const j of forPlat) {
      const fp = facetPlatform(j);
      platCounts.set(fp, (platCounts.get(fp) ?? 0) + 1);
      if (j.region === "domestic" || fp === "其他网站") domesticPlat.add(fp);
    }
    const forRegion = base.filter((j) => matchPlat(j) && matchType(j));
    const forType = base.filter((j) => matchRegion(j) && matchPlat(j));
    const typeCounts = new Map<string, number>();
    for (const j of forType) typeCounts.set(j.job_type || "unknown", (typeCounts.get(j.job_type || "unknown") ?? 0) + 1);
    return {
      // 海外平台排在后面，并标上「海外」
      plats: [...platCounts.entries()].map(([p, n]) => ({ p, n, overseas: !domesticPlat.has(p) }))
        .sort((a, b) => Number(a.overseas) - Number(b.overseas) || Number(a.p === "其他网站") - Number(b.p === "其他网站") || b.n - a.n),
      multi: base.filter((j) => matchRegion(j) && matchPlat(j) && matchType(j) && platformsOf(j).length > 1).length,
      regions: {
        domestic: count((j) => j.region === "domestic", forRegion),
        overseas: count((j) => j.region === "overseas", forRegion),
        remote: count((j) => j.remote, forRegion),
      },
      types: [...typeCounts.entries()].sort((a, b) => b[1] - a[1]),
      verdicts: Object.fromEntries(["recommend", "maybe", "", "no"].map((v) => [v,
        (all ?? []).filter((j) => (j.verdict || "") === v && matchStatus(j) && matchQ(j) && matchMulti(j) && matchRegion(j) && matchPlat(j) && matchType(j)).length])) as Record<string, number>,
    };
  }, [all, regions, plats, types, verdicts, statusF, q, multiOnly]); // eslint-disable-line react-hooks/exhaustive-deps

  const list = useMemo(() => {
    const l = (all ?? []).filter((j) => matchRegion(j) && matchPlat(j) && matchType(j) && matchVerdict(j) && matchStatus(j) && matchQ(j) && matchMulti(j));
    const by: Record<Sort, (a: Job, b: Job) => number> = {
      // 同一小时内发现的算同一批，批内按匹配分排，回来看新岗位时高匹配的在前面
      ai: (a, b) => verdictOf(a).rank - verdictOf(b).rank || (b.score ?? -1) - (a.score ?? -1) || b.first_seen.localeCompare(a.first_seen),
      published: (a, b) => (b.published_at || "").slice(0, 10).localeCompare((a.published_at || "").slice(0, 10)) || (b.score ?? -1) - (a.score ?? -1),
      new: (a, b) => b.first_seen.slice(0, 13).localeCompare(a.first_seen.slice(0, 13)) || (b.score ?? -1) - (a.score ?? -1)
        || b.first_seen.localeCompare(a.first_seen),
      salary: (a, b) => (b.salary_min_k ?? -1) - (a.salary_min_k ?? -1),
    };
    return l.sort(by[sort]);
  }, [all, regions, plats, types, verdicts, statusF, q, sort, multiOnly]); // eslint-disable-line react-hooks/exhaustive-deps

  // 按「首次发现」的日期分组；按匹配分或薪资排序时，组内顺序也跟着排序
  const groups = useMemo(() => {
    const m = new Map<string, Job[]>();
    for (const j of list.slice(0, shown)) {
      const d = j.first_seen.slice(0, 10);
      if (!m.has(d)) m.set(d, []);
      m.get(d)!.push(j);
    }
    return [...m.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [list, shown]);
  const dayTotals = useMemo(() => {
    const m = new Map<string, number>();
    for (const j of list) m.set(j.first_seen.slice(0, 10), (m.get(j.first_seen.slice(0, 10)) ?? 0) + 1);
    return m;
  }, [list]);

  useEffect(() => {
    if (SNAP) return;
    for (const [d] of groups) {
      if (d in summaries) continue;
      setSummaries((s) => ({ ...s, [d]: "" }));
      api.summary(d).then((r) => r.text && setSummaries((s) => ({ ...s, [d]: r.text! }))).catch(() => { });
    }
  }, [groups]); // eslint-disable-line react-hooks/exhaustive-deps

  const makeSummary = async (d: string) => {
    setBusySum(d);
    try { const r = await api.makeSummary(d); setSummaries((s) => ({ ...s, [d]: r.text })); }
    catch (e) { toast((e as Error).message); }
    finally { setBusySum(""); }
  };

  const setStatus = async (j: Job, s: JobStatus) => {
    const prev = j.status;
    // 先改界面再发请求，失败再还原
    setAll((a) => (a ?? []).map((x) => (x.id === j.id ? { ...x, status: s } : x)));
    try { await api.setStatus(j.id, s); toast(s === "starred" ? "已收藏" : s === "applied" ? "已标记为已投" : s === "dismissed" ? "已标为不合适" : "已取消"); }
    catch (e) { setAll((a) => (a ?? []).map((x) => (x.id === j.id ? { ...x, status: prev } : x))); toast((e as Error).message); }
  };

  const exportHtml = async () => {
    try {
      const days = range === "all" ? 3650 : range === "1" || range === "2" ? 2 : Number(range);
      const r = await api.exportHtml(days);
      toast(`已导出 ${r.count} 条到 ${r.path}`);
    } catch (e) { toast((e as Error).message); }
  };

  const merged = useMemo(() => list.reduce((n, j) => n + j.also.length, 0), [list]);
  const anyFilter = regions.size + plats.size + types.size > 0 || verdicts.size !== 3 || verdicts.has("no") || statusF !== "all" || q || multiOnly;
  const clear = () => { setRegions(new Set()); setPlats(new Set()); setTypes(new Set()); setVerdicts(new Set(["recommend", "maybe", ""])); setStatusF("all"); setQ(""); setMultiOnly(false); };

  return (
    <>
      <header className="r-top">
        <div className="r-bar">
          <img src={SNAP ? undefined : "/icon.svg"} alt="" hidden={!!SNAP} />
          <h1>检索结果</h1>
          <span className="meta">{SNAP ? `快照 · 导出于 ${SNAP.at.replace("T", " ").slice(0, 16)}` : "本机实时数据"}</span>
          <span className="grow" />
          {!SNAP && <button className="btn ghost sm" onClick={load} title="刷新" aria-label="刷新">{loading ? <Loader2 className="spin" /> : <RefreshCw />}<span className="t-label">刷新</span></button>}
          {!SNAP && <AsyncButton className="btn ghost sm hide-s" icon={<Download />} onClick={exportHtml} title="导出成一个 HTML 文件，可以发到手机上看">导出</AsyncButton>}
          <ThemeToggle theme={theme} setTheme={setTheme} />
        </div>
      </header>

      <main className="r-wrap">
        <section className="filters" aria-label="筛选">
          {!SNAP && (
            <div className="f-row scroll-s">
              <span className="lab">时间</span>
              <Seg<Range> label="时间范围" value={range} onChange={setRange} options={[
                { value: "1", label: "今天" }, { value: "2", label: "昨天" }, { value: "3", label: "近 3 天" },
                { value: "7", label: "近 7 天" }, { value: "30", label: "近 30 天" }, { value: "all", label: "全部" },
              ]} />
            </div>
          )}
          <div className="f-row">
            <span className="lab">地区</span>
            {([["domestic", "国内"], ["overseas", "海外"], ["remote", "远程"]] as const).map(([k, l]) => (
              <button key={k} className="chip" aria-pressed={regions.has(k)} onClick={() => setRegions(toggle(regions, k))}>
                {l}<span className="n">{facets.regions[k]}</span>
              </button>
            ))}
          </div>
          <div className="f-row">
            <span className="lab">平台</span>
            <button className="chip" aria-pressed={multiOnly} onClick={() => setMultiOnly(!multiOnly)}
              title="同一个岗位在两个以上平台都出现过">多平台都有<span className="n">{facets.multi}</span></button>
            {facets.plats.map(({ p, n, overseas }) => (
              <button key={p} className="chip" aria-pressed={plats.has(p)} onClick={() => setPlats(toggle(plats, p))}>
                {p}{overseas && <span className="n">海外</span>}<span className="n">{n}</span>
              </button>
            ))}
            {facets.plats.length === 0 && <span className="faint" style={{ fontSize: 13 }}>—</span>}
          </div>
          <div className="f-row">
            <span className="lab">类型</span>
            {facets.types.map(([t, n]) => (
              <button key={t} className="chip" aria-pressed={types.has(t)} onClick={() => setTypes(toggle(types, t))}>
                {JOB_TYPE_LABEL[t] || "未注明"}<span className="n">{n}</span>
              </button>
            ))}
          </div>
          <div className="f-row">
            <span className="lab" title="AI 按你的条件给每条岗位下的结论">AI</span>
            {(["recommend", "maybe", "", "no"] as const).map((v) => (
              <button key={v} className="chip" aria-pressed={verdicts.has(v)} onClick={() => setVerdicts(toggle(verdicts, v))}>
                {VERDICT[v].label}<span className="n">{facets.verdicts[v]}</span>
              </button>
            ))}
          </div>
          <div className="f-row scroll-s">
            <span className="lab">状态</span>
            <Seg<StatusF> label="状态" value={statusF} onChange={setStatusF} options={[
              { value: "all", label: "全部" }, { value: "new", label: "未处理" }, { value: "starred", label: "收藏" },
              { value: "applied", label: "已投" }, ...(SNAP ? [] : [{ value: "dismissed" as StatusF, label: "不合适" }])]} />
          </div>
          <div className="f-row wrap-s">
            <div className="search"><Search />
              <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜岗位、公司、城市、技能" aria-label="搜索" />
            </div>
            <select className="select" value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="排序">
              <option value="ai">AI 推荐优先</option><option value="published">最新发布</option><option value="new">最新发现</option><option value="salary">薪资</option>
            </select>
          </div>
        </section>

        <div className="r-count">
          <span>共 {list.length} 条{merged > 0 && <span className="faint" title="同一岗位在多个平台或多次发布时合并成一条，其他链接放在「另见」里"> · 已合并 {merged} 条重复</span>}</span>
          {anyFilter && <button className="btn ghost sm" onClick={clear}>清除筛选</button>}
        </div>

        {error ? <div className="notice danger">{error}</div> :
          all === null ? <div className="empty"><Loader2 className="spin" /></div> :
            list.length === 0 ? (
              <div className="empty"><Inbox /><b>{all.length ? "没有符合筛选的岗位" : "这段时间还没有收集到岗位"}</b>
                {anyFilter && <button className="btn" onClick={clear}>清除筛选</button>}</div>
            ) : groups.map(([d, jobs]) => (
              <section className="day" key={d}>
                <div className="day-head">
                  <h2>{dayLabel(d)}</h2><span className="n">{dayTotals.get(d)} 条</span>
                  <span className="grow" />
                  {!SNAP && !summaries[d] && (
                    <button className="btn ghost sm" onClick={() => makeSummary(d)} disabled={busySum === d}>
                      {busySum === d ? <Loader2 className="spin" /> : <Sparkles />}AI 总结这一天
                    </button>
                  )}
                </div>
                {summaries[d] && <div className="summary"><b><Sparkles size={14} />AI 总结</b>{summaries[d]}</div>}
                <div className="list">
                  {jobs.map((j) => <Item key={j.id} j={j} onStatus={SNAP ? undefined : (s) => setStatus(j, s)} />)}
                </div>
              </section>
            ))}

        {list.length > shown && <button className="btn more-btn" onClick={() => setShown(shown + PAGE)}>再显示 {Math.min(PAGE, list.length - shown)} 条</button>}
        <p className="r-foot">每条岗位都链接到原始页面；信息以原页面为准。</p>
      </main>
      {toastNode}
    </>
  );
}

function Item({ j, onStatus }: { j: Job; onStatus?: (s: JobStatus) => void }) {
  const meta = [j.company, j.remote ? (j.city && j.city !== "远程" ? `${j.city}（可远程）` : "远程") : j.city,
    j.experience, j.education, JOB_TYPE_LABEL[j.job_type]].filter(Boolean);
  const blurb = j.ai_summary || j.description;
  const v = verdictOf(j);
  const pub = publishedAgo(j.published_at);
  return (
    <article className={`item ${j.status === "dismissed" || j.verdict === "no" ? "dim" : ""}`}>
      <Score value={j.score} />
      <span className="t-wrap">
        <a className="t" href={j.url} target="_blank" rel="noopener noreferrer">{j.title_zh || j.title}</a>
        {j.verdict ? <span className={`badge ${v.cls}`}>{v.label}</span> : null}
        {platformsOf(j).length > 1 && (
          <span className="badge blue" title={`这些平台都有：${platformsOf(j).join("、")}`}>{platformsOf(j).length} 个平台都有</span>
        )}
      </span>
      <span className={`sal ${j.salary ? "" : "none"}`}>{j.salary || "薪资未写"}</span>
      {j.title_zh && <div className="orig" title="原文标题">{j.title}</div>}
      {meta.length > 0 && <div className="l2">{meta.map((m, i) => <span key={i}>{m}</span>)}</div>}
      {blurb && <div className="l3">{blurb}</div>}
      {j.verdict_reason && <div className={`why ${v.cls}`}>{j.verdict === "no" ? "不合适：" : "AI："}{j.verdict_reason}</div>}
      <div className="l4">
        <span className="src">
          <a href={j.url} target="_blank" rel="noopener noreferrer" title={j.url}>{platformOf(j)}</a>
          <ExternalLink size={12} />
        </span>
        {j.also.length > 0 && <>
          <span>另见</span>
          {j.also.map((a) => <a key={a.id} href={a.url} target="_blank" rel="noopener noreferrer">{platformOf(a)}</a>)}
        </>}
        <span className="sep" />
        <span className={`pub ${pub && pub.days > 30 ? "old" : ""}`} title={j.published_at ? `发布于 ${j.published_at.slice(0, 10)}` : "发布时间未知"}>
          {pub ? `${pub.text}发布` : "发布时间未知"}
        </span>
        <span title={j.first_seen.replace("T", " ")}>· 发现 {timeAgo(j.first_seen)}</span>
        {j.region === "overseas" && <span className="badge blue">海外</span>}
        {j.tags.slice(0, 4).map((t) => <span className="badge" key={t}>{t}</span>)}
        {j.status === "applied" && <span className="badge ok">已投</span>}
        {onStatus && <span className="acts"><JobActions job={j} onChange={onStatus} /></span>}
      </div>
    </article>
  );
}
