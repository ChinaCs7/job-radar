import { useEffect, useState } from "react";
import { Loader2, Save } from "lucide-react";
import { api, type Criteria as C } from "../../lib/api";
import { JOB_TYPE_LABEL } from "../../lib/format";
import { TagInput } from "../../components/ui";
import type { PageProps } from "../App";

export default function Criteria({ refresh, toast, overview, currentPlan }: PageProps) {
  const [c, setC] = useState<C | null>(null);
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [name,setName] = useState('');
  const [person,setPerson] = useState('');
  const [revision,setRevision] = useState(1);
  const [identity,setIdentity] = useState('');
  const [error,setError] = useState('');

  useEffect(() => { api.settings().then((s) => { setC(s.criteria); setSaved(JSON.stringify(s.criteria)); setName(s.plan?.name || '');setPerson(s.plan?.person || '');setRevision(s.plan?.revision || 1);setIdentity(JSON.stringify([s.plan?.name,s.plan?.person])); }).catch(e=>setError(e.message)); }, []);

  if (!c) return <div className="page"><div className="empty">{error?<span role="alert">{error}</span>:<Loader2 className="spin" />}</div></div>;
  const dirty = JSON.stringify(c) !== saved || JSON.stringify([name,person])!==identity;
  const set = <K extends keyof C>(k: K, v: C[K]) => setC({ ...c, [k]: v });
  const noRegion = !c.regions.domestic && !c.regions.overseas && !c.regions.remote;

  const save = async (andRun: boolean) => {
    setBusy(true);
    try {
      const s = await api.updatePlan(currentPlan,{criteria:c,name,person,revision});
      setSaved(JSON.stringify(s.criteria));
      setRevision(s.revision);setIdentity(JSON.stringify([s.name,s.person]));
      if (andRun) { const r=await api.runNow(undefined,currentPlan); toast(r.started.length?`已保存，启动 ${r.started.length} 个信源`:'已保存；没有启动新任务，请检查信源与预算'); } else toast("已保存，候选将按新条件重新评估");
      refresh();
    } catch (e) { toast((e as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>{overview?.plan?.name || "方案条件"}</h1>
          <p>只修改当前方案。保存后按新条件重新评估已有候选，其他方案保持独立。</p>
        </div>
      </div>

      <div className="panel panel-pad">
        <div className="field"><label htmlFor="plan-name">方案名称</label><input id="plan-name" className="input" value={name} onChange={e=>setName(e.target.value)} maxLength={100}/><span className="hint">建议包含方向、城市或工作类型，便于区分。</span></div>
        <div className="field"><label htmlFor="plan-person">求职者</label><input id="plan-person" className="input" value={person} onChange={e=>setPerson(e.target.value)} maxLength={60}/><span className="hint">每个方案的个人简介独立保存。</span></div>
        <div className="field">
          <label htmlFor="kw">关键词</label>
          <TagInput id="kw" value={c.keywords} onChange={(v) => set("keywords", v)} placeholder="例如：AI Agent、大模型应用、LLM" />
          <span className="hint">关键词按每轮访问预算轮转，不会一直只搜前几个。英文平台（LinkedIn、RemoteOK、HN）也用这些词，建议中英文各放一两个。关键词越多，检索越慢。</span>
        </div>
        <div className="field">
          <label htmlFor="city">城市</label>
          <TagInput id="city" value={c.cities} onChange={(v) => set("cities", v)} placeholder="例如：厦门、上海；不填表示不限" />
          <span className="hint">只对国内的非远程岗位生效。Boss 直聘会按这些城市分别搜。</span>
        </div>
        <div className="field">
          <label htmlFor="sal">月薪下限</label>
          <div className="row">
            <input id="sal" className="input" style={{ width: 120 }} type="number" min={0} step={1}
              value={c.salary_min_k || ""} placeholder="不限" onChange={(e) => set("salary_min_k", Number(e.target.value) || 0)} />
            <span className="muted">K / 月</span>
          </div>
          <span className="hint">按薪资区间的下限判断，留 20% 余量；没写薪资的岗位不会被过滤掉。海外岗位按美元粗略折算。</span>
        </div>
        <div className="field">
          <label>地区</label>
          <div className="row" style={{ gap: 20, flexWrap: "wrap" }}>
            {([["domestic", "国内"], ["overseas", "海外"], ["remote", "远程（国内外都算）"]] as const).map(([k, l]) => (
              <label className="check" key={k}>
                <input type="checkbox" checked={c.regions[k]} onChange={(e) => set("regions", { ...c.regions, [k]: e.target.checked })} />{l}
              </label>
            ))}
          </div>
          <span className="hint" style={noRegion ? { color: "var(--danger)" } : undefined}>
            {noRegion ? "至少选一个地区，否则什么都搜不到。" : "关掉海外以后，海外平台的岗位只保留远程的；海外和远程都关掉，海外信源就不会再跑。结果页里还能再按地区筛。"}
          </span>
        </div>
        <div className="field">
          <label htmlFor="age">发布时间</label>
          <select id="age" className="select" style={{ width: 200 }} value={c.max_age_days ?? 30}
            onChange={(e) => set("max_age_days", Number(e.target.value))}>
            {[[3, "最近 3 天"], [7, "最近 7 天"], [14, "最近 2 周"], [30, "最近 1 个月"], [60, "最近 2 个月"], [0, "不限"]].map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
          <span className="hint">超过这个时间发布的岗位不要。未知日期会标为待核验，不能作为已确认的新岗位推荐。</span>
        </div>
        <div className="field">
          <label>岗位类型</label>
          <div className="row" style={{ gap: 20, flexWrap: "wrap" }}>
            {Object.entries(JOB_TYPE_LABEL).map(([k, l]) => (
              <label className="check" key={k}>
                <input type="checkbox" checked={c.job_types.includes(k)}
                  onChange={(e) => set("job_types", e.target.checked ? [...c.job_types, k] : c.job_types.filter((x) => x !== k))} />{l}
              </label>
            ))}
          </div>
          <span className="hint">看不出类型的岗位会保留。</span>
        </div>
        <div className="field">
          <label htmlFor="ex">排除词</label>
          <TagInput id="ex" value={c.exclude} onChange={(v) => set("exclude", v)} placeholder="例如：外包、销售、驻场" />
          <span className="hint">岗位名或公司名里出现这些词会标记为已过滤，保留原因供检查。</span>
        </div>
        <div className="field">
          <label htmlFor="pf">关于你</label>
          <textarea id="pf" className="textarea" rows={4} value={c.profile} onChange={(e) => set("profile", e.target.value)}
            placeholder="几句话介绍经历和想找的方向，例如：5 年 AI 应用开发，做过 Dify 工作流和 AIGC 平台，想做 Agent 方向，人在厦门，可以远程。" />
          <span className="hint">给 AI 打匹配分用，只存在本机，只会随岗位一起发给 DeepSeek。不填也能用，只是打分会粗一些。</span>
        </div>
      </div>

      <div className="savebar">
        <button className="btn primary" disabled={!dirty || busy || noRegion || !name.trim() || !person.trim()} onClick={() => save(false)}>
          {busy ? <Loader2 className="spin" /> : <Save />}保存
        </button>
        <button className="btn" disabled={busy || noRegion || !c.keywords.length} onClick={() => save(true)}>保存并立即检索</button>
        <span className="faint" style={{ fontSize: 13 }}>{dirty ? "有未保存的修改" : "已保存"}</span>
      </div>
    </div>
  );
}
