import { useEffect, useState } from "react";
import { CheckCircle2, ExternalLink, Loader2, ShieldCheck, XCircle } from "lucide-react";
import { api, openExternal, type BrowserPlatform, type Settings } from "../../lib/api";
import { AsyncButton, STATE_META, Switch } from "../../components/ui";
import type { PageProps } from "../App";

type Result = { ok: boolean; message: string } | null;

export default function Accounts({ overview, refresh, toast }: PageProps) {
  const [s, setS] = useState<Settings | null>(null);
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [llmRes, setLlmRes] = useState<Result>(null);
  const [testing, setTesting] = useState(false);
  const [browser, setBrowser] = useState<{ running: boolean; browser: string | null } | null>(null);
  const [boss, setBoss] = useState<{ state: string; message: string } | null>(null);
  const [checking, setChecking] = useState(false);

  const load = () => api.settings().then((x) => { setS(x); setModel(x.llm.model); });
  useEffect(() => {
    load();
    const poll = () => api.browserStatus().then(setBrowser).catch(() => setBrowser(null));
    poll();
    const t = window.setInterval(poll, 4000);
    return () => window.clearInterval(t);
  }, []);

  const saveKey = async () => {
    setTesting(true); setLlmRes(null);
    try {
      const r = await api.testLlm({ api_key: key, model });
      setLlmRes(r);
      if (r.ok) {
        await api.saveSettings({ llm: { api_key: key, model } });
        setKey(""); await load(); refresh(); toast("已保存 DeepSeek key");
      }
    } catch (e) { setLlmRes({ ok: false, message: (e as Error).message }); }
    finally { setTesting(false); }
  };

  const clearKey = async () => { await api.saveSettings({ llm: { clear_key: true } }); await load(); refresh(); toast("已删除 key"); };
  const setEnrich = async (v: boolean) => { await api.saveSettings({ llm: { enrich: v } }); load(); };

  const openLogin = async () => {
    try { await api.openBrowser("boss"); toast("已打开专用浏览器，请在里面登录 Boss 直聘"); }
    catch (e) { toast((e as Error).message); }
  };
  const check = async () => {
    setChecking(true); setBoss(null);
    try { const r = await api.checkLogin("boss"); setBoss(r); refresh(); }
    catch (e) { setBoss({ state: "error", message: (e as Error).message }); }
    finally { setChecking(false); }
  };

  const bossSrc = overview?.sources.find((x) => x.id === "boss");
  const [platforms, setPlatforms] = useState<BrowserPlatform[]>([]);
  const loadPlatforms = () => api.browserPlatforms().then(setPlatforms).catch(() => { });
  useEffect(() => { loadPlatforms(); }, [overview]);
  const openPlatform = async (p: BrowserPlatform) => {
    try { await api.openBrowser(p.id); toast(`已在专用浏览器打开 ${p.name}`); }
    catch (e) { toast((e as Error).message); }
  };
  const enablePlatform = async (p: BrowserPlatform, v: boolean) => {
    await api.saveSettings({ sources: { [p.id]: { enabled: v, ...(v ? { paused: "", paused_reason: "" } : {}) } } });
    refresh(); loadPlatforms();
  };
  const resumePlatform = async (p: BrowserPlatform) => { await api.resume(p.id); toast(`${p.name} 已恢复`); refresh(); loadPlatforms(); };

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>账号与密钥</h1>
          <p>账号登录态和 key 都只保存在这台电脑上，不会上传到任何地方。</p>
        </div>
      </div>

      <div className="panel">
        <section className="acct">
          <div className="acct-head">
            <span className="logo">AI</span>
            <div className="grow"><h2>DeepSeek</h2><span className="faint" style={{ fontSize: 13 }}>AI 整理、匹配打分、每日总结、AI 助手、全网搜索都用它</span></div>
            {s?.llm.has_key ? <span className="badge ok"><CheckCircle2 size={12} />已配置 {s.llm.key_hint}</span> : <span className="badge">未配置</span>}
          </div>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <input className="input" style={{ maxWidth: 380 }} type="password" autoComplete="off" value={key}
              placeholder={s?.llm.has_key ? "输入新 key 可替换" : "sk-…"} onChange={(e) => setKey(e.target.value)} aria-label="DeepSeek API key" />
            <input className="input" style={{ width: 170 }} value={model} onChange={(e) => setModel(e.target.value)} aria-label="模型" title="模型名" />
            <button className="btn primary" disabled={!key || testing} onClick={saveKey}>
              {testing && <Loader2 className="spin" />}测试并保存
            </button>
            {s?.llm.has_key && <button className="btn ghost danger" onClick={clearKey}>删除 key</button>}
          </div>
          {llmRes && (
            <div className={`row ${llmRes.ok ? "" : "err"}`} style={{ fontSize: 13, color: llmRes.ok ? "var(--ok)" : "var(--danger)" }}>
              {llmRes.ok ? <CheckCircle2 size={16} /> : <XCircle size={16} />}{llmRes.ok ? `连接正常：${llmRes.message}` : llmRes.message}
            </div>
          )}
          <div className="row" style={{ fontSize: 13 }}>
            <Switch label="新岗位自动交给 AI 整理" checked={!!s?.llm.enrich} onChange={setEnrich} disabled={!s?.llm.has_key} />
            <span className="grow">新岗位自动交给 AI 整理字段、判断是不是岗位、打匹配分</span>
            <button className="btn ghost sm" onClick={() => openExternal("https://platform.deepseek.com/api_keys")}>去申请 key<ExternalLink /></button>
          </div>
        </section>

        <section className="acct">
          <div className="acct-head">
            <span className="logo">B</span>
            <div className="grow"><h2>Boss 直聘</h2><span className="faint" style={{ fontSize: 13 }}>用一个专用浏览器登录你自己的账号，和你平时用的 Chrome 分开</span></div>
            {bossSrc?.state === "paused" ? <span className="badge danger">已暂停</span> :
              boss?.state === "ok" ? <span className="badge ok"><CheckCircle2 size={12} />已登录</span> : null}
          </div>
          <ol className="steps">
            <li>点「打开登录窗口」，会弹出一个新的 Chrome 窗口。</li>
            <li>在里面扫码或用手机号登录 Boss 直聘。如果出现滑块验证，手动完成。</li>
            <li>回到这里点「检测登录状态」。显示已登录后，这个窗口可以最小化，但不要关掉。</li>
          </ol>
          <div className="row" style={{ flexWrap: "wrap" }}>
            <AsyncButton className="btn primary" icon={<ExternalLink />} onClick={openLogin}>打开登录窗口</AsyncButton>
            <button className="btn" onClick={check} disabled={checking || !browser?.running}>
              {checking ? <Loader2 className="spin" /> : <ShieldCheck />}检测登录状态
            </button>
            <span className="faint" style={{ fontSize: 13 }}>
              专用浏览器：{browser ? (browser.running ? "已打开" : "未打开") : "—"}{browser && !browser.browser ? "（没找到 Chrome，请先安装）" : ""}
            </span>
          </div>
          {boss && (
            <div className="row" style={{ fontSize: 13, color: boss.state === "ok" ? "var(--ok)" : "var(--danger)" }}>
              {boss.state === "ok" ? <CheckCircle2 size={16} /> : <XCircle size={16} />}{boss.message}
            </div>
          )}
          <div className="notice" style={{ fontSize: 13 }}>
            <span className="muted">Boss 对频繁访问很敏感：建议间隔 2 小时以上、夜间暂停、关键词和城市别太多。如果被要求验证，求职雷达会自动暂停 Boss，等你在专用浏览器里完成验证后，到「信源与频率」点「恢复」。</span>
          </div>
        </section>

        <section className="acct">
          <div className="acct-head">
            <span className="logo">网</span>
            <div className="grow"><h2>其他平台的登录与验证</h2>
              <span className="faint" style={{ fontSize: 13 }}>都在同一个专用浏览器里操作：点「打开」，登录或完成验证，然后打开右边的开关（已暂停的点「恢复」）</span></div>
          </div>
          <div className="plat-list">
            {platforms.filter((p) => p.id !== "boss").map((p) => {
              const m = STATE_META[p.state];
              const need = p.needs_login ? "需要登录" : p.verify_once ? "首次需要验证" : "不用登录";
              return (
                <div className="plat" key={p.id}>
                  <div className="grow">
                    <div className="row" style={{ gap: 8 }}>
                      <b style={{ fontWeight: 500 }}>{p.name}</b>
                      <span className={`badge ${p.needs_login || p.verify_once ? "warn" : ""}`}>{need}</span>
                      <span className="faint" style={{ fontSize: 12 }}>{p.group}</span>
                    </div>
                    <div className="row" style={{ gap: 6, fontSize: 12, marginTop: 2 }}>
                      <i className={`dot ${m.dot}`} /><span className="muted">{m.label}</span>
                      {(p.paused_reason || p.last_error) && <span className="ellipsis" style={{ color: "var(--danger)", maxWidth: 520 }}>{p.paused_reason || p.last_error}</span>}
                    </div>
                  </div>
                  <AsyncButton className="btn sm" icon={<ExternalLink />} onClick={() => openPlatform(p)}>打开</AsyncButton>
                  {p.state === "paused" && <AsyncButton className="btn sm" onClick={() => resumePlatform(p)}>恢复</AsyncButton>}
                  <Switch label={`启用 ${p.name}`} checked={!!p.enabled} onChange={(v) => enablePlatform(p, v)} />
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
