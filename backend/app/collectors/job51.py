"""前程无忧：显式城市、最新排序，点击真实下一页并核对请求。"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode
import lxml.html
from .. import browser, plans, db
from .base import Collector, CollectorError, SourceInfo, keywords_of
from .webpages import parse_51job, WebPage, SITES

# Public 51job city selector seo_dd_areas.js, observed 2026-10-24.
CITY_CODES=json.loads((Path(__file__).resolve().parents[1]/'data'/'51job_city_codes.json').read_text('utf-8'))


def search_url(keyword,city):
    code=CITY_CODES.get(city.strip().removesuffix('市')) if city else '000000'
    if not code: raise CollectorError('config',f'前程无忧城市尚未适配：{city}；不沿用浏览器记忆')
    return 'https://we.51job.com/pc/search?'+urlencode({'keyword':keyword,'searchType':2,'sortType':1,'jobArea':code}),code


def verified_jobs(response,meta,keyword,code,page):
    query=meta.get('query') or {}
    if any(str(query.get(k))!=str(v) for k,v in {'keyword':keyword,'jobArea':code,'pageNum':page,'sortType':1}.items()):
        raise CollectorError('coverage','前程无忧实际搜索条件或页码不符，停止接收')
    data=(response.get('resultbody') or {}).get('job') or {}
    if not isinstance(data.get('items'),list): raise CollectorError('parse','前程无忧列表结构变化')
    jobs=parse_51job(response)
    if len(jobs)!=len(data['items']) or any(not j.url for j in jobs): raise CollectorError('parse','前程无忧存在缺少身份或链接的岗位')
    for job in jobs: job.raw={'coverage':'list_only','date_basis':'platform_issue_date'}
    return jobs


async def next_page(visit,html,label="前程无忧"):
    doc=lxml.html.fromstring(html)
    buttons=doc.xpath('//div[contains(@class,"el-pagination")]//button[contains(@class,"btn-next")]')
    if len(buttons)!=1: raise CollectorError('coverage',f'{label}下一页控件无法确认')
    if 'disabled' in buttons[0].attrib: return False
    page=visit.page
    root=await page.send('DOM.getDocument',{'depth':0})
    node=await page.send('DOM.querySelector',{'nodeId':root['root']['nodeId'],'selector':'.el-pagination .btn-next'})
    if not node.get('nodeId'): raise CollectorError('coverage',f'{label}下一页控件已变化')
    await page.send('DOM.scrollIntoViewIfNeeded',{'nodeId':node['nodeId']})
    await asyncio.sleep(0.8)
    box=await page.send('DOM.getBoxModel',{'nodeId':node['nodeId']})
    quad=box['model']['content'];x=sum(quad[::2])/4;y=sum(quad[1::2])/4
    await page.send('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y})
    for event in ('mousePressed','mouseReleased'):
        await page.send('Input.dispatchMouseEvent',{'type':event,'x':x,'y':y,'button':'left','clickCount':1})
    return True


class Job51(Collector):
    info=SourceInfo('51job','前程无忧','招聘平台','domestic',note='城市与关键词显式传入；真实翻页核验，每组合本轮最多 2 页；列表摘要待补详情')
    async def collect(self,criteria,cfg,settings):
        combos=[(k,c) for k in keywords_of(criteria) for c in criteria.get('cities') or ['']]
        for k,c in combos: search_url(k,c)
        out={}
        try:
            for kw,city in plans.rotate('51job',combos,max(1,min(3,int(cfg.get('max_combos',1))))):
                url,code=search_url(kw,city)
                async with browser.Visit(url,capture=r'api/job/search-pc',settle=5) as v:
                    limit=max(1,min(3,int(cfg.get('max_pages',2))))
                    for page in range(1,limit+1):
                        response=await v.next_json(20)
                        html=await v.html();WebPage(SITES['51job'])._check(v)
                        if response is None: raise CollectorError('coverage','前程无忧未收到搜索响应')
                        jobs=verified_jobs(response,v.last_response_meta,kw,code,page)
                        if page>1 and jobs and all(j.id in out for j in jobs): raise CollectorError('coverage','前程无忧翻页全部重复')
                        out.update({j.id:j for j in jobs})
                        db.log('info',f'前程无忧 {kw}/{city or "全国"}：已核验第 {page} 页 {len(jobs)} 条；详情待补','51job')
                        if not jobs: break
                        if page==limit:
                            db.log('info','前程无忧本轮页数预算结束，未声称全量覆盖','51job');break
                        await asyncio.sleep(4)
                        if not await next_page(v,html): break
            return list(out.values())
        except CollectorError as e:
            e.partial=list(out.values());raise
        except Exception as e:
            raise CollectorError('network',f'前程无忧检索中断：{type(e).__name__}',list(out.values())) from e
