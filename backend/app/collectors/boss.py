"""Boss 直聘。

为什么不直接请求接口：Boss 的搜索接口要带一个由混淆 JS 算出来、经常变的 token；
页面上的薪资用了字体反爬；代码直接发请求很快会收到 code 37「您的环境存在异常」。

所以这里的链路是（参考 eatmoreduck/boss-zhipin-scraper，MIT）：
  专用浏览器（已登录）打开真实搜索页
  → 页面自己发出 /wapi/zpgeek/search/joblist.json
  → 我们只旁听这个响应（Network 域），拿到明文薪资的 JSON
  → 翻页靠模拟滚轮触发页面自己的「无限滚动」

判定规则：
- 响应 code 31 / 37，或 message 里有「异常 / 频繁 / 验证」→ blocked：立刻停，不重试，等人工处理
- 缺少岗位列表字段 → 响应异常，不能当作零岗位；薪资为空不推断登录状态
- 页面被跳到登录页或安全验证页 → login / blocked
"""
from __future__ import annotations

import asyncio
import base64
import json
import random
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

from .. import browser
from ..models import Job
from .base import Collector, CollectorError, SourceInfo, keywords_of

JOBLIST = "/wapi/zpgeek/search/joblist.json"
RESTRICTED_CODES = {31, 37}
RESTRICTED_WORDS = ("环境存在异常", "访问频繁", "操作太频繁", "安全校验", "滑块", "验证")
CITY_CODES: dict[str, str] = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "boss_city_codes.json").read_text("utf-8"))
NATIONWIDE = "100010000"
LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"


def city_code(name: str) -> str | None:
    name = name.strip().removesuffix("市")
    return CITY_CODES.get(name)


def classify(data: dict | None) -> tuple[str, str]:
    """返回 (状态, 说明)。状态：ok / empty / login / blocked / error"""
    if not isinstance(data, dict):
        return "error", "没有拿到搜索结果"
    code = data.get("code")
    msg = str(data.get("message") or "")
    if code in RESTRICTED_CODES or any(w in msg for w in RESTRICTED_WORDS):
        return "blocked", f"Boss 要求人工验证（{msg or code}）"
    if code != 0:
        return "error", f"Boss 返回异常：{msg or code}"
    if not isinstance(data.get('zpData'),dict) or not isinstance(data['zpData'].get('jobList'),list):
        return 'error','Boss 响应缺少岗位列表字段，不能当作零岗位'
    jobs = data['zpData']['jobList']
    if not jobs:
        return "empty", "没有符合条件的岗位"
    return "ok", ""


def guess_type(title: str, labels: list) -> str:
    """平台列表里没有明确的工作性质字段，只能看标题和标签；看不出来就留空，不默认成全职。"""
    t = title + " " + " ".join(str(x) for x in labels or [])
    return "intern" if "实习" in t else "parttime" if "兼职" in t else ""


def map_job(raw: dict) -> Job | None:
    jid = raw.get("encryptJobId")
    if not jid:
        return None
    labels = raw.get("jobLabels") or []
    title = raw.get("jobName") or ""
    return Job(
        source="boss", external_id=jid, title=title,
        url=f"https://www.zhipin.com/job_detail/{jid}.html",
        company=raw.get("brandName") or "", city=raw.get("cityName") or "",
        salary=raw.get("salaryDesc") or "",
        job_type=guess_type(title, labels),
        experience=raw.get("jobExperience") or "", education=raw.get("jobDegree") or "",
        tags=(raw.get("skills") or [])[:8] + (raw.get("welfareList") or [])[:4],
        description=" · ".join(x for x in (raw.get("areaDistrict"), raw.get("businessDistrict"),
                                            raw.get("brandIndustry"), raw.get("brandScaleName"),
                                            raw.get("brandStageName"), raw.get("bossTitle")) if x),
        platform="Boss 直聘",
        raw={"bossOnline": raw.get("bossOnline"), "brandId": raw.get("encryptBrandId")},
    )


class _Capture:
    """旁听页面自己发出的 joblist 请求，按顺序返回响应 JSON。"""

    def __init__(self, page: browser.CDPPage):
        self.page = page
        self.pending: set[str] = set()
        self.nav_url = ""
        self.expected = None
        self.requests = {}
        self.last_request = None
        self.observed = []

    def expect(self, keyword, city, page):
        self.expected = (keyword,str(city),int(page))
        self.last_request = None

    async def next(self, timeout: float) -> dict | None:
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while (left := end - loop.time()) > 0:
            try:
                ev = await asyncio.wait_for(self.page.events.get(), left)
            except asyncio.TimeoutError:
                return None
            m, p = ev["method"], ev.get("params", {})
            if m == 'Network.requestWillBeSent' and JOBLIST in p.get('request',{}).get('url',''):
                request=p['request']
                query=parse_qs(urlparse(request['url']).query)
                post=request.get('postData','')
                if request.get('hasPostData') and not post:
                    post=(await self.page.send('Network.getRequestPostData',{'requestId':p['requestId']})).get('postData','')
                if post:
                    try:
                        fields=json.loads(post)
                        if isinstance(fields,dict): query.update({k:[str(v)] for k,v in fields.items()})
                    except ValueError:
                        query.update(parse_qs(post))
                try:
                    self.requests[p['requestId']] = (query.get('query',[''])[0],query.get('city',[''])[0],int(query.get('page',['0'])[0]))
                except ValueError:
                    self.requests[p['requestId']] = None
                self.observed.append(self.requests[p['requestId']])
            if m == "Network.responseReceived" and JOBLIST in p.get("response", {}).get("url", ""):
                if self.expected and self.requests.get(p['requestId']) != self.expected:
                    continue
                self.pending.add(p["requestId"])
            elif m == "Network.loadingFinished" and p.get("requestId") in self.pending:
                self.pending.discard(p["requestId"])
                body = await self.page.send("Network.getResponseBody", {"requestId": p["requestId"]})
                text = body.get("body", "")
                if body.get("base64Encoded"):
                    text = base64.b64decode(text).decode("utf-8", "replace")
                try:
                    data=json.loads(text)
                    observed=self.requests.pop(p['requestId'],None)
                    if self.expected and observed!=self.expected: continue
                    self.last_request=observed
                    return data
                except json.JSONDecodeError:
                    return None
            elif m == "Page.frameNavigated" and not p.get("frame", {}).get("parentId"):
                self.nav_url = p["frame"].get("url", "")
                # 验证页地址里也带 passport，所以先判断验证、再判断登录
                if "verify" in self.nav_url or "/safe/" in self.nav_url:
                    raise CollectorError("blocked", "Boss 要求安全验证，请打开专用浏览器手动完成")
                if "/web/user/" in self.nav_url or "passport" in self.nav_url:
                    raise CollectorError("login", "Boss 跳到了登录页，请在「账号与密钥」里重新登录")
        return None


def search_url(keyword: str, city: str, page: int = 1) -> str:
    return "https://www.zhipin.com/web/geek/job?" + urlencode({"query": keyword, "city": city, "page": page})


async def _human_scroll(page: browser.CDPPage):
    for _ in range(random.randint(3, 6)):
        await page.wheel(random.randint(250, 600) if random.random() > 0.15 else -random.randint(60, 150))
        await asyncio.sleep(random.uniform(0.6, 1.8))
    await page.wheel(4000)


async def probe() -> tuple[str, str]:
    """检测登录状态：打开一次真实搜索页看返回。只在使用者点「检测」时调用。"""
    async with browser.browser_slot(), browser.CDPPage() as page:
        await page.send("Network.enable")
        await page.send("Page.enable")
        cap = _Capture(page)
        await page.send("Page.navigate", {"url": search_url("Python", NATIONWIDE)})
        try:
            data = await cap.next(25)
        except CollectorError as e:
            return e.kind, str(e)
        return classify(data)


class Boss(Collector):
    info = SourceInfo("boss", "Boss 直聘", "招聘平台", "domestic", needs_login=True,
                      note="用专用浏览器和你自己的账号，频率请别太高")

    async def collect(self, criteria, cfg, settings):
        from .. import plans, db
        from ..execution import progress
        from ..pipeline import passes
        from ..models import parse_salary_min_k
        from . import boss_state as state
        kws = keywords_of(criteria)
        requested_cities=criteria.get('cities') or []
        unknown=[c for c in requested_cities if not city_code(c)]
        if unknown:
            raise CollectorError('config','Boss 不认识这些城市，未回退全国：'+'、'.join(unknown))
        cities=[city_code(c) for c in requested_cities] or [NATIONWIDE]
        combos=plans.rotate('boss',[(k,c) for k in kws for c in cities],min(3,int(cfg.get('max_combos',3))))
        max_pages=max(1,min(3,int(cfg.get('max_pages',2))))
        revision=plans.get()['revision']
        out=[]
        evidence={'queries':[], 'detail_attempted':0,'detail_completed':0,'detail_failed':0,
                  'filters':'关键词与城市在请求中核验；薪资、类型、时效在本地筛选；未知字段待核验'}
        def save(jobs):
            if plans.get()['revision']!=revision:
                raise CollectorError('config','方案已修改，停止旧条件采集')
            for j in jobs: j.salary_min_k=parse_salary_min_k(j.salary)
            db.upsert_jobs(jobs)
            # Save each page before requesting another, including when a later request times out.
            for j in jobs:
                ok,why=passes(db.get_job(j.id),criteria)
                if not ok:
                    db.update_evaluation(j.id,{'filtered':1,'verdict':'no','verdict_reason':why,'score_reason':why,'evaluated':1},revision)
            state.enqueue([j for j in jobs if passes(j.__dict__,criteria)[0]])
        try:
            async with browser.browser_slot(), browser.CDPPage() as page:
                await page.send('Network.enable')
                await page.send('Page.enable')
                cap=_Capture(page)
                for i,(kw,city) in enumerate(combos):
                    sig,start,head=state.page_start(kw,city)
                    record={'keyword':kw,'city':city,'start_page':start,'mode':'回扫首页' if head else '继续扫描','pages':[],'stop':''}
                    evidence['queries'].append(record)
                    progress('boss','searching',f'{kw}：从第 {start} 页开始，城市代码 {city}')
                    if i: await asyncio.sleep(random.uniform(6,15))
                    # Live verification: Boss ignores page= in navigation and always starts at page 1.
                    # Traverse the actual UI to the checkpoint; never label page 1 as page N.
                    cap.expect(kw,city,1)
                    await page.send('Page.navigate',{'url':search_url(kw,city,1)})
                    seen=set()
                    for pg in range(1,min(21,start+max_pages)):
                        if pg>1:
                            cap.expect(kw,city,pg)
                            await asyncio.sleep(random.uniform(6,10))
                            await _human_scroll(page)
                        data=await cap.next(25 if pg==1 else 15)
                        if data is None and pg>1:
                            # The list may not have finished rendering when the first wheel event arrives.
                            # One bounded second scroll, never a request replay or a new page navigation.
                            await _human_scroll(page)
                            data=await cap.next(10)
                        if data is None:
                            record['observed_requests']=cap.observed[-12:]
                            record['stop']='未取得与关键词、城市、页码一致的响应'
                            raise CollectorError('coverage',f'{kw} 第 {pg} 页未核验成功；保留已保存页面，不把滚动次数当页数')
                        status,why=classify(data)
                        if status not in ('ok','empty'):
                            record['stop']=why
                            raise CollectorError(status if status in ('login','blocked') else 'network',why)
                        jobs=[j for j in map(map_job,data['zpData']['jobList']) if j]
                        if len(jobs)!=len(data['zpData']['jobList']):
                            record['stop']='部分岗位缺少稳定 ID，未推进续查位置'
                            raise CollectorError('parse','Boss 列表存在缺少岗位 ID 的记录，不能视作完整页面')
                        fresh=[j for j in jobs if j.id not in seen]
                        record['pages'].append({'page':pg,'replay':pg<start,'count':len(jobs),'new_in_round':len(fresh),
                                                'job_ids':[j.external_id for j in jobs]})
                        if jobs and not fresh:
                            record['stop']='页面重复，未推进续查位置'
                            raise CollectorError('coverage',f'{kw} 第 {pg} 页只有重复岗位，停止本轮')
                        save(fresh)
                        seen.update(j.id for j in fresh)
                        out.extend(fresh)
                        more=data['zpData'].get('hasMore')
                        state.page_saved(sig,pg,False if status=='empty' else more,head or pg<start)
                        progress('boss','searching',f'{kw}：已核验第 {pg} 页，本组合 {len(seen)} 个不同岗位')
                        if status=='empty' or more is False:
                            record['stop']='平台返回末页'
                            break
                        if pg>=20:
                            record['stop']='达到 20 页扫描上限；下轮回扫首页，并不代表全站搜全'
                            state.page_saved(sig,pg,False)
                            break
                    if not record['stop']: record['stop']='本轮页数预算用尽，已保存续查位置'
                    state.round_done(sig)
            budget=max(0,min(5,int(cfg.get('detail_budget',3))))
            state.init()
            # Also process older candidates in this plan, not only this round's first few results.
            for j,attempts in state.pending(budget,criteria):
                if not passes(j.__dict__,criteria)[0]: continue
                evidence['detail_attempted']+=1
                progress('boss','detail',f'详情队列：{j.title}（第 {attempts+1} 次尝试）')
                try:
                    detail=await fetch_detail(j.url)
                    if not detail.get('description'):
                        raise CollectorError('parse','详情页面没有识别到职位正文，未标为完成')
                    j.description=detail['description']
                    if detail.get('published_at'): j.published_at=detail['published_at']
                    if detail.get('job_type'): j.job_type=detail['job_type']
                    save([j])
                    state.detail_done(j.id,True)
                    out.append(j)
                    evidence['detail_completed']+=1
                except CollectorError as e:
                    evidence['detail_failed']+=1
                    state.detail_done(j.id,False,str(e),e.kind in ('login','blocked'))
                    if e.kind in ('login','blocked'): raise
                    db.log('warn',f'详情补全失败，延后重试：{j.title}；{e}','boss')
                except Exception as e:
                    evidence['detail_failed']+=1
                    state.detail_done(j.id,False,str(e))
                    db.log('warn',f'详情补全失败，延后重试：{j.title}；{type(e).__name__}','boss')
            return list({j.id:j for j in out}.values())
        except CollectorError as e:
            evidence['error']={'kind':e.kind,'message':str(e)}
            e.partial=list({j.id:j for j in out}.values())
            raise
        except asyncio.CancelledError:
            evidence['error']={'kind':'cancelled','message':'取消；已经核验的页面已逐页保存'}
            raise
        finally:
            state.receipt(evidence)
            pages=sum(len(q['pages']) for q in evidence['queries'])
            db.log('info',f'Boss 覆盖记录：{pages} 个已核验页面；详情尝试 {evidence["detail_attempted"]}，成功 {evidence["detail_completed"]}；' +
                   '；'.join(q['keyword']+'：'+q['stop'] for q in evidence['queries']),'boss')


def parse_detail(html: str) -> dict:
    """Boss-specific detail extraction; never treat nearby navigation as a JD."""
    import lxml.html
    doc=lxml.html.fromstring(html)
    result={}
    for script in doc.xpath('//script[@type="application/ld+json"]/text()'):
        try: items=json.loads(script)
        except ValueError: continue
        if not isinstance(items,list): items=[items]
        for item in items:
            if not isinstance(item,dict) or item.get('@type')!='JobPosting': continue
            from .base import strip_html
            result['description']=strip_html(str(item.get('description') or ''))
            result['published_at']=str(item.get('datePosted') or '')[:10]
            if item.get('employmentType')=='FULL_TIME': result['job_type']='fulltime'
    blocks=doc.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," job-sec-text ")]')
    text='\n\n'.join(' '.join(b.text_content().split()) for b in blocks)
    if len(text)>len(result.get('description','')): result['description']=text[:12000]
    return result


async def fetch_detail(url: str) -> dict:
    async with browser.Visit(url,settle=3) as visit:
        html=await visit.html()
        if any(x in visit.final_url for x in ('verify','/safe/')) or '验证' in visit.title:
            raise CollectorError('blocked','Boss 详情需要人工验证，已暂停')
        if '/web/user/' in visit.final_url or 'passport' in visit.final_url:
            raise CollectorError('login','Boss 详情需要登录')
        return parse_detail(html)
