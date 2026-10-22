"""有公开接口的信源：腾讯招聘、V2EX、电鸭、RemoteOK、Hacker News。不需要登录，最稳定。"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime

from ..models import REGION_DOMESTIC, REGION_OVERSEAS, Job
from .base import Collector, CollectorError, SourceInfo, keywords_of, strip_html, text_matches


class Tencent(Collector):
    """腾讯招聘官网的公开查询接口，支持关键词搜索。海外岗位（新加坡等）也在里面，按国家分地区。"""
    info = SourceInfo("tencent", "腾讯招聘", "公司官网", "mixed", note="官网公开接口，含海外岗位")
    API = "https://careers.tencent.com/tencentcareer/api/post/Query"

    async def collect(self, criteria, cfg, settings):
        out: list[Job] = []
        async with self.client() as c:
            for kw in keywords_of(criteria):
                for page in (1, 2):
                    r = await c.get(self.API, params={"keyword": kw, "pageIndex": page, "pageSize": 20,
                                                      "language": "zh-cn", "area": "cn"})
                    r.raise_for_status()
                    posts = (r.json().get("Data") or {}).get("Posts") or []
                    for p in posts:
                        country = p.get("CountryName") or ""
                        domestic = country in ("中国", "") or country.startswith("中国")
                        pid = str(p.get("PostId"))
                        out.append(Job(
                            source="tencent", external_id=pid,
                            title=p.get("RecruitPostName") or "",
                            url=f"https://careers.tencent.com/jobdesc.html?postId={pid}",
                            company=f"腾讯 · {p['BGName']}" if p.get("BGName") else "腾讯",
                            city=p.get("LocationName") or "",
                            region=REGION_DOMESTIC if domestic else REGION_OVERSEAS,
                            job_type="fulltime",
                            experience=p.get("RequireWorkYearsName") or "",
                            tags=[t for t in (p.get("CategoryName"), p.get("ProductName")) if t],
                            description=(p.get("Responsibility") or "")[:1500],
                            platform="腾讯招聘",
                            published_at=_cn_date(p.get("LastUpdateTime")),
                            raw={"PostURL": p.get("PostURL")},
                        ))
                    if len(posts) < 20:
                        break
                    await asyncio.sleep(1)
        return out


def _cn_date(s: str | None) -> str:
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


class V2ex(Collector):
    """V2EX 的「酷工作」和「远程工作」节点。接口只给最新帖子，没有搜索，所以本地按关键词过滤；
    帖子是随手写的，交给大模型整理字段。"""
    info = SourceInfo("v2ex", "V2EX 酷工作", "社区", "domestic", note="酷工作 + 远程工作节点，本地按关键词过滤")
    NODES = ("jobs", "remote")

    async def collect(self, criteria, cfg, settings):
        kws = keywords_of(criteria)
        out: list[Job] = []
        # V2EX 的 Cloudflare 会拦「冒充浏览器」的 UA，接口请求老实报自己的名字反而能通过
        async with self.client(headers={"User-Agent": "job-radar/0.1"}) as c:
            for node in self.NODES:
                r = await c.get("https://www.v2ex.com/api/topics/show.json", params={"node_name": node})
                if r.status_code == 403:
                    raise CollectorError("blocked", "V2EX 暂时拒绝了请求，稍后会自动重试")
                r.raise_for_status()
                for t in r.json():
                    body = t.get("content") or ""
                    if not text_matches(f"{t.get('title', '')}\n{body}", kws):
                        continue
                    out.append(Job(
                        source="v2ex", external_id=str(t["id"]), title=t.get("title") or "",
                        url=t.get("url") or f"https://www.v2ex.com/t/{t['id']}",
                        remote=node == "remote", description=body[:3000], platform="V2EX",
                        published_at=_ts(t.get("created")), needs_enrich=True,
                        raw={"node": node, "author": (t.get("member") or {}).get("username"), "replies": t.get("replies")},
                    ))
                await asyncio.sleep(1)
        return out


def _ts(v) -> str:
    try:
        return datetime.fromtimestamp(int(v)).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""


class Eleduck(Collector):
    """电鸭社区的招聘分类（远程、兼职居多）。帖子带城市 / 工作方式标签。"""
    info = SourceInfo("eleduck", "电鸭", "社区", "domestic", note="远程 / 兼职为主")
    API = "https://svc.eleduck.com/api/v1/posts"

    async def collect(self, criteria, cfg, settings):
        kws = keywords_of(criteria)
        out: list[Job] = []
        async with self.client() as c:
            for page in (1, 2, 3):
                r = await c.get(self.API, params={"page": page, "category": 5})
                r.raise_for_status()
                for p in r.json().get("posts") or []:
                    if p.get("closed") or p.get("deleted"):
                        continue
                    tags = {t["tag_group"]["code"]: t["name"] for t in p.get("tags") or [] if t.get("tag_group")}
                    text = f"{p.get('title', '')}\n{p.get('summary', '')}"
                    if not text_matches(text, kws):
                        continue
                    way = tags.get("job_type", "")
                    out.append(Job(
                        source="eleduck", external_id=p["id"], title=p.get("title") or "",
                        url=f"https://eleduck.com/posts/{p['id']}",
                        city=tags.get("city", ""), remote="远程" in way,
                        job_type="parttime" if "兼职" in way else ("fulltime" if way else ""),
                        tags=[v for v in tags.values() if v],
                        description=p.get("summary") or "", platform="电鸭",
                        salary=_salary_in(p.get("title") or ""),
                        published_at=(p.get("published_at") or "")[:19], needs_enrich=True,
                    ))
                await asyncio.sleep(1)
        return out


_SAL = re.compile(r"\d+(?:\.\d+)?\s*[kK千万]?\s*[-~]\s*\d+(?:\.\d+)?\s*[kK千万](?:\s*/\s*[月年天])?|\d+\s*元\s*/\s*天")


def _salary_in(s: str) -> str:
    m = _SAL.search(s)
    return m.group(0) if m else ""


class RemoteOK(Collector):
    """RemoteOK 公开接口。条款要求注明来源并链接回原页面，我们每条都带原始链接和信源名。"""
    info = SourceInfo("remoteok", "RemoteOK", "海外与远程", "overseas", note="海外远程岗位")

    async def collect(self, criteria, cfg, settings):
        kws = keywords_of(criteria)
        async with self.client() as c:
            r = await c.get("https://remoteok.com/api")
            r.raise_for_status()
        out: list[Job] = []
        for p in r.json()[1:]:   # 第 0 条是接口说明
            text = f"{p.get('position', '')} {' '.join(p.get('tags') or [])} {p.get('description', '')[:2000]}"
            if not text_matches(text, kws):
                continue
            lo, hi = p.get("salary_min") or 0, p.get("salary_max") or 0
            salary = f"${lo // 1000}K-{hi // 1000}K/年" if lo and hi else ""
            out.append(Job(
                source="remoteok", external_id=str(p.get("id")), title=p.get("position") or "",
                url=p.get("url") or f"https://remoteok.com/remote-jobs/{p.get('id')}",
                company=p.get("company") or "", city=p.get("location") or "Remote",
                region=REGION_OVERSEAS, remote=True, salary=salary,
                # 美元年薪粗略折成人民币月薪（K），只用于筛选
                salary_min_k=round(lo * 7.1 / 12 / 1000, 1) if lo else None,
                job_type="fulltime", tags=(p.get("tags") or [])[:8],
                description=strip_html(p.get("description") or "")[:2000], platform="RemoteOK",
                published_at=(p.get("date") or "")[:19],
            ))
        return out


class HackerNews(Collector):
    """Hacker News 每月的「Who is hiring?」帖。用 Algolia 搜索接口在最新一期的评论里按关键词搜。
    每条评论是一个岗位，格式不统一，交给大模型整理。"""
    info = SourceInfo("hn", "HN Who is hiring", "海外与远程", "overseas", note="每月一期，评论即岗位")

    async def collect(self, criteria, cfg, settings):
        kws = keywords_of(criteria)
        out: list[Job] = []
        async with self.client() as c:
            r = await c.get("https://hn.algolia.com/api/v1/search_by_date",
                            params={"tags": "story,author_whoishiring", "hitsPerPage": 5})
            r.raise_for_status()
            story = next((h for h in r.json()["hits"] if "who is hiring" in (h.get("title") or "").lower()), None)
            if not story:
                return []
            sid = story["objectID"]
            for kw in kws:
                r = await c.get("https://hn.algolia.com/api/v1/search",
                                params={"tags": f"comment,story_{sid}", "query": kw, "hitsPerPage": 50})
                r.raise_for_status()
                for h in r.json()["hits"]:
                    if h.get("parent_id") and str(h["parent_id"]) != sid:
                        continue   # 只要顶层评论（岗位本身），不要回复
                    text = strip_html(h.get("comment_text") or "")
                    first = text.split("\n", 1)[0]
                    parts = [x.strip() for x in first.split("|")]
                    out.append(Job(
                        source="hn", external_id=h["objectID"], title=first[:160],
                        url=f"https://news.ycombinator.com/item?id={h['objectID']}",
                        company=parts[0][:80] if len(parts) > 1 else "",
                        region=REGION_OVERSEAS, remote="remote" in first.lower(),
                        description=text[:3000], platform="Hacker News",
                        published_at=(h.get("created_at") or "")[:19], needs_enrich=True,
                        raw={"story": story.get("title")},
                    ))
                await asyncio.sleep(0.5)
        return out
