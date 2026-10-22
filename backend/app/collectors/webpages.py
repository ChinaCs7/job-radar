"""需要用浏览器打开的信源：国内招聘平台（猎聘、前程无忧、智联、拉勾、58、牛客）和媒体平台
（小红书、知乎、微博、脉脉、即刻），以及免费的全网搜索（必应）。

这些平台都有反爬：接口带签名、有滑块验证、或者要登录。所以统一走专用浏览器（见 browser.py）：
打开真实的搜索页，然后用两种方式之一拿数据——

1. 旁听接口（capture）：页面自己会请求一个返回 JSON 的搜索接口，我们只读它的响应。字段完整、最准。
   用于：猎聘、前程无忧、小红书招聘官网。
2. 收链接（harvest）：读渲染好的页面，按「这个平台的岗位 / 帖子链接长什么样」把链接和它周围的文字收下来。
   不依赖接口格式，平台改版也不容易坏；字段靠大模型整理（needs_enrich）。
   用于：智联、拉勾、58、牛客、各媒体平台、必应。

遇到验证页 / 登录页时抛 blocked / login，调度器会暂停这个信源，等使用者在专用浏览器里手动处理。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote

import lxml.html

from .. import browser
from ..models import REGION_DOMESTIC, Job
from .base import Collector, CollectorError, SourceInfo, keywords_of
from .boss import guess_type
from .websearch import site_label


# ---------- 收链接 ----------

def harvest(html: str, base: str, href_re: str, *, container_xpath: str | None = None) -> list[tuple[str, str, str]]:
    """返回 [(链接, 标题, 周围文字)]。周围文字取「往上找到的第一个文字够多的父元素」。"""
    try:
        doc = lxml.html.fromstring(html)
    except (ValueError, lxml.etree.ParserError):
        return []
    doc.make_links_absolute(base, resolve_base_href=True)
    pat = re.compile(href_re)
    roots = doc.xpath(container_xpath) if container_xpath else [doc]
    seen: dict[str, tuple[str, str, str]] = {}
    for root in roots:
        for a in root.iter("a"):
            href = a.get("href") or ""
            if not pat.search(href):
                continue
            key = re.sub(r"[?#].*$", "", href) if "xsec_token" not in href else href
            title = _clean(a.text_content())
            ctx, node = "", a
            for _ in range(6):
                node = node.getparent()
                if node is None:
                    break
                t = _clean(node.text_content())
                if len(t) >= 40:
                    ctx = t[:800]
                    break
            if not title:
                title = (ctx.split(" ")[0] if ctx else "")[:80]
            if key in seen:
                # 同一个链接出现多次（封面图 + 标题），保留文字更多的那个
                if len(title) > len(seen[key][1]):
                    seen[key] = (href, title, seen[key][2] or ctx)
                continue
            seen[key] = (href, title, ctx)
    return [v for v in seen.values() if v[1] or v[2]]


_SAL_CUT = re.compile(r"\s(\d+(\.\d+)?\s*[-~]\s*\d+(\.\d+)?\s*[kK千万]|面议|薪资面议)")


def split_title(title: str, ctx: str) -> tuple[str, str]:
    """整张卡片都是链接时，标题会带上薪资、城市、公司。在薪资前截断，完整文字放进描述，留给 AI 整理。"""
    if len(title) <= 36:
        return title, ctx
    m = _SAL_CUT.search(title)
    head = title[: m.start()] if m and m.start() >= 4 else title[:36]
    return head.strip(), (title if len(title) > len(ctx) else ctx)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _hid(url: str) -> str:
    return hashlib.sha1(re.sub(r"[?#].*$", "", url).encode()).hexdigest()[:20]


# ---------- 平台定义 ----------

@dataclass
class Site:
    id: str
    name: str
    group: str                       # 招聘平台 / 媒体平台 / 全网搜索
    url: Callable[[str, dict], str]  # (关键词, 搜索条件) -> 搜索页地址
    note: str = ""
    needs_login: bool = False        # 必须登录才能搜
    verify_once: bool = False        # 首次需要手动过一次验证
    home: str = ""                   # 「打开登录 / 验证」时打开的地址
    href: str = ""                   # harvest：岗位 / 帖子链接的正则
    container: str | None = None     # harvest：只在这些容器里找链接
    capture: str = ""                # capture：接口地址的正则
    parse: Callable[[dict], list[Job]] | None = None
    parse_html: Callable[[str], list[Job]] | None = None   # 数据嵌在页面的 JSON 里（如智联的 __INITIAL_STATE__）
    blocked: tuple[str, ...] = ()    # 地址里出现这些就是验证页
    login: tuple[str, ...] = ()      # 地址里出现这些就是登录页
    suffix: str = ""                 # 搜索词后缀，媒体平台加「招聘」
    scroll: int = 2
    enabled: bool = True
    extra: dict = field(default_factory=dict)


CITY_58 = {"北京": "bj", "上海": "sh", "广州": "gz", "深圳": "sz", "杭州": "hz", "厦门": "xm", "成都": "cd", "武汉": "wh",
           "南京": "nj", "西安": "xa", "苏州": "su", "天津": "tj", "重庆": "cq", "长沙": "cs", "郑州": "zz", "福州": "fz",
           "合肥": "hf", "济南": "jn", "青岛": "qd", "大连": "dl", "宁波": "nb", "东莞": "dg", "佛山": "fs", "珠海": "zh"}


def _city(c: dict) -> str:
    return (c.get("cities") or [""])[0].removesuffix("市")


def parse_liepin(d: dict) -> list[Job]:
    out = []
    for it in (((d.get("data") or {}).get("data") or {}).get("jobCardList") or []):
        j, comp = it.get("job") or {}, it.get("comp") or {}
        if not j.get("jobId"):
            continue
        rt = j.get("refreshTime") or ""
        out.append(Job(
            source="liepin", external_id=str(j["jobId"]), title=j.get("title") or "", url=j.get("link") or "",
            company=comp.get("compName") or "", city=j.get("dq") or "", salary=j.get("salary") or "",
            experience=j.get("requireWorkYears") or "", education=j.get("requireEduLevel") or "",
            job_type=guess_type(j.get("title") or "", j.get("labels") or []),
            tags=[x for x in (j.get("labels") or []) if isinstance(x, str)][:6],
            description=" · ".join(x for x in (comp.get("compIndustry"), comp.get("compScale"), comp.get("compStage")) if x),
            platform="猎聘", published_at=f"{rt[:4]}-{rt[4:6]}-{rt[6:8]}" if len(rt) >= 8 else "",
        ))
    return out


def parse_51job(d: dict) -> list[Job]:
    out = []
    for it in (((d.get("resultbody") or {}).get("job") or {}).get("items") or []):
        jid = str(it.get("jobId") or "")
        if not jid:
            continue
        url = it.get("jobHref") or f"https://jobs.51job.com/{it.get('hrefAreaPinYin') or 'all'}/{jid}.html"
        out.append(Job(
            source="51job", external_id=jid, title=it.get("jobName") or "", url=url,
            company=it.get("companyName") or it.get("fullCompanyName") or "",
            city=(it.get("jobAreaLevelDetail") or {}).get("cityString") or it.get("jobAreaString") or "",
            salary=it.get("provideSalaryString") or "", experience=it.get("workYearString") or "",
            education=it.get("degreeString") or "", tags=(it.get("jobTags") or [])[:6],
            description=" · ".join(x for x in (it.get("companyTypeString"), it.get("companySizeString"),
                                                it.get("companyIndustryType1Str")) if x),
            job_type=guess_type(it.get("jobName") or "", it.get("jobTags") or []),
            platform="前程无忧", published_at=(it.get("issueDateString") or "")[:19],
        ))
    return out


def parse_xhsjobs(d: dict) -> list[Job]:
    out = []
    for it in ((d.get("data") or {}).get("list") or []):
        pid = it.get("positionId")
        if not pid:
            continue
        out.append(Job(
            source="xhsjobs", external_id=str(pid), title=it.get("positionName") or "",
            url=f"https://job.xiaohongshu.com/social/position/{pid}", company="小红书",
            city=(it.get("workplace") or "").replace("市", ""), job_type="fulltime",
            tags=[x for x in (it.get("jobType"), it.get("subDirectionName")) if x],
            description=f"{it.get('duty') or ''}\n{it.get('qualification') or ''}"[:2500],
            platform="小红书官网", published_at=it.get("publishTime") or "",
        ))
    return out


def parse_zhilian(html: str) -> list[Job]:
    """智联的搜索结果放在页面内嵌的 window.__INITIAL_STATE__.positionList 里，字段很全（含「兼职/临时」这种工作性质）。"""
    import json as _json
    m = re.search(r"__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not m:
        return []
    try:
        state = _json.loads(m.group(1))
    except ValueError:
        return []
    out = []
    for p in state.get("positionList") or []:
        url = p.get("positionURL") or p.get("positionUrl") or ""
        if not url:
            continue
        wt = p.get("workType") or ""
        raw_sk = p.get("skillLabel") or []
        if isinstance(raw_sk, str):
            try:
                raw_sk = _json.loads(raw_sk.replace("'", '"'))
            except ValueError:
                raw_sk = []
        skills = [x.get("value") for x in raw_sk if isinstance(x, dict) and x.get("value")]
        out.append(Job(
            source="zhilian", external_id=p.get("number") or url, title=p.get("name") or "", url=url,
            company=p.get("companyName") or "", city="·".join(x for x in (p.get("workCity"), p.get("cityDistrict")) if x),
            salary=p.get("salary60") or "", experience=p.get("workingExp") or "", education=p.get("education") or "",
            job_type="parttime" if "兼职" in wt else "intern" if "实习" in wt else "fulltime" if "全职" in wt else "",
            tags=skills[:6], description=" · ".join(x for x in (p.get("industryName"), p.get("companySize"), wt,
                                                                  p.get("jobSummary")) if x)[:1500],
            platform="智联招聘", published_at=(p.get("publishTime") or "")[:19],
        ))
    return out


def parse_xhs(d: dict) -> list[Job]:
    """小红书搜索接口 /api/sns/web/v1/search/notes 的返回。只有标题，正文要点进去看；交给 AI 判断是不是招聘。"""
    out = []
    for it in ((d.get("data") or {}).get("items") or []):
        nid, card = it.get("id"), it.get("note_card") or {}
        if not nid or it.get("model_type") not in (None, "note"):
            continue
        title = card.get("display_title") or ""
        token = it.get("xsec_token") or ""
        when = next((t.get("text") for t in card.get("corner_tag_info") or [] if t.get("type") == "publish_time"), "")
        out.append(Job(
            source="xiaohongshu", external_id=nid, title=title[:200] or "（无标题笔记）",
            url=f"https://www.xiaohongshu.com/explore/{nid}?xsec_token={token}&xsec_source=pc_search",
            description=" · ".join(x for x in (title, f"作者：{(card.get('user') or {}).get('nickname', '')}",
                                                 f"发布：{when}" if when else "") if x),
            platform="小红书", needs_enrich=True,
        ))
    return out


SITES: dict[str, Site] = {s.id: s for s in [
    # —— 国内招聘平台 ——
    Site("liepin", "猎聘", "招聘平台", lambda k, c: f"https://www.liepin.com/zhaopin/?key={quote(k)}",
         note="中高端岗位多，不登录也能搜", home="https://www.liepin.com/",
         capture=r"pc-search-job", parse=parse_liepin, blocked=("verify", "captcha"), login=("passport",)),
    Site("51job", "前程无忧", "招聘平台",
         lambda k, c: f"https://we.51job.com/pc/search?keyword={quote(k)}&searchType=2&sortType=0",
         note="不登录也能搜，城市按 IP 默认", home="https://we.51job.com/",
         capture=r"api/job/search-pc", parse=parse_51job, blocked=("verify", "captcha"), login=("login.51job",)),
    Site("zhilian", "智联招聘", "招聘平台", lambda k, c: f"https://sou.zhaopin.com/?kw={quote(k)}",
         note="建议登录；数据从页面内嵌的岗位列表里读", needs_login=True, home="https://passport.zhaopin.com/login",
         parse_html=parse_zhilian, blocked=("verify", "captcha"), login=("passport.zhaopin",)),
    Site("lagou", "拉勾", "招聘平台", lambda k, c: f"https://www.lagou.com/wn/jobs?kd={quote(k)}&city={quote(_city(c) or '全国')}",
         note="首次要过滑块验证，互联网岗位多", verify_once=True, home="https://www.lagou.com/wn/jobs?kd=Python",
         href=r"lagou\.com/(wn/)?jobs/\d+\.html", blocked=("verify", "滑动验证"), login=("passport.lagou",)),
    Site("58", "58 同城", "招聘平台",
         lambda k, c: f"https://{CITY_58.get(_city(c), 'bj')}.58.com/job/?key={quote(k)}",
         note="首次要过验证码；城市取搜索条件里的第一个", verify_once=True, home="https://bj.58.com/job/",
         href=r"58\.com/[\w/]+/\d+x\.shtml", blocked=("antibot", "verifycode"), login=("passport.58",)),
    Site("nowcoder", "牛客", "招聘平台", lambda k, c: f"https://www.nowcoder.com/jobs/recommend/campus?keyword={quote(k)}",
         note="校招、实习、内推为主", home="https://www.nowcoder.com/jobs",
         href=r"nowcoder\.com/jobs/detail/\d+", login=("/login",)),
    # —— 公司官网里需要浏览器的 ——
    Site("xhsjobs", "小红书官网", "公司官网", lambda k, c: f"https://job.xiaohongshu.com/social/position?keyword={quote(k)}",
         note="小红书招聘官网（接口带签名，所以走浏览器）", home="https://job.xiaohongshu.com/",
         capture=r"pageQueryPosition", parse=parse_xhsjobs),
    # —— 媒体平台：都要登录；帖子交给 AI 判断是不是招聘 ——
    Site("xiaohongshu", "小红书", "媒体平台",
         lambda k, c: f"https://www.xiaohongshu.com/search_result?keyword={quote(k)}&type=51",
         note="搜「关键词 + 招聘」的笔记；需要登录", needs_login=True, home="https://www.xiaohongshu.com/",
         capture=r"/api/sns/web/v1/search/notes", parse=parse_xhs, login=("/login",),
         suffix=" 招聘", enabled=False),
    Site("zhihu", "知乎", "媒体平台", lambda k, c: f"https://www.zhihu.com/search?type=content&q={quote(k)}",
         note="需要登录", needs_login=True, home="https://www.zhihu.com/signin",
         href=r"(zhihu\.com/question/\d+(/answer/\d+)?|zhuanlan\.zhihu\.com/p/\d+)", login=("signin", "/login"),
         suffix=" 招聘", enabled=False),
    Site("weibo", "微博", "媒体平台", lambda k, c: f"https://s.weibo.com/weibo?q={quote(k)}",
         note="需要登录", needs_login=True, home="https://weibo.com/login.php",
         href=r"weibo\.com/\d+/[A-Za-z0-9]{8,}", login=("passport.weibo", "login"), suffix=" 招聘", enabled=False),
    Site("maimai", "脉脉", "媒体平台", lambda k, c: f"https://maimai.cn/web/search_center?type=gossip&query={quote(k)}",
         note="实验性：职言区帖子没有独立链接、且多为求职帖，暂时拿不到数据", needs_login=True, home="https://maimai.cn/platform/login",
         href=r"maimai\.cn/web/(gossip_detail|feed_detail)", login=("platform/login",), suffix=" 内推", enabled=False),
    Site("jike", "即刻", "媒体平台", lambda k, c: f"https://web.okjike.com/search?keyword={quote(k)}",
         note="需要登录", needs_login=True, home="https://web.okjike.com/login",
         href=r"okjike\.com/originalPost/[0-9a-f]{24}", login=("/login",), suffix=" 招聘", enabled=False),
]}

class WebPage(Collector):
    """一个 Site 对应一个信源。"""

    def __init__(self, site: Site):
        self.site = site
        self.info = SourceInfo(site.id, site.name, site.group, "domestic",
                               needs_login=site.needs_login or site.verify_once, note=site.note)
        self.info.verify_once = site.verify_once  # type: ignore[attr-defined]
        self.info.home = site.home  # type: ignore[attr-defined]

    def _check(self, v: browser.Visit):
        u = (v.final_url or "").lower()
        title = v.title or ""
        if any(x.lower() in u for x in self.site.blocked) or any(x in title for x in ("验证", "Verification", "captcha")):
            raise CollectorError("blocked", f"{self.site.name} 要求验证：请在专用浏览器里打开它，手动完成验证后点「恢复」")
        if any(x.lower() in u for x in self.site.login):
            raise CollectorError("login", f"{self.site.name} 需要登录：请在「账号与密钥」里打开登录窗口")

    async def collect(self, criteria, cfg, settings):
        s = self.site
        kws = keywords_of(criteria)[: int(cfg.get("max_keywords", 2))]
        out: list[Job] = []
        for kw in kws:
            q = kw + s.suffix
            async with browser.Visit(s.url(q, criteria), capture=s.capture or None) as v:
                if s.parse_html:
                    await v.scroll(1)
                    html = await v.html()
                    self._check(v)
                    out += [j for j in s.parse_html(html) if j.url]
                elif s.capture and s.parse:
                    # 同一个页面可能先请求「筛选条件」再请求「岗位列表」，地址相近；全部收下逐个解析
                    got, first = [], await v.next_json(20)
                    while first is not None:
                        got.append(first)
                        first = await v.next_json(3)
                    await v.html()
                    self._check(v)
                    if not got:
                        raise CollectorError("network", f"{s.name} 没有返回搜索结果（页面可能改版或加载太慢）")
                    for d in got:
                        try:
                            out += [j for j in s.parse(d) if j.url]
                        except (AttributeError, TypeError, KeyError):
                            continue
                else:
                    await v.scroll(s.scroll)
                    html = await v.html()
                    self._check(v)
                    items = harvest(html, v.final_url or s.home, s.href, container_xpath=s.container)
                    if not items and s.needs_login and ("登录" in html[:200000]):
                        raise CollectorError("login", f"{s.name} 需要登录：请在「账号与密钥」里打开登录窗口")
                    for href, title, ctx in items:
                        title, ctx = split_title(title, ctx)
                        out.append(Job(
                            source=s.id, external_id=_hid(href), title=title[:200], url=href,
                            description=ctx, platform=s.name, region=REGION_DOMESTIC,
                            needs_enrich=True,
                        ))
        return out


# ---------- 免费全网搜索：必应 ----------

class BingSearch(Collector):
    """用专用浏览器打开必应搜索结果页，按「关键词 招聘 site:平台」搜，不需要任何 key。
    搜到的是网页，交给 AI 判断是不是岗位；没有 key 时显示原始标题和摘要。"""
    info = SourceInfo("bing", "全网搜索（必应）", "全网搜索", "mixed",
                      note="免费：用专用浏览器搜必应，按站点搜小红书、脉脉、知乎、牛客等")

    async def collect(self, criteria, cfg, settings):
        kws = keywords_of(criteria)
        sites = cfg.get("sites") or []
        city = " ".join((criteria.get("cities") or [])[:1])
        queries = [f"{kw} 招聘 site:{s}" for kw in kws for s in sites] + [f"{kw} 招聘 {city}".strip() for kw in kws]
        out: list[Job] = []
        for q in queries[: int(cfg.get("max_queries", 10))]:
            async with browser.Visit(f"https://cn.bing.com/search?q={quote(q)}&count=30", settle=3) as v:
                html = await v.html()
                if "captcha" in (v.final_url or "") or "验证" in v.title:
                    raise CollectorError("blocked", "必应要求验证：请在专用浏览器里打开必应手动完成")
                for href, title, ctx in harvest(html, "https://cn.bing.com/", r"^https?://(?!(cn\.)?bing\.com|go\.microsoft)",
                                                container_xpath="//li[contains(@class,'b_algo')]//h2"):
                    snippet = _bing_snippet(html, href)
                    if not looks_like_job(f"{title} {snippet}"):
                        continue
                    out.append(Job(
                        source="bing", external_id=_hid(href), title=title[:200], url=href,
                        description=snippet or ctx, platform=site_label(href), needs_enrich=True,
                        raw={"query": q},
                    ))
        return out


_JOB_WORDS = re.compile(r"招聘|招人|岗位|职位|内推|诚聘|急招|社招|校招|实习|求贤|hiring|job|career|薪|简历|jd", re.I)


def looks_like_job(text: str) -> bool:
    """搜索结果粗筛：标题和摘要里一个招聘相关的词都没有，基本不是岗位（词典、诗词、百科这类）。"""
    return bool(_JOB_WORDS.search(text or ""))


def _bing_snippet(html: str, href: str) -> str:
    """必应的摘要在标题所在 li.b_algo 里，单独取出来比「周围文字」更干净。"""
    try:
        doc = lxml.html.fromstring(html)
    except (ValueError, lxml.etree.ParserError):
        return ""
    for li in doc.xpath("//li[contains(@class,'b_algo')]"):
        a = li.xpath(".//h2//a/@href")
        if a and a[0] == href:
            return _clean(" ".join(li.xpath(".//p//text() | .//div[contains(@class,'b_caption')]//text()")))[:600]
    return ""

