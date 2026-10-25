"""牛客原生职位搜索；不收零结果之后的扩展推荐。"""
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from .. import browser, plans, db
from ..models import Job
from .base import Collector, CollectorError, SourceInfo, keywords_of
from .webpages import WebPage, SITES


def search_url(keyword, city, recruit_type, page):
    route={2:'intern/center',3:'fulltime/center'}[recruit_type]
    return 'https://www.nowcoder.com/jobs/'+route+'?'+urlencode({
        'search':keyword,'city':city,'recruitType':recruit_type,'latest':'true','page':page})


def verified_jobs(response, meta, keyword, city, recruit_type, page):
    body=meta.get('body') or {}
    if body.get('query')!=keyword or (body.get('jobCity') or [])!=([city] if city else []) or str(body.get('recruitType'))!=str(recruit_type) or str(body.get('page'))!=str(page):
        raise CollectorError('coverage','牛客实际请求的关键词、城市、类型或页码不符，停止接收推荐列表')
    data=response.get('data') or {}
    if response.get('code')!=0 or not isinstance(data,dict) or not isinstance(data.get('datas'),list) or str(data.get('currentPage'))!=str(page):
        raise CollectorError('parse','牛客未返回可核验的职位列表')
    out=[]
    for card in data['datas']:
        j=card.get('data') or {}
        if not j.get('id') or not j.get('jobName'):
            raise CollectorError('parse','牛客出现未支持的职位卡片类型')
        try: ext=json.loads(j.get('ext') or '{}')
        except (ValueError,TypeError): ext={}
        if not isinstance(ext,dict): ext={}
        try: published=datetime.fromtimestamp(int(j['createTime'])/1000,timezone(timedelta(hours=8))).isoformat(timespec='seconds')
        except (ValueError,TypeError,KeyError,OverflowError): published=''
        salary=j.get('salaryShow') or ''
        if not salary and j.get('salaryMin') and j.get('salaryMax'):
            unit={1:'元/天',2:'K'}.get(j.get('salaryType'))
            if unit: salary=f"{j['salaryMin']}-{j['salaryMax']}{unit}"
        out.append(Job(source='nowcoder',external_id=str(j['id']),title=j['jobName'],
            url=f"https://www.nowcoder.com/jobs/detail/{j['id']}",
            company=(j.get('recommendInternCompany') or {}).get('companyName') or '',
            city=j.get('jobCity') or '',job_type={2:'intern',3:'fulltime'}.get(j.get('recruitType'),''),
            salary=salary,description='\n'.join(str(ext[k]) for k in ('infos','requirements','jobStrength') if ext.get(k)),
            tags=(j.get('jobKeys') or '').split(',')[:6],platform='牛客',published_at=published,
            raw={'date_basis':'created','refresh_time':j.get('refreshTime'),'coverage':'native_search'}))
    return out,int(data.get('totalPage') or 0)


class Nowcoder(Collector):
    info=SourceInfo('nowcoder','牛客','招聘平台','domestic',note='社招/实习原生搜索，逐页核验；按首次发布日期筛选，排除扩展推荐；每组合本轮最多 2 页')

    async def collect(self,criteria,cfg,settings):
        kinds=criteria.get('job_types') or ['fulltime']
        types=[code for kind,code in [('fulltime',3),('intern',2)] if kind in kinds]
        if not types: raise CollectorError('config','牛客目前支持全职社招和实习；不把校招结果充当兼职')
        combos=[(kw,c,t) for kw in keywords_of(criteria) for c in criteria.get('cities') or [''] for t in types]
        out={}
        from ..collection_budget import track
        track(out)
        try:
            for kw,city,kind in plans.rotate('nowcoder',combos,max(1,min(3,int(cfg.get('max_combos',2))))):
                from .job51 import next_page
                import asyncio
                limit=max(1,min(3,int(cfg.get('max_pages',2))))
                async with browser.Visit(search_url(kw,city,kind,1),capture=r'/np-api/u/job/square-search',settle=5) as v:
                    for page in range(1,limit+1):
                        response=await v.next_json(20)
                        html=await v.html();WebPage(SITES['nowcoder'])._check(v)
                        if response is None: raise CollectorError('coverage','牛客未返回原生搜索接口，不使用推荐页替代')
                        jobs,total=verified_jobs(response,v.last_response_meta,kw,city,kind,page)
                        if jobs and all(j.id in out for j in jobs) and page>1:
                            raise CollectorError('coverage','牛客翻页重复，停止本轮')
                        out.update({j.id:j for j in jobs})
                        db.log('info',f'牛客 {kw}/{city or "全国"}：第 {page}/{total} 页 {len(jobs)} 条；以首次发布日期筛选','nowcoder')
                        if page>=total: break
                        if page==limit:
                            db.log('warning',f'牛客本轮达到页数预算，共 {total} 页尚未全部扫描','nowcoder');break
                        await asyncio.sleep(4)
                        if not await next_page(v,html,'牛客'):
                            raise CollectorError('coverage','牛客声明有后续页，但下一页不可用')
            return list(out.values())
        except CollectorError as e:
            e.partial=list(out.values());raise
        except Exception as e:
            raise CollectorError('network',f'牛客检索中断：{type(e).__name__}',list(out.values())) from e
