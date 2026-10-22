import { useEffect, useState } from "react";
import { Inbox, Loader2, Save } from "lucide-react";
import { api, type Usage as U, type UsageRow } from "../../lib/api";
import { dayLabel, timeAgo } from "../../lib/format";
import { Seg } from "../../components/ui";
import type { PageProps } from "../App";

const KIND: Record<string, string> = {
  enrich: "整理岗位", summary: "每日总结", assistant: "AI 助手", search: "DeepSeek 搜索", test: "测试连接", other: "其他",
};

const yuan = (v: number) => (v >= 1 ? `¥${v.toFixed(2)}` : v >= 0.01 ? `¥${v.toFixed(3)}` : v > 0 ? `¥${v.toFixed(4)}` : "¥0");
const tok = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n));

function Sum({ label, r }: { label: string; r: UsageRow }) {
  return (
    <div>
      <small>{label}</small>
      <b>{yuan(r.cost)}</b>
      <span className="sub">{r.calls} 次 · 输入 {tok(r.prompt)} · 输出 {tok(r.completion)}</span>
    </div>
  );
}

export default function Usage({ overview, toast }: PageProps) {
  const [u, setU] = useState<U | null>(null);
  const [tab, setTab] = useState<"day" | "calls">("day");
  const [price, setPrice] = useState<U["price"] | null>(null);
  const tick = overview?.stats.total;

  useEffect(() => { api.usage().then((x) => { setU(x); setPrice((p) => p ?? x.price); }).catch(() => { }); }, [tick]);

  const savePrice = async () => {
    if (!price) return;
    await api.saveSettings({ llm: { price } });
    toast("已保存价格，之后的调用按新价格计算");
  };

  if (!u) return <div className="page"><div className="empty"><Loader2 className="spin" /></div></div>;
  const maxDay = Math.max(...u.by_day.map((d) => d.cost), 0.000001);

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>AI 用量</h1>
          <p>每次调用 DeepSeek 的 token 数和估算花费。现在是{u.peak_now ? "高峰时段（全价）" : "空闲时段（半价）"}；实际扣费以 DeepSeek 后台为准。</p>
        </div>
      </div>

      <div className="panel usage-sum">
        <Sum label="今天" r={u.today} />
        <Sum label="本月" r={u.month} />
        <Sum label="累计" r={u.total} />
      </div>

      <section className="section">
        <div className="section-head">
          <h2>明细</h2>
          <Seg label="明细类型" value={tab} onChange={setTab} options={[{ value: "day", label: "按天" }, { value: "calls", label: "每次调用" }]} />
        </div>
        <div className="panel t-scroll">
          {u.total.calls === 0 ? (
            <div className="empty"><Inbox /><b>还没有调用记录</b><span>填好 DeepSeek key 后，整理岗位、总结和 AI 助手的每次调用都会记在这里。</span></div>
          ) : tab === "day" ? (
            <table className="table">
              <thead><tr><th>日期</th><th className="num">调用</th><th className="num">输入 tokens</th><th className="num">其中缓存命中</th><th className="num">输出 tokens</th><th className="num">花费</th><th style={{ width: "26%" }} /></tr></thead>
              <tbody>
                {u.by_day.map((d) => (
                  <tr key={d.day}>
                    <td style={{ whiteSpace: "nowrap" }}>{dayLabel(d.day)}</td>
                    <td className="num">{d.calls}</td>
                    <td className="num">{d.prompt.toLocaleString()}</td>
                    <td className="num faint">{d.hit.toLocaleString()}</td>
                    <td className="num">{d.completion.toLocaleString()}</td>
                    <td className="num"><b style={{ fontWeight: 500 }}>{yuan(d.cost)}</b></td>
                    <td><div className="bar" style={{ width: `${(d.cost / maxDay) * 100}%` }} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="table">
              <thead><tr><th>时间</th><th>用途</th><th className="num">输入</th><th className="num">缓存命中</th><th className="num">输出</th><th>时段</th><th className="num">花费</th></tr></thead>
              <tbody>
                {u.recent.map((r) => (
                  <tr key={r.id}>
                    <td className="faint" style={{ whiteSpace: "nowrap" }}>{timeAgo(r.at)}</td>
                    <td>{KIND[r.kind] || r.kind}</td>
                    <td className="num">{r.kind === "search" ? `${r.requests} 次` : r.prompt_tokens.toLocaleString()}</td>
                    <td className="num faint">{r.kind === "search" ? "—" : r.cache_hit_tokens.toLocaleString()}</td>
                    <td className="num">{r.kind === "search" ? "—" : r.completion_tokens.toLocaleString()}</td>
                    <td><span className={`badge ${r.peak ? "warn" : ""}`}>{r.peak ? "高峰" : "空闲"}</span></td>
                    <td className="num">{yuan(r.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {u.by_kind.length > 0 && (
        <section className="section">
          <div className="section-head"><h2>按用途（近 30 天）</h2></div>
          <div className="panel t-scroll">
            <table className="table">
              <thead><tr><th>用途</th><th className="num">调用</th><th className="num">输入 tokens</th><th className="num">输出 tokens</th><th className="num">花费</th></tr></thead>
              <tbody>
                {u.by_kind.map((k) => (
                  <tr key={k.kind}>
                    <td>{KIND[k.kind] || k.kind}</td>
                    <td className="num">{k.kind === "search" ? `${k.requests} 次` : k.calls}</td>
                    <td className="num">{k.prompt.toLocaleString()}</td>
                    <td className="num">{k.completion.toLocaleString()}</td>
                    <td className="num">{yuan(k.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {price && (
        <section className="section">
          <div className="section-head"><h2>价格</h2><span className="sub">元 / 百万 tokens（高峰时段），来自 DeepSeek 官网；官网调价时在这里改</span></div>
          <div className="panel" style={{ padding: "14px 18px" }}>
            <div className="row" style={{ flexWrap: "wrap", gap: 16, fontSize: 13 }}>
              {([["input_hit", "输入（缓存命中）"], ["input_miss", "输入（未命中）"], ["output", "输出"], ["search_per_1k", "搜索（元 / 千次）"], ["off_peak_ratio", "空闲时段折扣"]] as const).map(([k, l]) => (
                <label key={k} className="row" style={{ gap: 6 }}>
                  <span className="muted">{l}</span>
                  <input className="input" type="number" step="0.01" min={0} style={{ width: 84 }} value={price[k]}
                    onChange={(e) => setPrice({ ...price, [k]: Number(e.target.value) })} />
                </label>
              ))}
              <button className="btn sm" onClick={savePrice}><Save />保存价格</button>
            </div>
            <p className="faint" style={{ fontSize: 12, marginTop: 8 }}>
              高峰时段：工作日 9:00–12:00、14:00–18:00，其他时间按折扣算。法定节假日也是空闲价，但这里按工作日估算，可能略高。
            </p>
          </div>
        </section>
      )}
    </div>
  );
}
