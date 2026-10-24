"""Collect once, preserve candidates, assess independently for each plan."""
from __future__ import annotations
import asyncio
import hashlib
import json
import httpx
from dataclasses import asdict
from datetime import datetime, timedelta
from . import db, llm, plans
from .config import load_settings
from .collectors import REGISTRY, CollectorError
from .models import Job, parse_salary_min_k
from .plan_context import current_plan

_locks: dict[str,asyncio.Lock] = {}
PROGRESS: dict[tuple[str,str],dict] = {}


def progress(source: str, stage: str, message: str):
    PROGRESS[(current_plan.get() or 'legacy',source)]={'stage':stage,'message':message,'at':db.now()}


def quality(row: dict) -> list[str]:
    from .pipeline import age_days
    missing=[]
    if age_days(row.get('published_at') or '') is None: missing.append('发布时间待核验')
    if len(row.get('description') or '')<180: missing.append('岗位正文不完整')
    if not row.get('company'): missing.append('公司未明确')
    return missing


async def run_source(source_id: str) -> dict:
    from .pipeline import passes, age_days, _REMOTE
    pid=current_plan.get() or 'legacy'
    s=load_settings(); p=plans.get(pid); revision=p['revision']
    crit=s['criteria']; cfg=s['sources'].get(source_id,{})
    run_id=db.run_start(source_id)
    warning=None
    progress(source_id,'queued','等待该平台的采集任务与浏览器使用权')
    db.log('info',f'开始检索 {REGISTRY[source_id].info.name} · {p["name"]}',source_id)
    try:
        async with _locks.setdefault(source_id,asyncio.Lock()):
            if plans.get(pid)['state']!='active': raise CollectorError('config','方案已归档，已停止本次任务')
            # Reuse a recent identical search across plans; personal profile and evaluation preferences are excluded.
            search={k:crit[k] for k in ('keywords','cities','regions','job_types')}
            key=hashlib.sha256(json.dumps([source_id,search,cfg],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            cached=db.conn().execute('SELECT * FROM collector_cache WHERE key=? AND at>?',
                (key,(datetime.now()-timedelta(minutes=15)).isoformat())).fetchone()
            if cached:
                jobs=[Job(**j) for j in json.loads(cached['jobs'])]
                progress(source_id,'cache','复用 15 分钟内相同条件的采集，按当前方案重新筛选')
            else:
                progress(source_id,'loading','正在访问平台；若需登录或验证会暂停')
                try:
                    jobs=await asyncio.wait_for(REGISTRY[source_id].collect(crit,cfg,s),timeout=600)
                except CollectorError as e:
                    if not e.partial: raise
                    jobs=e.partial
                    warning=e
                if not warning:
                    db.conn().execute('INSERT OR REPLACE INTO collector_cache VALUES(?,?,?)',
                        (key,db.now(),json.dumps([asdict(j) for j in jobs],ensure_ascii=False,default=str)))
                    db.conn().commit()
        progress(source_id,'saving','保存候选并记录筛选理由')
        # A changed plan cannot silently consume results produced by old criteria.
        latest=plans.get(pid)
        if latest['revision']!=revision or latest['state']!='active':
            raise CollectorError('config','检索期间方案已修改或归档；本轮结果未归入方案，请重新检索')
        jobs=list({j.id:j for j in jobs}.values())
        for j in jobs:
            if not j.remote and _REMOTE.search(j.title+' '+' '.join(j.tags)): j.remote=True
            if j.salary_min_k is None: j.salary_min_k=parse_salary_min_k(j.salary)
        added=db.upsert_jobs(jobs)
        kept=0
        for j in jobs:
            row=db.get_job(j.id)
            ok,why=passes(row,crit) if not j.needs_enrich or row['enriched'] else (True,'')
            age=age_days(row.get('published_at') or '')
            if crit.get('max_age_days') and age is not None and age>crit['max_age_days']:
                ok,why=False,f'发布于 {age} 天前，太旧了'
            if ok: kept+=1
            else: db.update_evaluation(j.id,{'filtered':1,'score_reason':why,'verdict_reason':why,'verdict':'no','evaluated':1},revision)
        detail=f'去重后 {len(jobs)} 条候选；初筛保留 {kept} 条；缺少日期或正文的标为待核验。'
        if warning:
            detail='本轮仅部分完成，已保存候选。'+detail+str(warning)
            db.run_finish(run_id,ok=False,found=len(jobs),added=len(added),kept=kept,detail=detail,error=str(warning),error_kind=warning.kind)
            progress(source_id,'error',detail)
            db.log('warn',detail,source_id)
            return {'ok':False,'kind':warning.kind,'error':str(warning),'found':len(jobs),'added':len(added),'kept':kept}
        db.run_finish(run_id,ok=True,found=len(jobs),added=len(added),kept=kept,detail=detail)
        progress(source_id,'done',detail)
        db.log('info',detail,source_id)
        return {'ok':True,'found':len(jobs),'added':len(added),'kept':kept}
    except asyncio.CancelledError:
        db.run_finish(run_id,ok=False,error='任务已取消，已保存的岗位保留',error_kind='cancelled')
        progress(source_id,'cancelled','已取消')
        raise
    except Exception as e:
        kind=e.kind if isinstance(e,CollectorError) else 'timeout' if isinstance(e,asyncio.TimeoutError) else 'network'
        message=str(e) or '任务超过 10 分钟，已释放资源；可稍后重试'
        db.run_finish(run_id,ok=False,error=message,error_kind=kind)
        progress(source_id,'error',message); db.log('warn',message,source_id)
        return {'ok':False,'kind':kind,'error':message}


def retry(row, reason):
    attempts=int(row.get('attempts') or 0)+1
    db.update_evaluation(row['id'],{'attempts':attempts,'retry_at':(datetime.now()+timedelta(minutes=5*attempts)).isoformat(),
        'score_reason':f'AI 未完成：{reason}；'+('已暂停，点击重新评估可重试' if attempts>=3 else '稍后重试')},row.get('assessment_revision'))


async def enrich_pending(batch=10):
    from .pipeline import passes
    s=load_settings()
    if not s['llm'].get('api_key') or not s['llm'].get('enrich'): return 0
    p=plans.get(); revision=p['revision']
    if p['state']!='active' or not p['evaluation_enabled']: return 0
    rows=db.jobs_to_enrich(batch)
    if not rows: return 0
    try:
        # Fact extraction has no person's preferences. Its result is reusable by all plans.
        need=[]
        for row in rows:
            fact=db.conn().execute('SELECT enriched,needs_enrich FROM jobs WHERE id=?',(row['id'],)).fetchone()
            if not fact['enriched'] and fact['needs_enrich']: need.append(row)
        if need:
            extracted=await llm.extract_facts(s['llm'],need)
            for i,row in enumerate(need):
                it=next((v for v in extracted if isinstance(v,dict) and v.get('i')==i),None)
                if not it: continue
                fields={k:str(it[k])[:4000] for k in ('title','company','city','salary','job_type','published_at','title_zh') if it.get(k) and not row.get(k)}
                if fields.get('salary'): fields['salary_min_k']=parse_salary_min_k(fields['salary'])
                if it.get('is_job') is False: fields['job_type']='not_a_job'
                if it.get('remote') is True: fields['remote']=1
                if fields:
                    from .models import cluster_key
                    facts={**row,**fields}
                    fields['cluster_key']=cluster_key(facts['company'] or '',facts['title'],facts['city'] or '',facts['job_type'] or '')
                    db.update_job(row['id'],fields)
                db.conn().execute('UPDATE jobs SET enriched=1 WHERE id=?',(row['id'],))
            db.conn().commit()
        fresh=[db.get_job(r['id']) for r in rows]
        fresh=[r for r in fresh if r]
        items=await llm.enrich(s['llm'],s['criteria'],fresh)
        # Ignore results produced against an outdated request.
        if plans.get()['revision']!=revision: return 0
        by_i={it.get('i'):it for it in items if isinstance(it,dict)}
        for i,row in enumerate(fresh):
            latest_fact=db.conn().execute('SELECT content_hash FROM jobs WHERE id=?',(row['id'],)).fetchone()
            if not latest_fact or latest_fact['content_hash']!=row.get('content_hash'): continue
            it=by_i.get(i)
            if not it or it.get('verdict') not in ('recommend','maybe','no'):
                retry(row,'缺少该岗位的有效判断'); continue
            try: score=max(0,min(100,int(it.get('score',0))))
            except (TypeError,ValueError): retry(row,'分数格式错误'); continue
            ok,why=passes(row,s['criteria'])
            if row['job_type']=='not_a_job': ok,why=False,'不是具体招聘信息'
            verdict=it['verdict'] if ok else 'no'
            gaps=quality(row)
            reason=str(it.get('reason') or '')[:300] if ok else why
            if gaps and verdict=='recommend':
                verdict='maybe'; reason='；'.join(gaps)+'。'+reason
            db.update_evaluation(row['id'],{'evaluated':1,'filtered':int(not ok),'score':min(score,40) if verdict=='no' else score,
                'verdict':verdict,'verdict_reason':reason,'score_reason':reason,'ai_summary':str(it.get('summary') or '')[:600]},revision)
        db.log('info',f'按方案「{p["name"]}」评估了 {len(fresh)} 条候选','llm')
        return len(fresh)
    except (llm.LLMError,ValueError,KeyError,httpx.HTTPError) as e:
        for row in rows: retry(row,str(e)[:150])
        db.log('warn',f'AI 评估未完成：{e}','llm')
        return 0
