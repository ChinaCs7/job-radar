"""Liepin's own city codes and zero-based page contract, verified against responses."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from .. import browser,db,plans
from ..plan_context import current_plan
from .base import Collector,CollectorError,SourceInfo,keywords_of
from .webpages import parse_liepin,WebPage,SITES

# Observed from the public city selector's get-all-dq response, 2026-10-24.
CITY_CODES=json.loads((Path(__file__).resolve().parents[1]/'data'/'liepin_city_codes.json').read_text('utf-8'))


def search_url(keyword,city,page):
    code=CITY_CODES.get(city.strip().removesuffix('市')) if city else '410'
    if not code: raise CollectorError('config',f'猎聘城市尚未适配：{city}；不会回退全国搜索')
    return 'https://www.liepin.com/zhaopin/?'+urlencode({'key':keyword,'dq':code,'city':code,'currentPage':page}),code


def verified_jobs(response,keyword,code,page):
    data=response.get('data') if isinstance(response,dict) else None
    content=data.get('data') if isinstance(data,dict) else None
    if not isinstance(content,dict) or 'jobCardList' not in content: return None
    sub=content.get('jobSubscribeInfo') or {};pagination=data.get('pagination') or {}
    if sub.get('keyword')!=keyword or str(sub.get('dqCode'))!=code or str(pagination.get('currentPage'))!=str(page):
        raise CollectorError('coverage','猎聘响应关键词、城市或页码与方案不一致')
    if not isinstance(content['jobCardList'],list): raise CollectorError('parse','猎聘岗位列表结构变化')
    jobs=parse_liepin(response)
    if len(jobs)!=len(content['jobCardList']) or any(not j.url for j in jobs):
        raise CollectorError('parse','猎聘页面存在缺少岗位 ID 或链接的记录')
    return jobs,pagination


class Liepin(Collector):
    info=SourceInfo('liepin','猎聘','招聘平台','domestic',note='按猎聘城市代码与页码核验搜索；列表日期为平台刷新字段，详情及在招状态待核验')

    async def collect(self,criteria,cfg,settings):
        from ..execution import progress
        out={}
        from ..collection_budget import track
        track(out)
        pid=current_plan.get() or 'legacy';revision=plans.get()['revision']
        combinations=[(k,c) for k in keywords_of(criteria) for c in criteria.get('cities') or ['']]
        for keyword,city in combinations: search_url(keyword,city,0)
        try:
            for keyword,city in plans.rotate('liepin',combinations,min(2,int(cfg.get('max_combos',1)))):
                signature=hashlib.sha256(json.dumps([keyword,city]).encode()).hexdigest()
                row=db.conn().execute('SELECT cursor FROM search_cursors WHERE plan_id=? AND source=? AND signature=?',(pid,'liepin_pages',signature)).fetchone()
                start=row[0] if row else 0;seen=set()
                for page in range(start,min(10,start+max(1,min(3,int(cfg.get('max_pages',2)))))):
                    url,code=search_url(keyword,city,page)
                    progress('liepin','searching',f'{keyword} / {city or "全国"}：核验第 {page+1} 页')
                    async with browser.Visit(url,capture='pc-search-job',settle=5) as visit:
                        matched=None
                        for attempt in range(6):
                            response=await visit.next_json(20 if attempt==0 else 3)
                            if response is None: break
                            matched=verified_jobs(response,keyword,code,page)
                            if matched is not None: break
                        await visit.html();WebPage(SITES['liepin'])._check(visit)
                        if matched is None: raise CollectorError('coverage','猎聘未取得可核验的岗位响应')
                    jobs,pagination=matched
                    if jobs and all(j.id in seen for j in jobs): raise CollectorError('coverage','猎聘翻页只返回重复岗位，未推进断点')
                    seen.update(j.id for j in jobs);out.update({j.id:j for j in jobs})
                    # Persist the page before moving its checkpoint. The outer execution stage applies plan filters.
                    from ..pipeline import passes
                    from ..models import parse_salary_min_k
                    if plans.get()['revision']!=revision: raise CollectorError('config','方案已修改，停止旧条件检索')
                    for job in jobs: job.salary_min_k=parse_salary_min_k(job.salary)
                    db.upsert_jobs(jobs)
                    for job in jobs:
                        ok,why=passes(job.__dict__,criteria)
                        if not ok: db.update_evaluation(job.id,{'filtered':1,'evaluated':1,'verdict':'no','score_reason':why,'verdict_reason':why},revision)
                    end=not jobs or page+1>=min(10,int(pagination.get('totalPage') or 1))
                    db.conn().execute('INSERT OR REPLACE INTO search_cursors VALUES(?,?,?,?)',(pid,'liepin_pages',signature,0 if end else page+1));db.conn().commit()
                    db.log('info',f'猎聘 {keyword}/{city or "全国"}：已核验第 {page+1} 页 {len(jobs)} 条；'+('本轮扫描范围结束，下轮回首页' if end else '已保存续查位置')+'；详情与在招状态待核验','liepin')
                    if end: break
            return list(out.values())
        except CollectorError as e:
            e.partial=list(out.values());raise
        except Exception as e:
            raise CollectorError('network',f'猎聘本轮未完成：{type(e).__name__}，保留已取得的岗位',list(out.values())) from e
