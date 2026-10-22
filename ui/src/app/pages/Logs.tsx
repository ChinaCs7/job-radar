import { useEffect, useState } from "react";
import { Inbox, Loader2 } from "lucide-react";
import { api, type LogLine, type Run } from "../../lib/api";
import { SOURCE_LABEL, timeAgo } from "../../lib/format";
import { Seg } from "../../components/ui";
import type { PageProps } from "../App";

const KIND: Record<string, string> = { login: "需要登录", blocked: "被风控", config: "缺配置", network: "网络 / 接口错误" };

function duration(r: Run): string {
  if (!r.finished_at) return "进行中";
  const s = Math.round((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000);
  return s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`;
}

export default function Logs({ overview }: PageProps) {
  const [tab, setTab] = useState<"runs" | "logs">("runs");
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [logs, setLogs] = useState<LogLine[] | null>(null);
  const tick = overview?.stats.total;

  useEffect(() => {
    if (tab === "runs") api.runs().then(setRuns);
    else api.logs().then(setLogs);
  }, [tab, tick]);

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow"><h1>运行日志</h1><p>每次检索的结果和出错原因。</p></div>
        <Seg label="日志类型" value={tab} onChange={setTab} options={[{ value: "runs", label: "检索记录" }, { value: "logs", label: "详细日志" }]} />
      </div>
      <div className="panel t-scroll">
        {tab === "runs" ? (
          runs === null ? <div className="empty"><Loader2 className="spin" /></div> :
            runs.length === 0 ? <div className="empty"><Inbox /><b>还没有检索记录</b></div> : (
              <table className="table">
                <thead><tr><th>时间</th><th>信源</th><th>结果</th><th>找到</th><th>新增</th><th>耗时</th><th>说明</th></tr></thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.id}>
                      <td className="faint" style={{ whiteSpace: "nowrap" }}>{timeAgo(r.started_at)}</td>
                      <td style={{ whiteSpace: "nowrap" }}>{SOURCE_LABEL[r.source] || r.source}</td>
                      <td>{r.ok === null ? <span className="badge blue">进行中</span> : r.ok ? <span className="badge ok">成功</span> :
                        <span className={`badge ${r.error_kind === "network" ? "warn" : "danger"}`}>{KIND[r.error_kind || ""] || "失败"}</span>}</td>
                      <td>{r.found}</td><td>{r.added}</td>
                      <td className="faint" style={{ whiteSpace: "nowrap" }}>{duration(r)}</td>
                      <td className="muted" style={{ fontSize: 13, maxWidth: 420 }}>{r.error}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
        ) : (
          logs === null ? <div className="empty"><Loader2 className="spin" /></div> :
            logs.map((l) => (
              <div className="log-line" key={l.id}>
                <span className="faint">{timeAgo(l.at)}</span>
                <span className="muted">{SOURCE_LABEL[l.source] || (l.source === "llm" ? "AI" : l.source || "系统")}</span>
                <span className={`lv-${l.level}`}>{l.message}</span>
              </div>
            ))
        )}
      </div>
    </div>
  );
}
