import { Loader2, Sparkles } from "lucide-react";
import type { Overview } from "../lib/api";
import { api } from '../lib/api';
import { useState } from 'react';

/** 顶部进度条：只要有检索在跑、或者 AI 还在整理，就一直显示在每个页面顶部。 */
export default function ActivityBar({ overview }: { overview: Overview }) {
  const { running, queued, pending_enrich } = overview.activity;
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState('');
  if (!running.length && !queued.length && !pending_enrich) return null;
  const name = (id: string) => overview.sources.find((s) => s.id === id)?.name ?? id;
  const total = running.length + queued.length;
  // 浏览器类每个大约 1 分钟（含冷却），接口类很快
  const detail = overview.sources.find(s=>s.state==='running')?.progress?.message;
  return (
    <div className="activity" role="status" aria-live="polite">
      {total > 0 ? (
        <>
          <Loader2 className="spin" />
          <span className="grow ellipsis">
            <b>正在检索</b>：{running.map(name).join("、") || "等待中"}
            {queued.length > 0 && <span className="muted">　·　排队 {queued.length} 个：{queued.map(name).join("、")}</span>}
          </span>
          {detail && <span className="muted activity-detail">{detail}</span>}
          <button className="btn sm" disabled={cancelling} onClick={async()=>{setCancelling(true);try{await api.cancel();}catch(e){setError((e as Error).message);}finally{setCancelling(false);}}}>{cancelling?'取消中…':'取消采集'}</button>
        </>
      ) : null}
      {pending_enrich > 0 && (
        <span className={`row ${total ? "" : "grow"}`} style={{ gap: 6 }}>
          <Sparkles size={15} className="ai" />AI 整理中：还剩 {pending_enrich} 条
        </span>
      )}
      {total > 0 && <i className="activity-line" />}
      {error && <span role="alert">{error}</span>}
    </div>
  );
}
