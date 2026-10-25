import { useCallback, useEffect, useRef, useState } from "react";
import { BriefcaseBusiness, Coins, KeyRound, LayoutDashboard, RadioTower, ScrollText, SlidersHorizontal, Sparkles, FolderOpen } from "lucide-react";
import { api, selectPlan, getSelectedPlan, type Plan, type Overview as OverviewData } from "../lib/api";
import { untilLabel } from "../lib/format";
import { useTheme } from "../lib/theme";
import { Switch, ThemeToggle, useToast } from "../components/ui";
import Plans from "./pages/Plans";
import "../styles/plans.css";
import ActivityBar from "./ActivityBar";
import Overview from "./pages/Overview";
import Jobs from "./pages/Jobs";
import Criteria from "./pages/Criteria";
import Sources from "./pages/Sources";
import Accounts from "./pages/Accounts";
import Assistant from "./pages/Assistant";
import Logs from "./pages/Logs";
import Usage from "./pages/Usage";

export type PageId = "plans" | "overview" | "jobs" | "criteria" | "sources" | "accounts" | "assistant" | "usage" | "logs";

const NAV: { id: PageId; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "plans", label: "求职方案", icon: FolderOpen },
  { id: "overview", label: "总览", icon: LayoutDashboard },
  { id: "jobs", label: "岗位", icon: BriefcaseBusiness },
  { id: "criteria", label: "方案条件", icon: SlidersHorizontal },
  { id: "sources", label: "信源与频率", icon: RadioTower },
  { id: "accounts", label: "账号与密钥", icon: KeyRound },
  { id: "assistant", label: "指挥助手", icon: Sparkles },
  { id: "usage", label: "AI 用量", icon: Coins },
  { id: "logs", label: "运行日志", icon: ScrollText },
];

export interface PageProps {
  planList: Plan[];
  overview: OverviewData | null;
  currentPlan: string;
  choosePlan: (id: string) => void;
  refresh: () => Promise<void>;
  go: (p: PageId) => void;
  toast: (m: string) => void;
}

export default function App() {
  const [page, setPage] = useState<PageId>("plans");
  const [planList,setPlanList] = useState<Plan[]>([]);
  const [currentPlan,setCurrentPlan] = useState(getSelectedPlan());
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [offline, setOffline] = useState(false);
  const [theme, setTheme] = useTheme();
  const [toastNode, toast] = useToast();

  // 记住每个信源上一次看到的状态：从「检索中 / 排队中」变成别的状态，就说明这一轮跑完了，弹提示
  const prevStates = useRef<Record<string, string>>({});
  const refreshSequence = useRef(0);
  const refresh = useCallback(() => {
    const sequence=++refreshSequence.current;
    const requestedPlan=getSelectedPlan();
    api.plans(true).then(all => {
      const list=all.filter(p=>p.state!=='deleted');
      setPlanList(all);
      if(!list.some(p=>p.id===getSelectedPlan())) {
        const next=list.find(p=>p.state==='active') || list[0];
        if(next) { selectPlan(next.id); setCurrentPlan(next.id); setOverview(null); prevStates.current={}; }
        else { setPage('plans'); setOverview(null); }
      }
    }).catch(() => {});
    return api.overview().then((o) => {
      if (requestedPlan!==getSelectedPlan() || sequence!==refreshSequence.current) return;
      const prev = prevStates.current;
      for (const s of o.sources) {
        const was = prev[s.id];
        if ((was === "running" || was === "queued") && s.state !== "running" && s.state !== "queued") {
          const r = s.last_run;
          toast(r?.ok ? `${s.name} 完成：找到 ${r.found} 条，新增 ${r.added} 条` : `${s.name} 没成功：${r?.error || s.config.paused_reason || "原因见运行日志"}`);
        }
        prev[s.id] = s.state;
      }
      setOverview(o); setOffline(false);
    }).catch(() => setOffline(true));
  }, [toast]);

  const active = overview ? overview.activity.running.length + overview.activity.queued.length > 0 || overview.activity.pending_enrich > 0 : false;
  useEffect(() => {
    refresh();
    // 有检索在跑时 2 秒刷新一次，平时 5 秒
    const t = window.setInterval(refresh, active ? 2000 : 5000);
    return () => window.clearInterval(t);
  }, [refresh, active]);

  const paused = overview?.sources.some((s) => s.state === "paused") ?? false;
  const nextRun = overview?.sources.map((s) => s.next_run).filter(Boolean).sort()[0] ?? null;
  const busy = overview?.sources.filter((s) => s.state === "running") ?? [];
  const queued = overview?.sources.filter((s) => s.state === "queued") ?? [];

  const toggleRunning = async (v: boolean) => {
    await api.setRunning(v);
    toast(v ? "已开启自动检索" : "已关闭自动检索");
    refresh();
  };

  const choosePlan = (id: string) => {
    selectPlan(id); setCurrentPlan(id); setOverview(null); prevStates.current={}; refresh();
  };
  const props: PageProps = { overview, refresh, go: setPage, toast, currentPlan, choosePlan, planList };

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <img src="/icon.svg" alt="" />
          <div><b>求职雷达</b><small>本机运行</small></div>
        </div>
        <nav className="nav" aria-label="主导航">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} aria-current={page === id ? "page" : undefined} onClick={() => setPage(id)} title={label}>
              <Icon /><span>{label}</span>
              {id === "jobs" && overview ? <span className="count" title="今天新增">{overview.stats.today || ""}</span> : null}
              {id === "sources" && paused ? <i className="alert" aria-label="有信源需要处理" /> : null}
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <div className="runbox">
            <div className="row">
              <b className="grow">当前方案自动检索</b>
              <Switch label="自动检索" checked={!!overview?.running} disabled={!overview || !overview.has_keywords || overview.plan?.state!=="active"}
                onChange={toggleRunning} />
            </div>
            <small>
              {offline ? "本地服务未连接" :
                !overview ? "加载中…" :
                  busy.length ? `正在检索：${busy.map((b) => b.name).join("、")}${queued.length ? `，${queued.length} 个排队` : ""}` :
                    overview.running ? `下一次：${untilLabel(nextRun)}` :
                      overview.has_keywords ? "已关闭，只在手动点击时检索" : "先设置搜索关键词"}
            </small>
          </div>
          <ThemeToggle theme={theme} setTheme={setTheme} />
        </div>
      </aside>
      <main className="main">
        <div className="plan-context">
          <label>当前方案<select className="select" aria-label="当前方案" value={currentPlan} onChange={e=>choosePlan(e.target.value)}>
            {!planList.some(p=>p.id===currentPlan) && <option value={currentPlan}>请选择可用方案</option>}
            {planList.filter(p=>p.state!=='deleted').map(p=><option key={p.id} value={p.id}>{p.person} / {p.name}{p.state==='archived'?'（已归档）':''}</option>)}
          </select></label>
          <span className="plan-context-note">岗位、条件和运行记录属于当前方案</span>
          <button className="btn ghost sm" onClick={()=>setPage('plans')}>管理方案</button>
          {overview?.plan?.state==='archived' && <span className="badge">已归档 · 可查看历史</span>}
        </div>
        {overview && <ActivityBar overview={overview} />}
        {page === "plans" && <Plans {...props} />}
        <div className="plan-content" key={currentPlan}>
        {page === "overview" && <Overview {...props} />}
        {page === "jobs" && <Jobs {...props} />}
        {page === "criteria" && <Criteria {...props} />}
        {page === "sources" && <Sources {...props} />}
        {page === "accounts" && <Accounts {...props} />}
        {page === "assistant" && <Assistant {...props} />}
        {page === "usage" && <Usage {...props} />}
        {page === "logs" && <Logs {...props} />}
        </div>
      </main>
      {toastNode}
    </div>
  );
}
