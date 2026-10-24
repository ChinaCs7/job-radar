import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, Play, RotateCcw } from "lucide-react";
import { api, type Source, type SourceConfig } from "../../lib/api";
import { timeAgo, untilLabel } from "../../lib/format";
import { AsyncButton, STATE_META, Switch, TagInput } from "../../components/ui";
import type { PageProps } from "../App";

const INTERVALS = [15, 30, 60, 120, 180, 360, 720, 1440];
const intervalLabel = (m: number) => (m < 60 ? `${m} 分钟` : m < 1440 ? `${m / 60} 小时` : "每天");
const JOBSPY_SITES = [["linkedin", "LinkedIn"], ["indeed", "Indeed"], ["google", "Google Jobs"], ["glassdoor", "Glassdoor"]] as const;

export default function Sources({ overview, refresh, go, toast }: PageProps) {
  const [open, setOpen] = useState<string | null>(null);
  const [night, setNight] = useState<{ start: number; end: number } | null>(null);
  useEffect(() => { api.settings().then((s) => setNight(s.night)); }, []);

  const list = overview?.sources ?? [];
  const groups = [...new Set(list.map((s) => s.group))];

  const patch = async (s: Source, cfg: Partial<SourceConfig>) => {
    try { await api.saveSettings({ sources: { [s.id]: cfg } }); refresh(); }
    catch (e) { toast((e as Error).message); }
  };
  const run = async (s: Source) => {
    try {
      const result=await api.runNow(s.id);
      if (!result.started.length) { toast('没有启动新任务：该信源正在运行或已达到今日全局预算'); return; }
      toast(s.browser ? `${s.name} 已加入浏览器队列，前面有任务时会稍等` : `开始检索 ${s.name}`);
      refresh();
    } catch (e) { toast((e as Error).message); }
  };
  const resume = async (s: Source) => { await api.resume(s.id); toast(`${s.name} 已恢复，下一轮会继续检索`); refresh(); };
  const saveNight = async (n: { start: number; end: number }) => { setNight(n); await api.saveSettings({ night: n }); };

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>信源与频率</h1>
          <p>每个信源按自己的间隔检索，间隔会随机浮动 15%。一个信源出错不影响其他信源。</p>
        </div>
        {night && (
          <div className="row muted" style={{ fontSize: 13 }}>
            夜间暂停
            <select className="select" style={{ width: 84 }} value={night.start} aria-label="夜间暂停开始"
              onChange={(e) => saveNight({ ...night, start: +e.target.value })}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{h}:00</option>)}
            </select>
            到
            <select className="select" style={{ width: 84 }} value={night.end} aria-label="夜间暂停结束"
              onChange={(e) => saveNight({ ...night, end: +e.target.value })}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{h}:00</option>)}
            </select>
          </div>
        )}
      </div>

      {!overview ? <div className="empty"><Loader2 className="spin" /></div> : (
        <div className="panel">
          {groups.map((g) => (
            <div key={g}>
              <div className="group-title">{g}</div>
              {list.filter((s) => s.group === g).map((s) => {
                const m = STATE_META[s.state];
                const lr = s.last_run;
                const hasMore = ["jobspy", "websearch", "bing", "boss", "company"].includes(s.id);
                return (
                  <div className="src-row" key={s.id}>
                    <Switch label={`开启 ${s.name}`} checked={s.config.enabled} onChange={(v) => patch(s, { enabled: v })} />
                    <div>
                      <div className="title">
                        <b>{s.name}</b>
                        {s.region === "overseas" && <span className="badge blue">海外</span>}
                        {s.needs_login && <span className="badge warn">需要登录 / 验证</span>}
                        {s.browser && <span className="badge" title="用专用浏览器打开网页检索">浏览器</span>}
                        {s.needs_key && <span className="badge">需要 DeepSeek key</span>}
                        <span className="row" style={{ gap: 6, fontSize: 13 }}><i className={`dot ${m.dot}`} /><span className="muted">{m.label}</span></span>
                      </div>
                      <div className="desc">{s.note}</div>
                      {s.progress && <div className="desc">{s.progress.message}</div>}
                      <div className="desc">今日全局次数 {s.daily_used ?? 0} / {s.daily_cap ?? '—'} · 多个方案共用平台访问预算</div>
                      <div className="stat">
                        <span>上次 {lr ? timeAgo(lr.finished_at || lr.started_at) : "—"}{lr?.ok ? `，找到 ${lr.found} 条，新增 ${lr.added} 条` : ""}</span>
                        <span>下次 {!overview.running ? "自动检索已关闭" : s.night_now ? "夜间暂停中" : s.next_run ? untilLabel(s.next_run) : "即将开始"}</span>
                        <span>累计 {s.total} 条</span>
                      </div>
                      {s.state === "paused" && <div className="stat err">{s.config.paused_reason}</div>}
                      {s.state === "error" && lr?.error && <div className="stat err">{lr.error}</div>}
                    </div>
                    <div className="ctrl">
                      <select className="select" value={s.config.interval_min} aria-label={`${s.name} 检索间隔`}
                        onChange={(e) => patch(s, { interval_min: +e.target.value })}>
                        {INTERVALS.map((m) => <option key={m} value={m}>每 {intervalLabel(m)}</option>)}
                      </select>
                      <label className="check" style={{ fontSize: 13 }}>
                        <input type="checkbox" checked={s.config.night_pause} onChange={(e) => patch(s, { night_pause: e.target.checked })} />夜间暂停
                      </label>
                      {s.state === "paused" ? (
                        <>
                          {s.needs_login && <button className="btn sm" onClick={() => go("accounts")}>去登录</button>}
                          <AsyncButton className="btn sm" icon={<RotateCcw />} onClick={() => resume(s)}>已处理，恢复</AsyncButton>
                        </>
                      ) : (
                        <AsyncButton className="btn sm" disabled={!s.config.enabled || s.state === "running" || s.state === "queued"}
                          icon={s.state === "running" || s.state === "queued" ? <Loader2 className="spin" /> : <Play />} onClick={() => run(s)}>
                          {s.state === "running" ? "检索中" : s.state === "queued" ? "排队中" : "检索"}
                        </AsyncButton>
                      )}
                      {hasMore ? (
                        <button className="btn ghost sm icon" aria-expanded={open === s.id} title="更多设置"
                          onClick={() => setOpen(open === s.id ? null : s.id)}>
                          {open === s.id ? <ChevronDown /> : <ChevronRight />}
                        </button>
                      ) : <span style={{ width: 26, flex: "none" }} aria-hidden />}
                    </div>
                    {open === s.id && <More s={s} patch={(c) => patch(s, c)} />}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface Company { id: string; name: string; type: string; enabled: boolean; host?: string; channel?: string; path?: string; portal_type?: number }

/** 从飞书招聘的网址解析出公司配置，例如 https://xxx.jobs.feishu.cn/index/position/list */
function parseFeishu(url: string, name: string): Company | null {
  try {
    const u = new URL(url.trim());
    const path = u.pathname.split("/").filter(Boolean)[0] || "index";
    return { id: `custom-${u.host}`, name: name.trim() || u.host, type: "feishu", enabled: true, host: u.host,
      channel: "saas-career", path, portal_type: 6 };
  } catch { return null; }
}

function CompanyEditor({ list, save }: { list: Company[]; save: (l: Company[]) => void }) {
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const add = () => {
    const c = parseFeishu(url, name);
    if (!c || list.some((x) => x.id === c.id)) return;
    save([...list, c]); setUrl(""); setName("");
  };
  return (
    <div className="more">
      <div className="row" style={{ gap: 18, flexWrap: "wrap" }}>
        {list.map((c) => (
          <label className="check" key={c.id} style={{ fontSize: 13 }}>
            <input type="checkbox" checked={c.enabled !== false}
              onChange={(e) => save(list.map((x) => (x.id === c.id ? { ...x, enabled: e.target.checked } : x)))} />
            {c.name}
            {c.id.startsWith("custom-") && (
              <button className="btn ghost sm" style={{ height: 20, padding: "0 4px" }} title="移除"
                onClick={(e) => { e.preventDefault(); save(list.filter((x) => x.id !== c.id)); }}>移除</button>
            )}
          </label>
        ))}
      </div>
      <div className="row" style={{ flexWrap: "wrap", fontSize: 13 }}>
        <span className="muted">添加用飞书招聘的公司</span>
        <input className="input" style={{ width: 120 }} placeholder="公司名" value={name} onChange={(e) => setName(e.target.value)} />
        <input className="input" style={{ flex: 1, minWidth: 240 }} placeholder="招聘官网网址，例如 https://xxx.jobs.feishu.cn/index"
          value={url} onChange={(e) => setUrl(e.target.value)} />
        <button className="btn sm" disabled={!parseFeishu(url, name)} onClick={add}>添加</button>
      </div>
      <span className="faint" style={{ fontSize: 12 }}>网址里有 jobs.feishu.cn、或者页面底部写着「飞书招聘」的公司官网都可以加。</span>
    </div>
  );
}

function More({ s, patch }: { s: Source; patch: (c: Partial<SourceConfig>) => void }) {
  const c = s.config as SourceConfig & { sites?: string[]; location?: string; max_pages?: number; max_combos?: number; max_queries?: number; companies?: Company[] };
  if (s.id === "company") return <CompanyEditor list={c.companies ?? []} save={(l) => patch({ companies: l } as Partial<SourceConfig>)} />;
  if (s.id === "jobspy") {
    const sites = c.sites ?? [];
    return (
      <div className="more">
        <div className="row" style={{ gap: 18, flexWrap: "wrap" }}>
          <span className="muted" style={{ fontSize: 13 }}>平台</span>
          {JOBSPY_SITES.map(([k, l]) => (
            <label className="check" key={k} style={{ fontSize: 13 }}>
              <input type="checkbox" checked={sites.includes(k)}
                onChange={(e) => patch({ sites: e.target.checked ? [...sites, k] : sites.filter((x) => x !== k) })} />{l}
            </label>
          ))}
        </div>
        <div className="row">
          <span className="muted" style={{ fontSize: 13, width: 56 }}>地点</span>
          <input className="input" style={{ maxWidth: 280 }} defaultValue={c.location || ""} placeholder="例如：Singapore、Remote；不填表示不限"
            onBlur={(e) => patch({ location: e.target.value })} />
        </div>
      </div>
    );
  }
  if (s.id === "websearch" || s.id === "bing") {
    return (
      <div className="more">
        <span className="muted" style={{ fontSize: 13 }}>
          搜这些站点（每个关键词 × 每个站点搜一次，再加一次不限站点的搜索）。{s.id === "bing" ? "必应是免费的，用专用浏览器打开搜索页。" : "DeepSeek 搜索按次收费。"}
        </span>
        <TagInput value={c.sites ?? []} onChange={(v) => patch({ sites: v })} placeholder="xiaohongshu.com" />
        <div className="row" style={{ fontSize: 13 }}>
          <span className="muted">每轮最多</span>
          <input className="input" type="number" min={1} max={50} style={{ width: 72 }} defaultValue={c.max_queries ?? 12}
            onBlur={(e) => patch({ max_queries: Number(e.target.value) || 12 })} />
          <span className="muted">{s.id === "websearch" ? "次搜索（按次计费）" : "次搜索"}</span>
        </div>
      </div>
    );
  }
  return (
    <div className="more">
      <div className="row" style={{ fontSize: 13, flexWrap: "wrap" }}>
        <span className="muted">每个「关键词 × 城市」翻</span>
        <input className="input" type="number" min={1} max={5} style={{ width: 64 }} defaultValue={c.max_pages ?? 2}
          onBlur={(e) => patch({ max_pages: Number(e.target.value) || 2 })} />
        <span className="muted">页，每轮最多</span>
        <input className="input" type="number" min={1} max={20} style={{ width: 64 }} defaultValue={c.max_combos ?? 6}
          onBlur={(e) => patch({ max_combos: Number(e.target.value) || 6 })} />
        <span className="muted">个组合。数字越大越容易触发验证。</span>
      </div>
    </div>
  );
}
