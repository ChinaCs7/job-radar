import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowUp, Check, FileText, Info, Loader2, Paperclip, Search, Settings2, Sparkles, Trash2, X } from "lucide-react";
import { openJob } from "./Jobs";
import { api, streamAgent, type AgentStep, type SearchDraft, type Proposal } from "../../lib/api";
import { today } from "../../lib/format";
import { AsyncButton } from "../../components/ui";
import type { PageProps } from "../App";

interface Attachment { name: string; text: string; chars: number; masked: number }
type ProposalState = "pending" | "applied" | "discarded" | "expired";
interface Msg {
  role: "user" | "assistant";
  content: string;
  steps?: AgentStep[];
  drafts?: SearchDraft[];
  questions?: string[];
  notice?: string;
  error?: boolean;
  attachment?: Attachment;
  proposals?: (Proposal & { state?: ProposalState })[];
}

const KEY = "jr-chat-plan:";
const SUGGEST = [
  "列出我当前的全部求职方案",
  "根据我的简历，设计适合我的求职方案",
  "今天最适合我的 3 个岗位是哪些？",
  "收藏的岗位帮我比较一下",
  "各个信源最近表现怎么样？",
];
const TOOL_LABEL: Record<string, string> = {
  preview_search_plans: "设计搜索方案",
  list_plans: "列出方案", get_plan: "读取方案", create_plan: "创建方案", update_plan: "编辑方案", manage_plan: "管理方案", run_plan: "启动方案检索", cancel_plan: "取消任务", plan_progress: "检查进度", search_plan_jobs: "查询方案岗位",
  search_jobs: "查岗位", get_job: "看详情", get_stats: "看统计", get_settings: "看当前设置", propose_settings: "提出修改方案",
};

function stepText(s: NonNullable<Msg["steps"]>[number]): string {
  const l = TOOL_LABEL[s.tool] || s.tool;
  if (s.tool === "get_job" && s.args.serial != null) return `${l} #${s.args.serial}`;
  if (s.tool === "search_jobs") return `${l}${s.args.q ? `「${s.args.q}」` : ""}（${s.count ?? 0} 条）`;
  return l;
}

/** 发给模型的内容：附件（简历）作为一段带标记的文字跟在消息后面 */
function toWire(m: Msg) {
  const att = m.attachment ? `\n\n<附件 名称="${m.attachment.name}">\n${m.attachment.text}\n</附件>` : "";
  const preview=m.drafts ? `\n\n<方案预览数据>${JSON.stringify(m.drafts)}</方案预览数据>` : "";
  return { role: m.role, content: m.content + att + preview };
}

/** 只处理 **粗体**、#编号、列表和段落，生成 React 节点而不是拼 HTML：模型输出里可能带着岗位原文。
 *  「#588」变成可点的按钮：点了用专用浏览器打开那个岗位。 */
function render(text: string, onRef: (n: number) => void): ReactNode {
  const blocks = text.split(/\n{2,}/);
  const refs = (s: string, k: string) => s.split(/(#\d{1,6})/g).map((p, i) =>
    /^#\d+$/.test(p) ? <button key={`${k}-${i}`} className="ref" title="打开这个岗位" onClick={() => onRef(Number(p.slice(1)))}>{p}</button> : p);
  const inline = (s: string) => s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <b key={i}>{refs(p.slice(2, -2), `b${i}`)}</b> : <span key={i}>{refs(p, `s${i}`)}</span>);
  return blocks.map((b, i) => {
    const lines = b.split("\n");
    if (lines.every((l) => /^\s*([-*]|\d+\.)\s+/.test(l))) {
      return <ul key={i}>{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*([-*]|\d+\.)\s+/, ""))}</li>)}</ul>;
    }
    return <p key={i}>{lines.map((l, j) => <span key={j}>{j > 0 && <br />}{inline(l)}</span>)}</p>;
  });
}

export default function Assistant({ overview, go, toast, refresh, currentPlan }: PageProps) {
  const [msgs, setMsgs] = useState<Msg[]>(() => { try { return JSON.parse(localStorage.getItem(KEY+currentPlan) || "[]"); } catch { return []; } });
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<"" | "ask" | "summary" | "upload">("");
  const [att, setAtt] = useState<Attachment | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const request = useRef<AbortController | null>(null);
  const follow = useRef(true);
  const [stage,setStage] = useState("");
  useEffect(()=>()=>request.current?.abort(),[]);

  useEffect(() => {
    const timer=window.setTimeout(()=>{try { localStorage.setItem(KEY+currentPlan, JSON.stringify(msgs.slice(-40))); } catch { /* 本机存储不足 */ }},250);
    if(follow.current) end.current?.scrollIntoView({behavior:busy==='ask'?'auto':'smooth'});
    return ()=>window.clearTimeout(timer);
  }, [msgs,currentPlan,busy]);

  const openRef = async (n: number) => {
    try { const j = await api.jobBySerial(n); await openJob(j.url, toast); }
    catch (e) { toast((e as Error).message); }
  };

  const ask = async (text: string) => {
    const q = text.trim() || (att ? "这是我的简历，请根据经历设计可执行的求职方案预览，列出依据和待确认项，先不创建或检索" : "");
    if (!q || busy) return;
    const next: Msg[] = [...msgs, { role: "user", content: q, attachment: att ?? undefined }];
    if(request.current) return;
    const controller=new AbortController();request.current=controller;follow.current=true;
    setMsgs([...next,{role:"assistant",content:"",steps:[]}]); setDraft(""); setAtt(null); setBusy("ask");setStage("正在理解需求");
    const update=(change:(m:Msg)=>Msg)=>setMsgs(ms=>ms.map((m,i)=>i===next.length?change(m):m));
    try {
      await streamAgent(next.filter(m=>!m.error).map(toWire),event=>{
        if(event.type==='delta') update(m=>({...m,content:m.content+event.text}));
        if(event.type==='status') setStage(event.message);
        if(event.type==='tool_start') update(m=>({...m,steps:[...(m.steps || []),{id:event.id,tool:event.tool,args:{},count:null,status:'running'}]}));
        if(event.type==='tool_end') update(m=>({...m,steps:(m.steps || []).map(s=>s.id===event.id?event:s)}));
        if(event.type==='plan_preview') update(m=>({...m,drafts:event.drafts,questions:event.questions}));
        if(event.type==='proposal') update(m=>({...m,proposals:[...(m.proposals || []),{...event.proposal,state:'pending'}]}));
        if(event.type==='done') update(m=>({...m,steps:event.steps}));
      },controller.signal);
    } catch (e) {
      update(m=>({...m,notice:controller.signal.aborted?'已停止回复；已经执行的方案操作保留，可查看方案列表核对。':(e as Error).message,
        steps:(m.steps || []).map(s=>s.status==='running'?{...s,status:'error',message:'本轮已中断，执行结果请核对'}:s)}));
    } finally { request.current=null;setBusy("");setStage("");refresh(); }
  };

  const upload = async (f: File | undefined) => {
    if (!f) return;
    setBusy("upload");
    try {
      const r = await api.uploadAttachment(f);
      setAtt(r);
      toast(r.masked ? `已读取 ${r.name}，${r.chars} 字；手机号、邮箱等 ${r.masked} 处已在发给 AI 前去掉` : `已读取 ${r.name}，${r.chars} 字`);
    } catch (e) { toast((e as Error).message); }
    finally { setBusy(""); if (fileRef.current) fileRef.current.value = ""; }
  };

  const summary = async () => {
    if (busy) return;
    setMsgs((m) => [...m, { role: "user", content: "总结一下今天值得看的岗位" }]); setBusy("summary");
    try {
      const r = await api.makeSummary(today());
      setMsgs((m) => [...m, { role: "assistant", content: r.text, steps: [{ tool: "summary", args: {}, count: r.count }] }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", content: (e as Error).message, error: true }]);
    } finally { setBusy(""); }
  };

  const setProposalState = (pid: string, state: ProposalState) =>
    setMsgs((ms) => ms.map((m) => (m.proposals ? { ...m, proposals: m.proposals.map((p) => (p.proposal_id === pid ? { ...p, state } : p)) } : m)));

  const applyProposal = async (p: Proposal, andRun: boolean) => {
    try {
      const applied = await api.applyProposal(p.proposal_id);
      setProposalState(p.proposal_id, "applied");
      if (andRun) {
        const r = await api.runNow(undefined, applied.plan_id);
        toast(`已应用，开始检索 ${r.started.length} 个信源`);
      } else toast("已应用新的搜索条件，下一轮检索生效");
      refresh();
    } catch (e) {
      const msg = (e as Error).message;
      if (msg.includes("过期")) setProposalState(p.proposal_id, "expired");
      toast(msg);
    }
  };
  const discardProposal = async (p: Proposal) => {
    setProposalState(p.proposal_id, "discarded");
    api.discardProposal(p.proposal_id).catch(() => { });
  };

  if (overview && !overview.has_key) {
    return (
      <div className="page"><div className="empty">
        <Sparkles /><b>Agent 是可选 AI 功能</b><span>配置 key 后可按简历设计方案、查岗位和写总结。基础检索与方案管理照常可用。</span>
        <button className="btn primary" onClick={() => go("accounts")}>去填写</button>
      </div></div>
    );
  }

  return (
    <div className="chat">
      <div className="chat-head">
        <div className="page-head">
          <div className="grow"><h1>Agent</h1>
            <p>描述目标或上传简历，让助手创建、编辑、归档方案，启动检索并检查进度。</p></div>
          <button className="btn" onClick={summary} disabled={!!busy} title="总结今天值得看的岗位；今天没有就总结最近 7 天">
            {busy === "summary" ? <Loader2 className="spin" /> : <Sparkles />}AI 总结</button>
          {msgs.length > 0 && <button className="btn ghost icon" title="清空对话" aria-label="清空对话" disabled={!!busy} onClick={() => setMsgs([])}><Trash2 /></button>}
        </div>
      </div>
      <div className={`chat-log ${msgs.length === 0 && !busy ? "is-empty" : ""}`} onScroll={e=>{const el=e.currentTarget;follow.current=el.scrollHeight-el.scrollTop-el.clientHeight<100;}}>
        <div className="chat-inner">
          {msgs.length === 0 && !busy && (
            <div className="chat-empty">
              <Sparkles />
              <b>从一个求职目标开始</b>
              <span>点输入框左边的 <Paperclip size={13} style={{ verticalAlign: -2 }} /> 上传简历，再说说想找什么，它可以把不同方向和城市整理成独立方案。</span>
              <div className="suggest">{SUGGEST.map((s) => (
                <button key={s} className="chip" onClick={() => (s.includes("简历") && !att ? fileRef.current?.click() : ask(s))}>{s}</button>
              ))}</div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              {m.steps && m.steps.length > 0 && (
                <div className="steps-line"><Search size={13} />
                  {m.steps.map((s, j) => <span key={j} title={s.message} className={s.status==='error'?'err':undefined}>{s.status==='running'?<Loader2 size={12} className="spin" />:s.status==='done'?<Check size={12}/>:null}{s.tool === "summary" ? `汇总 ${s.count} 条` : stepText(s)}{s.status==='error'?`：${s.message || '未完成'}`:""}</span>)}
                </div>
              )}
              {m.attachment && <div className="att-chip"><FileText size={14} />{m.attachment.name}<span className="faint">{m.attachment.chars} 字</span></div>}
              {m.error ? (
                <div className="notice" style={{ fontSize: 13 }}><Info className="faint" /><span className="muted">{m.content}</span></div>
              ) : m.content ? (
                <div className="bubble">{m.role === "assistant" ? render(m.content, openRef) : m.content}</div>
              ) : null}
              {m.notice && <div className="notice" role="status"><Info size={14}/><span>{m.notice}</span></div>}
              {m.drafts && <div className="agent-drafts">
                <b>搜索方案预览 · 尚未创建</b>
                {m.drafts.map((d,j)=><div className="proposal" key={j}>
                  <div className="proposal-head"><FileText size={14}/><b>{d.name}</b><span className="badge">{d.person}</span></div>
                  <div className="proposal-reason">{d.reason}</div>
                  <div className="proposal-reason">关键词：{d.criteria.keywords.join('、')}<br/>城市：{d.criteria.cities.join('、') || '未限定'} · 类型：{d.criteria.job_types.map(t=>({fulltime:'全职',parttime:'兼职',intern:'实习',contract:'合同/外包'}[t] || t)).join('、')}<br/>月薪下限：{d.criteria.salary_min_k?`${d.criteria.salary_min_k}K`:'未设置'} · 最近 {d.criteria.max_age_days} 天</div>
                  {d.evidence.length>0 && <div className="proposal-reason muted">简历依据：{d.evidence.join('；')}</div>}
                </div>)}
                {!!m.questions?.length && <div className="notice">待确认：{m.questions.join('；')}</div>}
                <button className="btn" disabled={!!busy} onClick={()=>ask('按这份预览创建独立方案，保留预览条件，不启动检索：'+JSON.stringify(m.drafts))}>创建这些方案</button>
              </div>}
              {m.proposals?.map((p) => (
                <ProposalCard key={p.proposal_id} p={p} onApply={(run) => applyProposal(p, run)} onDiscard={() => discardProposal(p)} />
              ))}
            </div>
          ))}
          {busy === "ask" && <div className="msg assistant"><div className="steps-line" role="status"><Loader2 size={13} className="spin" />{stage || "正在生成回复"}</div></div>}
          {busy === "summary" && <div className="msg assistant"><div className="steps-line"><Loader2 size={13} className="spin" />正在总结…</div></div>}
          <div ref={end} />
        </div>
      </div>
      <div className="chat-input">
        <div className="box-wrap">
          {att && (
            <div className="att-pending">
              <FileText size={14} /><span className="ellipsis">{att.name}</span>
              <span className="faint">{att.chars} 字{att.masked ? ` · 已去掉 ${att.masked} 处联系方式` : ""}</span>
              <button className="btn ghost icon sm" aria-label="移除附件" onClick={() => setAtt(null)}><X /></button>
            </div>
          )}
          <div className="box">
            <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" hidden onChange={(e) => upload(e.target.files?.[0])} />
            <button className="btn ghost icon" title="上传简历（PDF / Word / TXT）" aria-label="上传附件" disabled={!!busy}
              onClick={() => fileRef.current?.click()}>{busy === "upload" ? <Loader2 className="spin" /> : <Paperclip />}</button>
            <textarea rows={1} value={draft}
              placeholder={att ? "说说你想找什么，例如：远程兼职，开发类（直接回车也行）" : "问问岗位，或者上传简历让它帮你设置；回车发送，Shift + 回车换行"}
              disabled={!!busy}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); ask(draft); } }} />
            {busy==='ask'?<button className="btn icon" aria-label="停止回复" title="停止本轮回复，已执行的操作保留" onClick={()=>request.current?.abort()}><X/></button>:<button className="btn primary icon" aria-label="发送" disabled={(!draft.trim() && !att) || !!busy} onClick={() => ask(draft)}><ArrowUp /></button>}
          </div>
        </div>
      </div>
    </div>
  );
}

/** 方案确认卡片：模型只能提方案，点「应用」后由程序写入设置 */
function ProposalCard({ p, onApply, onDiscard }: {
  p: Proposal & { state?: ProposalState }; onApply: (run: boolean) => Promise<void>; onDiscard: () => void;
}) {
  const done = p.state && p.state !== "pending";
  return (
    <div className={`proposal ${p.state || "pending"}`}>
      <div className="proposal-head">
        <Settings2 size={16} />
        <b className="grow">建议修改搜索条件</b>
        {p.state === "applied" && <span className="badge ok"><Check size={12} />已应用</span>}
        {p.state === "discarded" && <span className="badge">已放弃</span>}
        {p.state === "expired" && <span className="badge warn">已过期</span>}
      </div>
      {p.reason && <p className="proposal-reason">{p.reason}</p>}
      <table className="proposal-table">
        <thead><tr><th>项目</th><th>现在</th><th>改成</th></tr></thead>
        <tbody>
          {p.changes.map((c) => (
            <tr key={c.field}>
              <td className="faint">{c.label}</td>
              <td className="muted"><span className={c.field === "profile" ? "clamp" : ""}>{c.before}</span></td>
              <td><span className={c.field === "profile" ? "clamp" : ""}>{c.after}</span></td>
            </tr>
          ))}
          {p.enable_sources.length > 0 && <tr><td className="faint">打开信源</td><td className="muted">—</td><td>{p.enable_sources.join("、")}</td></tr>}
          {p.disable_sources.length > 0 && <tr><td className="faint">关闭信源</td><td className="muted">—</td><td>{p.disable_sources.join("、")}</td></tr>}
        </tbody>
      </table>
      {!done && (
        <div className="proposal-actions">
          <AsyncButton className="btn primary" icon={<Check />} onClick={() => onApply(true)}>应用并立即检索</AsyncButton>
          <AsyncButton className="btn" onClick={() => onApply(false)}>只应用</AsyncButton>
          <button className="btn ghost" onClick={onDiscard}>不要</button>
          <span className="faint" style={{ fontSize: 12 }}>点了才会生效；之后也能在「搜索条件」页改</span>
        </div>
      )}
    </div>
  );
}
