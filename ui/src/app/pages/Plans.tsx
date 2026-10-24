import { useEffect, useMemo, useState } from 'react';
import { Archive, ArrowRight, Copy, FolderOpen, Loader2, Plus, RotateCcw, Search, Sparkles, Trash2, X } from 'lucide-react';
import { api, type Plan } from '../../lib/api';
import type { PageProps } from '../App';

const split = (s: string) => [...new Set(s.split(/[,，、\n]/).map(x => x.trim()).filter(Boolean))];

export default function Plans({ go, toast, refresh, choosePlan, currentPlan, planList }: PageProps) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [person, setPerson] = useState('全部求职者');
  const [state, setState] = useState('active');
  const [creating, setCreating] = useState(false);
  const [who, setWho] = useState('我');
  const [directions, setDirections] = useState('');
  const [cities, setCities] = useState('');
  const [type, setType] = useState('fulltime');
  const [busy, setBusy] = useState('');
  const [deleting, setDeleting] = useState('');
  const [q, setQ] = useState('');
  const load = () => api.plans(true).then(p => { setPlans(p); setLoaded(true); setError(''); }).catch(e => { setError(e.message); setLoaded(true); });
  useEffect(() => { load(); }, []);
  useEffect(() => { setPlans(planList); }, [planList]);
  const people = [...new Set(plans.map(p => p.person))];
  const shown = plans.filter(p => p.state === state && (person === '全部求职者' || p.person === person) && `${p.name} ${p.person}`.includes(q));
  const combinations = useMemo(() => split(directions).flatMap(d => (split(cities).length ? split(cities) : ['不限城市']).map(c => `${d} · ${c}`)), [directions, cities]);
  const action = async (id: string, fn: () => Promise<unknown>, message: string) => {
    setBusy(id);
    try { await fn(); await load(); refresh(); setDeleting(''); toast(message); }
    catch(e) { toast((e as Error).message); }
    finally { setBusy(''); }
  };
  const create = async () => {
    setBusy('create');
    try {
      const created = await api.batchPlans({person:who.trim() || '我',directions:split(directions),cities:split(cities),
        criteria:{job_types:[type],regions:{domestic:true,overseas:false,remote:false},salary_min_k:0,max_age_days:30}});
      await load(); setCreating(false); setState('active'); setPerson('全部求职者');
      toast(`已创建 ${created.length} 个独立方案；可继续编辑关键词、薪资和简历`); refresh();
      if(created.length === 1) { choosePlan(created[0].id); go('criteria'); }
    } catch(e) { toast((e as Error).message); }
    finally { setBusy(''); }
  };
  return <div className="page plans-page">
    <div className="page-head"><div className="grow"><h1>求职方案</h1><p>一个目标，一份方案。岗位、匹配结论和投递进度分别保存。</p></div>
      <button className="btn" onClick={() => go('assistant')}><Sparkles/>让助手整理</button>
      <button className="btn primary" onClick={() => setCreating(true)}><Plus/>创建方案</button></div>
    {creating && <section className="plan-compose" aria-label="创建搜索方案">
      <div className="row"><h2 className="grow">把求职方向组合成方案</h2><button className="btn ghost icon" aria-label="关闭创建" disabled={!!busy} onClick={() => setCreating(false)}><X/></button></div>
      <div className="plan-form-grid">
        <label>求职者<input className="input" value={who} onChange={e => setWho(e.target.value)} placeholder="例如：小红"/></label>
        <label>工作类型<select className="select" value={type} onChange={e => setType(e.target.value)}><option value="fulltime">全职</option><option value="parttime">兼职</option><option value="contract">合同 / 外包</option><option value="intern">实习</option></select></label>
        <label>求职方向<input className="input" value={directions} onChange={e => setDirections(e.target.value)} placeholder="例如：销售、策划"/><small>用顿号或逗号分开，每个方向独立管理。</small></label>
        <label>城市<input className="input" value={cities} onChange={e => setCities(e.target.value)} placeholder="例如：上海、厦门"/><small>留空表示不限城市，创建后可设置远程。</small></label>
      </div>
      <div className="plan-preview"><b>{combinations.length ? `将创建 ${combinations.length} 个方案` : '填写方向后，这里会预览组合'}</b>
        <div className="row plan-chips">{combinations.slice(0,20).map(n => <span className="badge" key={n}>{n}</span>)}</div>
        <span className="muted">新方案从空结果开始。不会自动访问招聘网站；先检查条件，再开始检索。</span></div>
      <div className="row"><button className="btn primary" disabled={!!busy || !who.trim() || !combinations.length || combinations.length>20} onClick={create}>{busy==='create'?<Loader2 className="spin"/>:<Plus/>}创建 {combinations.length || ''} 个方案</button>
        <button className="btn" disabled={!!busy} onClick={() => setCreating(false)}>取消</button>{combinations.length>20 && <span className="danger">单次最多 20 个方案</span>}</div>
    </section>}
    <div className="plans-toolbar"><label className="plans-person">求职者<select className="select" value={person} onChange={e => setPerson(e.target.value)}><option>全部求职者</option>{people.map(p => <option key={p}>{p}</option>)}</select></label>
      <div className="seg" role="group" aria-label="方案状态">{[['active','使用中'],['archived','已归档'],['deleted','回收区']].map(([k,l]) => <button key={k} aria-pressed={state===k} onClick={() => setState(k)}>{l}</button>)}</div>
      <div className="search grow"><Search/><input className="input" aria-label="搜索方案" placeholder="搜索方案或求职者" value={q} onChange={e=>setQ(e.target.value)}/></div></div>
    {error && <div className="notice"><span className="grow">{error}</span><button className="btn" onClick={load}>重新加载</button></div>}
    {!loaded ? <div className="empty"><Loader2 className="spin"/><span>正在读取方案…</span></div> : shown.length===0 ?
      <div className="empty"><FolderOpen/><b>{q || person!=='全部求职者'?'没有匹配的方案':state==='active'?'这里还没有方案':state==='deleted'?'回收区是空的':'还没有归档方案'}</b>
        {q || person!=='全部求职者' ? <><span>试试其他关键词，或清除搜索和求职者筛选。</span><button className="btn" onClick={()=>{setQ('');setPerson('全部求职者');}}>清除筛选</button></> : <span>{state==='active'?'创建一个方向，或让助手根据简历帮你整理。':'历史结果会随方案保留，恢复后可以继续使用。'}</span>}</div> :
      <div className="plans-list">{shown.map(p => <article key={p.id} className={`plan-row ${p.id===currentPlan?'selected':''}`}>
        <div className="plan-row-main"><div className="row"><span className="badge">{p.person}</span>{p.id===currentPlan && <span className="badge blue">当前方案</span>}<span className="faint">{p.running?'自动检索已开启':'手动检索'}</span></div>
          <button className="plan-title" disabled={p.state==='deleted'} onClick={() => {choosePlan(p.id);go('jobs');}}>{p.name}<ArrowRight size={15}/></button>
          <p>{p.criteria.keywords.join('、') || '待填写关键词'}<span className="faint"> · {p.criteria.cities.join('、') || '不限城市'} · {p.criteria.job_types.map(t => ({fulltime:'全职',parttime:'兼职',contract:'合同 / 外包',intern:'实习'}[t] || t)).join('、')}</span></p>
          <div className="plan-counts"><span>{p.candidates || 0} 条候选</span><span>{p.recommended || 0} 条推荐</span><span>{p.pending || 0} 条待评估</span></div></div>
        <div className="plan-row-actions">{p.state!=='deleted' && <><button className="btn" disabled={!!busy} onClick={() => {choosePlan(p.id);go('criteria');}}>编辑方案</button>
          {p.state==='active' && <button className="btn ghost" disabled={!!busy || !p.candidates} onClick={()=>action(p.id,()=>api.reevaluate(p.id),'已加入当前方案的 AI 评估队列，需要已配置模型密钥')}><RotateCcw/>重新评估</button>}
          <button className="btn ghost" disabled={!!busy} onClick={() => action(p.id,()=>api.copyPlan(p.id),'已复制条件，新方案从空结果开始')}><Copy/>复制</button></>}
          <button className="btn ghost" disabled={!!busy} onClick={() => action(p.id,()=>api.updatePlan(p.id,{state:p.state==='active'?'archived':'active',running:false}),p.state==='active'?'已归档，历史结果保留':'已恢复方案')}>
            {p.state==='active'?<Archive/>:<RotateCcw/>}{p.state==='active'?'归档':'恢复'}</button>
          {p.state!=='deleted' && <button className="btn ghost icon" aria-label={`删除 ${p.name}`} disabled={!!busy} onClick={()=>setDeleting(p.id)}><Trash2/></button>}
          {busy===p.id && <Loader2 size={16} className="spin"/>}</div>
        {!p.evaluation_enabled && !!p.pending && <div className="muted plan-migration-note">历史岗位已保留。旧评分不再沿用；点击“重新评估”后才会调用 AI，不会在迁移时自动消耗额度。</div>}
        {deleting===p.id && <div className="plan-delete"><span>将“{p.name}”移入回收区？任务会停止，岗位结果保留。</span><button className="btn danger" disabled={!!busy} onClick={()=>action(p.id,()=>api.deletePlan(p.id),'已移入回收区，可随时恢复')}>移入回收区</button><button className="btn" onClick={()=>setDeleting('')}>取消</button></div>}
      </article>)}</div>}
    <div className="plans-explainer"><b>方案之间如何关联？</b><p>同一个岗位可以属于多个方案。原始岗位信息复用；是否适合、收藏和投递状态按方案分别记录。修改条件后会重新评估已有候选。</p></div>
  </div>;
}
