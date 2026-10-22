import { useCallback, useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Ban, Check, Loader2, Monitor, Moon, Star, Sun, X } from "lucide-react";
import type { Job, JobStatus, Source } from "../lib/api";
import { scoreClass } from "../lib/format";
import type { Theme } from "../lib/theme";

export function Switch({ checked, onChange, disabled, label }: {
  checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label: string;
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} className="switch"
      disabled={disabled} onClick={() => onChange(!checked)} />
  );
}

/** 标签输入：回车或逗号添加，退格删除最后一个 */
export function TagInput({ value, onChange, placeholder, id }: {
  value: string[]; onChange: (v: string[]) => void; placeholder?: string; id?: string;
}) {
  const [draft, setDraft] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  const add = (raw: string) => {
    const items = raw.split(/[,，、\n]/).map((s) => s.trim()).filter(Boolean);
    const next = [...value];
    for (const it of items) if (!next.includes(it)) next.push(it);
    if (next.length !== value.length) onChange(next);
    setDraft("");
  };
  return (
    <div className="tags" onClick={() => ref.current?.focus()}>
      {value.map((t) => (
        <span className="tag" key={t}>
          {t}
          <button type="button" aria-label={`删除 ${t}`} onClick={(e) => { e.stopPropagation(); onChange(value.filter((x) => x !== t)); }}>
            <X size={12} />
          </button>
        </span>
      ))}
      <input id={id} ref={ref} value={draft} placeholder={value.length ? "" : placeholder}
        onChange={(e) => (/[,，、]/.test(e.target.value) ? add(e.target.value) : setDraft(e.target.value))}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); add(draft); }
          else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
        }}
        onBlur={() => draft && add(draft)} />
    </div>
  );
}

export function Seg<T extends string>({ value, options, onChange, label }: {
  value: T; options: { value: T; label: ReactNode; title?: string }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" title={o.title} aria-pressed={o.value === value} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export function ThemeToggle({ theme, setTheme }: { theme: Theme; setTheme: (t: Theme) => void }) {
  return (
    <Seg label="主题" value={theme} onChange={setTheme} options={[
      { value: "light", title: "亮色", label: <span className="row" style={{ gap: 4 }}><Sun size={14} /><span className="t-label">亮色</span></span> },
      { value: "dark", title: "暗色", label: <span className="row" style={{ gap: 4 }}><Moon size={14} /><span className="t-label">暗色</span></span> },
      { value: "system", title: "跟随系统", label: <span className="row" style={{ gap: 4 }}><Monitor size={14} /><span className="t-label">系统</span></span> },
    ]} />
  );
}

export function Score({ value }: { value: number | null }) {
  return <span className={`score ${scoreClass(value)}`} title="匹配分（0-100）">{value ?? "—"}</span>;
}

export const STATE_META: Record<Source["state"], { dot: string; label: string }> = {
  ok: { dot: "ok", label: "正常" },
  idle: { dot: "", label: "等待首次检索" },
  running: { dot: "run", label: "检索中" },
  queued: { dot: "wait", label: "排队中" },
  paused: { dot: "danger", label: "已暂停" },
  error: { dot: "warn", label: "上次失败" },
  disabled: { dot: "", label: "已关闭" },
};

/** 点了以后一直转圈直到操作完成，期间不能重复点。所有会发请求的按钮都用它。 */
export function AsyncButton({ onClick, children, icon, className = "btn", disabled, ...rest }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onClick"> & {
  onClick: () => Promise<unknown> | unknown; icon?: ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  return (
    <button {...rest} className={className} disabled={disabled || busy} aria-busy={busy}
      onClick={async () => {
        setBusy(true);
        try { await onClick(); } finally { if (alive.current) setBusy(false); }
      }}>
      {busy ? <Loader2 className="spin" /> : icon}{children}
    </button>
  );
}

export function useToast(): [ReactNode, (msg: string) => void] {
  const [msg, setMsg] = useState("");
  const timer = useRef<number>(0);
  const show = useCallback((m: string) => {
    setMsg(m);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMsg(""), 2400);
  }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return [msg ? <div className="toast" role="status">{msg}</div> : null, show];
}

/** 岗位的三个状态操作：收藏、已投、不合适。再点一次取消。 */
export function JobActions({ job, onChange, size = "sm" }: {
  job: Job; onChange: (status: JobStatus) => void; size?: "sm" | "md";
}) {
  const cls = `btn ghost icon ${size === "sm" ? "sm" : ""}`;
  const toggle = (s: JobStatus) => onChange(job.status === s ? "seen" : s);   // 父组件先改界面再发请求，点了立刻有反应
  return (
    <span className="row" style={{ gap: 2 }}>
      <button className={cls} title={job.status === "starred" ? "取消收藏" : "收藏"} aria-pressed={job.status === "starred"}
        onClick={() => toggle("starred")} style={job.status === "starred" ? { color: "var(--warn)" } : undefined}>
        <Star fill={job.status === "starred" ? "currentColor" : "none"} />
      </button>
      <button className={cls} title={job.status === "applied" ? "取消已投" : "标记已投"} aria-pressed={job.status === "applied"}
        onClick={() => toggle("applied")} style={job.status === "applied" ? { color: "var(--ok)" } : undefined}>
        <Check />
      </button>
      <button className={cls} title={job.status === "dismissed" ? "恢复" : "不合适，隐藏"} onClick={() => toggle("dismissed")}>
        <Ban />
      </button>
    </span>
  );
}
