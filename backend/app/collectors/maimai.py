"""Maimai's web gossip search: structured posts, not guessed anchor links."""
import asyncio
import json
import re
from urllib.parse import urlencode

import lxml.html
from .. import browser,db,plans
from ..models import Job
from .base import Collector,CollectorError,SourceInfo,keywords_of,strip_html


def initial_data(html,query):
    doc=lxml.html.fromstring(html)
    for script in doc.xpath('//script[not(@src)]/text()'):
        match=re.search(r'\bshare_data\s*=\s*JSON.parse\(',script)
        if not match: continue
        try:
            encoded,_=json.JSONDecoder().raw_decode(script[match.end():].lstrip())
            data=json.loads(encoded)['data']
        except (ValueError,KeyError,TypeError):
            raise CollectorError('parse','脉脉页面数据结构变化，未将其当作空结果')
        if data.get('keyword')!=query or data.get('type')!='gossip':
            raise CollectorError('coverage','脉脉页面关键词或内容类型不匹配')
        return data
    raise CollectorError('parse','未找到脉脉结构化帖子列表，不能确认检索完成')


def parse_posts(data):
    if not isinstance(data,dict) or not isinstance(data.get('gossips'),list):
        raise CollectorError('parse','脉脉响应缺少帖子列表')
    jobs=[]
    for item in data['gossips']:
        post=item.get('gossip') or {}
        pid=str(post.get('id') or '')
        text=strip_html(post.get('text') or '').strip()
        if not pid or not text:
            raise CollectorError('parse','脉脉帖子缺少 ID 或正文，停止本页')
        params={'gid':pid}
        if post.get('egid'): params['egid']=post['egid']
        date=str(post.get('crtime') or '')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?',date): date=''
        seeking=bool(re.match(r'^(?:求内推|求职[，：:！!\s]|本人.{0,30}(?:求职|求内推))',text))
        jobs.append(Job(source='maimai',external_id=pid,title=text.split('\n')[0][:100],
            url='https://maimai.cn/web/gossip_detail?'+urlencode(params),description=text,
            published_at=date,platform='脉脉',needs_enrich=True,
            raw={'content_kind':'job_seeking' if seeking else 'unverified_post','date_basis':'post_created'}))
    return jobs


class Maimai(Collector):
    info=SourceInfo('maimai','脉脉','媒体平台','domestic',needs_login=True,
        note='职言招聘线索：按时间排序提取正文与发帖日期；城市需正文核验，不代表正式在招岗位')

    async def collect(self,criteria,cfg,settings):
        from .webpages import WebPage,SITES
        from ..execution import progress
        out={}
        from ..collection_budget import track
        track(out)
        max_pages=max(1,min(3,int(cfg.get('max_pages',2))))
        try:
            for keyword in plans.rotate('maimai',keywords_of(criteria),min(2,int(cfg.get('max_keywords',1)))):
                query=keyword+' 招聘'
                url='https://maimai.cn/web/search_center?'+urlencode({'type':'gossip','query':query,'sortby':'time'})
                async with browser.Visit(url,capture=r'/search/gossips(?:\?|$)',settle=5) as visit:
                    html=await visit.html();WebPage(SITES['maimai'])._check(visit)
                    data=initial_data(html,query)
                    seen=set();last_date=None
                    for page in range(max_pages):
                        if page:
                            await asyncio.sleep(6)
                            await visit.scroll(4)
                            data=await visit.next_json(15)
                            meta=visit.last_response_meta.get('query',{})
                            if data is None or meta.get('query')!=query or meta.get('offset')!=str(page*20) or meta.get('sortby')!='time':
                                raise CollectorError('coverage','脉脉下一页未核验成功，已保留前页帖子')
                            data=data.get('data') if isinstance(data,dict) else None
                        jobs=parse_posts(data)
                        if any(j.id in seen for j in jobs):
                            raise CollectorError('coverage','脉脉翻页出现重复帖子，停止而不当作新页')
                        for job in jobs:
                            if job.published_at and last_date and job.published_at>last_date:
                                raise CollectorError('coverage','脉脉结果未遵守时间倒序，停止时效扫描')
                            if job.published_at: last_date=job.published_at
                        seen.update(j.id for j in jobs);out.update({j.id:j for j in jobs})
                        progress('maimai','searching',f'{keyword}：已核验 {page+1} 页，{len(seen)} 条帖子，尚需筛选招聘性质')
                        if not data.get('more'): break
                        from ..pipeline import age_days
                        ages=[age_days(j.published_at) for j in jobs]
                        if criteria.get('max_age_days') and ages and all(a is not None and a>criteria['max_age_days'] for a in ages):
                            db.log('info','脉脉当前页全部超出方案时间范围，停止继续翻页','maimai');break
                    db.log('info',f'脉脉 {keyword}：核验 {len(seen)} 条时间倒序帖子；城市与招聘性质待核验；本轮最多 {max_pages} 页，不代表全站覆盖','maimai')
            return list(out.values())
        except CollectorError as e:
            e.partial=list(out.values());raise
        except Exception as e:
            raise CollectorError('network',f'脉脉本轮未完成：{type(e).__name__}；已保留此前取得的帖子',list(out.values())) from e
