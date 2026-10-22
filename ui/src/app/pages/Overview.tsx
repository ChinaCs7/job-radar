import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, BriefcaseBusiness, Inbox, Info, Loader2, PauseCircle, RefreshCw } from "lucide-react";
import { api, type Job, type JobStatus } from "../../lib/api";
import { openJob } from "./Jobs";
import { platformOf, platformsOf, publishedAgo, timeAgo, today, untilLabel, verdictOf } from "../../lib/format";
import { JobActions, Score, Seg, STATE_META } from "../../components/ui";
import type { PageProps } from "../App";

type Tab = "today" | "high" | "starred";

export default function Overview({ overview, refresh, go, toast }: PageProps) {
  const [tab, setTab] = useState<Tab>("today");
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [kicking, setKicking] = useState(false);
  const total = overview?.stats.today ?? 0;
  const activeCount = (overview?.activity.running.length ?? 0) + (overview?.activity.queued.length ?? 0);

  // 总览每 5 秒刷新一次；岗位表跟着「今天新增数」变化重新拉，避免无谓请求
  useEffect(() => {
    const p = tab === "today" ? { date: today(), sort: "score", limit: 80 }
      : tab === "high" ? { days: 7, sort: "score", limit: 200 }
        : { status: "starred", sort: "new", limit: 50 };
    // 刷新时保留旧列表，只在标题旁转个小圈，不整块闪成加载中
    setLoadingJobs(true);
    // 「今天新增」不显示 AI 判为不合适的；「AI 推荐」只显示推荐的
    api.jobs(p).then((r) => setJobs(r.jobs.filter((j) => tab === "high" ? j.verdict === "recommend" : tab === "today" ? j.verdict !== "no" : true).slice(0, 50))).catch(() => setJobs((x) => x ?? [])).finally(() => setLoadingJobs(false));
  }, [tab, total]);

  const runNow = async () => {
    setKicking(true);
    try {
      const r = await api.runNow();
      const n = r.started.length;
      const browserN = r.started.filter((id) => overview?.sources.find((s) => s.id === id)?.browser).length;
      toast(n ? `已开始检索 ${n} 个信源${browserN ? `，其中 ${browserN} 个用浏览器排队进行，约 ${Math.max(1, Math.round(browserN * 1.1))} 分钟` : ""}`
        : "没有可以检索的信源（都在跑、已暂停，或今天到了次数上限）");
      refresh();
    } catch (e) { toast((e as Error).message); }
    finally { setKicking(false); }
  };

  const setStatus = async (j: Job, s: JobStatus) => {
    const before = jobs;
    // 先改界面再发请求：点了立刻有反应；失败再还原
    setJobs((list) => (list ?? []).map((x) => (x.id === j.id ? { ...x, status: s } : x))
      .filter((x) => x.status !== "dismissed" && (tab !== "starred" || x.status === "starred")));
    try { await api.setStatus(j.id, s); toast(s === "starred" ? "已收藏" : s === "applied" ? "已标记为已投" : s === "dismissed" ? "已隐藏，可在结果页「不合适」里找回" : "已取消"); }
    catch (e) { setJobs(before); toast((e as Error).message); }
  };

  const sources = overview?.sources.filter((s) => s.config.enabled) ?? [];
  const paused = overview?.sources.filter((s) => s.state === "paused") ?? [];

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>总览</h1>
          <p>
            {overview
              ? `今天新增 ${overview.stats.today} 条${overview.stats.today_no ? `（另有 ${overview.stats.today_no} 条 AI 判为不合适，已隐藏）` : ""} · 今天 AI 推荐 ${overview.stats.today_high} 条 · 累计 ${overview.stats.total.toLocaleString()} 条`
              : "加载中…"}
          </p>
        </div>
        <button className="btn" onClick={runNow} disabled={kicking || activeCount > 0 || !overview?.has_keywords}
          title={activeCount ? "正在检索，跑完再点" : "马上检索所有开启的信源"}>
          {kicking || activeCount > 0 ? <Loader2 className="spin" /> : <RefreshCw />}
          {activeCount > 0 ? `检索中（${activeCount}）` : "立即检索"}
        </button>
        <button className="btn primary" onClick={() => go("jobs")}><BriefcaseBusiness />查看岗位</button>
      </div>

      {overview && !overview.has_keywords && (
        <div className="notice blue">
          <Info />
          <div className="grow"><b>开始之前，先设置搜索条件。</b>
            <span className="muted"> 关键词、城市、薪资这些设好以后才会开始检索。需要登录的平台和 AI 整理可以之后再配。</span></div>
          <button className="btn primary sm" onClick={() => go("criteria")}>去设置<ArrowRight /></button>
        </div>
      )}
      {paused.map((s) => (
        <div className="notice danger" key={s.id}>
          <AlertTriangle />
          <div className="grow"><b>{s.name} 已暂停：</b>{s.config.paused_reason || "需要处理"}</div>
          <button className="btn sm" onClick={() => go(s.needs_login ? "accounts" : "sources")}>去处理<ArrowRight /></button>
        </div>
      ))}
      {overview && overview.has_keywords && !overview.running && (
        <div className="notice">
          <PauseCircle className="faint" />
          <div className="grow muted">自动检索已关闭，现在只在点「立即检索」时运行。打开左下角的开关后，会按每个信源设定的间隔一直检索。</div>
        </div>
      )}
      {overview && !overview.has_key && overview.has_keywords && (
        <div className="notice">
          <Info className="faint" />
          <div className="grow muted">还没有填 DeepSeek key：岗位不会被 AI 整理字段和打匹配分，社区帖子只显示原文，全网搜索也用不了。</div>
          <button className="btn sm" onClick={() => go("accounts")}>去填写</button>
        </div>
      )}

      <section className="section">
        <div className="section-head">
          <h2>信源</h2>
          <span className="sub">{sources.length} 个开启</span>
          <span className="grow" />
          <button className="btn ghost sm" onClick={() => go("sources")}>管理信源<ArrowRight /></button>
        </div>
        <div className="strip">
          {sources.map((s) => {
            const m = STATE_META[s.state];
            return (
              <button key={s.id} className={`cell ${s.state === "paused" ? "bad" : ""}`} onClick={() => go("sources")}
                title={s.last_run?.error || m.label}>
                <span className="name ellipsis">{s.name}</span>
                <span className="row" style={{ gap: 6, fontSize: 12 }}>
                  <i className={`dot ${m.dot}`} /><span className="muted grow ellipsis">{m.label}</span>
                  {s.region === "overseas" && <span className="badge blue" style={{ height: 18, padding: "0 4px" }}>海外</span>}
                </span>
                <span className="meta">
                  <span>{s.state === "running" ? "进行中" : s.state === "queued" ? "排队中" : !overview?.running ? "手动" : s.night_now ? "夜间暂停" : s.next_run ? untilLabel(s.next_run) : "即将开始"}</span>
                  <span className="add">{s.last_run?.ok ? `+${s.last_run.added}` : ""}</span>
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>岗位</h2>
          <Seg<Tab> label="岗位范围" value={tab} onChange={setTab} options={[
            { value: "today", label: "今天新增" }, { value: "high", label: "AI 推荐（近 7 天）" }, { value: "starred", label: "收藏" },
          ]} />
          {loadingJobs && jobs !== null && <Loader2 size={14} className="spin faint" />}
          <span className="grow" />
          <button className="btn ghost sm" onClick={() => go("jobs")}>全部岗位<ArrowRight /></button>
        </div>
        <div className="panel t-scroll">
          {jobs === null ? <div className="empty"><Loader2 className="spin" /></div> :
            jobs.length === 0 ? (
              <div className="empty"><Inbox /><b>{tab === "starred" ? "还没有收藏的岗位" : "这里还没有岗位"}</b>
                <span>{tab === "today" ? "检索完成后，新岗位会出现在这里。" : tab === "high" ? "AI 判断为「推荐」的岗位会出现在这里。" : "在岗位右侧点星标收藏。"}</span></div>
            ) : (
              <table className="table jobs-table">
                <thead><tr><th style={{ width: 60 }}>匹配</th><th>岗位</th><th style={{ width: "15%" }}>公司</th><th style={{ width: "11%" }}>地点</th><th style={{ width: "12%" }}>薪资</th><th style={{ width: 170 }}>信源</th><th style={{ width: 92 }}>发布</th><th style={{ width: 92 }} /></tr></thead>
                <tbody>
                  {jobs.map((j) => (
                    <tr key={j.id}>
                      <td><Score value={j.score} /></td>
                      <td className="wrap">
                        <div className="row" style={{ gap: 6 }}>
                          <button className="job-title" onClick={() => openJob(j.url, toast)} title={j.title_zh ? `原文：${j.title}` : "打开原始页面"}>{j.title_zh || j.title}</button>
                          {j.verdict && j.verdict !== "no" && <span className={`badge ${verdictOf(j).cls}`}>{verdictOf(j).label}</span>}
                        </div>
                        {(j.verdict_reason || j.ai_summary) && <div className="job-sub ellipsis" title={j.ai_summary || ""}>{j.verdict_reason || j.ai_summary}</div>}
                      </td>
                      <td title={j.company}>{j.company || <span className="faint">未写</span>}</td>
                      <td title={j.city}>{j.remote ? "远程" : j.city || <span className="faint">—</span>}</td>
                      <td title={j.salary}>{j.salary || <span className="faint">未写</span>}</td>
                      <td>
                        <span className="badge">{platformOf(j)}</span>
                        {platformsOf(j).length > 1 && (
                          <span className="badge blue" style={{ marginLeft: 4 }} title={`这些平台都有：${platformsOf(j).join("、")}`}>
                            {platformsOf(j).length} 个平台
                          </span>
                        )}
                      </td>
                      <td className="faint" style={{ fontSize: 13 }} title={`发现于 ${timeAgo(j.first_seen)}`}>
                        {publishedAgo(j.published_at)?.text ?? "未知"}
                      </td>
                      <td><div className="actions"><JobActions job={j} onChange={(s) => setStatus(j, s)} /></div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>
      </section>
    </div>
  );
}
