import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowUp, Check, FileText, Info, Loader2, Paperclip, Search, Settings2, Sparkles, Trash2, X } from "lucide-react";
import { openJob } from "./Jobs";
import { api, type Proposal } from "../../lib/api";
import { today } from "../../lib/format";
import { AsyncButton } from "../../components/ui";
import type { PageProps } from "../App";

interface Attachment { name: string; text: string; chars: number; masked: number }
type ProposalState = "pending" | "applied" | "discarded" | "expired";
interface Msg {
  role: "user" | "assistant";
  content: string;
  steps?: { tool: string; args: Record<string, unknown>; count: number | null }[];
  error?: boolean;
  attachment?: Attachment;
  proposals?: (Proposal & { state?: ProposalState })[];
}

const KEY = "jr-chat";
const SUGGEST = [
  "列出我当前的全部求职方案",
  "根据我的简历，创建适合我的求职方案",
  "今天最适合我的 3 个岗位是哪些？",
  "收藏的岗位帮我比较一下",
  "各个信源最近表现怎么样？",
];
const TOOL_LABEL: Record<string, string> = {
  list_plans: "列出方案", get_plan: "读取方案", create_plan: "创建方案", update_plan: "编辑方案", manage_plan: "管理方案", run_plan: "启动方案检索", cancel_plan: "取消任务", plan_progress: "检查进度", search_plan_jobs: "查询方案岗位",
  search_jobs: "查岗位", get_job: "看详情", get_stats: "看统计", get_settings: "看当前设置", propose_settings: "提出修改方案",
};

function stepText(s: NonNullable<Msg["steps"]>[number]): string {
  const l = TOOL_LABEL[s.tool] || s.tool;
  if (s.tool === "get_job") return `${l} #${s.args.serial}`;
  if (s.tool === "search_jobs") return `${l}${s.args.q ? `「${s.args.q}」` : ""}（${s.count ?? 0} 条）`;
  return l;
}

/** 发给模型的内容：附件（简历）作为一段带标记的文字跟在消息后面 */
function toWire(m: Msg) {
  const att = m.attachment ? `\n\n<附件 名称="${m.attachment.name}">\n${m.attachment.text}\n</附件>` : "";
  return { role: m.role, content: m.content + att };
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

export default function Assistant({ overview, go, toast, refresh }: PageProps) {
  const [msgs, setMsgs] = useState<Msg[]>(() => { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; } });
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<"" | "ask" | "summary" | "upload">("");
  const [att, setAtt] = useState<Attachment | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify(msgs.slice(-40))); } catch { /* 忽略 */ }
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

  const openRef = async (n: number) => {
    try { const j = await api.jobBySerial(n); await openJob(j.url, toast); }
    catch (e) { toast((e as Error).message); }
  };

  const ask = async (text: string) => {
    const q = text.trim() || (att ? "这是我的简历，帮我看看适合找什么样的岗位，并帮我设置搜索条件" : "");
    if (!q || busy) return;
    const next: Msg[] = [...msgs, { role: "user", content: q, attachment: att ?? undefined }];
    setMsgs(next); setDraft(""); setAtt(null); setBusy("ask");
    try {
      const r = await api.assistant(next.filter((m) => !m.error).map(toWire));
      refresh();
      setMsgs([...next, { role: "assistant", content: r.reply, steps: r.steps, proposals: r.proposals?.map((p) => ({ ...p, state: "pending" })) }]);
    } catch (e) {
      setMsgs([...next, { role: "assistant", content: (e as Error).message, error: true }]);
    } finally { setBusy(""); }
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
        <Sparkles /><b>AI 助手需要 DeepSeek key</b><span>填好以后，可以让它帮你挑岗位、按简历设置搜索条件、写总结。</span>
        <button className="btn primary" onClick={() => go("accounts")}>去填写</button>
      </div></div>
    );
  }

  return (
    <div className="chat">
      <div className="chat-head">
        <div className="page-head">
          <div className="grow"><h1>指挥助手</h1>
            <p>描述目标或上传简历，让助手创建、编辑、归档方案，启动检索并检查进度。</p></div>
          <button className="btn" onClick={summary} disabled={!!busy} title="总结今天值得看的岗位；今天没有就总结最近 7 天">
            {busy === "summary" ? <Loader2 className="spin" /> : <Sparkles />}AI 总结</button>
          {msgs.length > 0 && <button className="btn ghost icon" title="清空对话" aria-label="清空对话" onClick={() => setMsgs([])}><Trash2 /></button>}
        </div>
      </div>
      <div className={`chat-log ${msgs.length === 0 && !busy ? "is-empty" : ""}`}>
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
                  {m.steps.map((s, j) => <span key={j}>{s.tool === "summary" ? `汇总 ${s.count} 条` : stepText(s)}</span>)}
                </div>
              )}
              {m.attachment && <div className="att-chip"><FileText size={14} />{m.attachment.name}<span className="faint">{m.attachment.chars} 字</span></div>}
              {m.error ? (
                <div className="notice" style={{ fontSize: 13 }}><Info className="faint" /><span className="muted">{m.content}</span></div>
              ) : m.content ? (
                <div className="bubble">{m.role === "assistant" ? render(m.content, openRef) : m.content}</div>
              ) : null}
              {m.proposals?.map((p) => (
                <ProposalCard key={p.proposal_id} p={p} onApply={(run) => applyProposal(p, run)} onDiscard={() => discardProposal(p)} />
              ))}
            </div>
          ))}
          {busy === "ask" && <div className="msg assistant"><div className="steps-line"><Loader2 size={13} className="spin" />正在思考、查数据…</div></div>}
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
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); ask(draft); } }} />
            <button className="btn primary icon" aria-label="发送" disabled={(!draft.trim() && !att) || !!busy} onClick={() => ask(draft)}><ArrowUp /></button>
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
