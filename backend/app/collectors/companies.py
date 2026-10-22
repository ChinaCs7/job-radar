"""公司官网：直接请求各家招聘官网的公开查询接口，不需要浏览器、不需要登录，最稳定。

一个信源（company）里包含多家公司，每家可以单独开关。每条岗位的平台名写成「字节跳动官网」这样。

公司的接口按招聘系统分几类：
- feishu：飞书招聘（字节、小米，以及很多用飞书招聘的公司）。先取 csrf token，再按关键词搜。
  地址形如 jobs.bytedance.com、xxx.jobs.feishu.cn；可以在界面里自己添加。
- tencent / meituan / netease / mihoyo：各家自己的接口。
"""
from __future__ import annotations

import asyncio

from ..models import REGION_DOMESTIC, REGION_OVERSEAS, Job
from .base import Collector, CollectorError, SourceInfo, keywords_of
from .simple import Tencent

# 默认公司清单。feishu 类型需要：host、channel、path（网址里 position 前面那一段）、portal_type
DEFAULT_COMPANIES = [
    {"id": "tencent", "name": "腾讯", "type": "tencent", "enabled": True},
    {"id": "bytedance", "name": "字节跳动", "type": "feishu", "enabled": True,
     "host": "jobs.bytedance.com", "channel": "office", "path": "society", "portal_type": 2, "detail": "experienced"},
    {"id": "xiaomi", "name": "小米", "type": "feishu", "enabled": True,
     "host": "xiaomi.jobs.f.mioffice.cn", "channel": "saas-career", "path": "index", "portal_type": 6},
    {"id": "meituan", "name": "美团", "type": "meituan", "enabled": True},
    {"id": "netease", "name": "网易", "type": "netease", "enabled": True},
    {"id": "mihoyo", "name": "米哈游", "type": "mihoyo", "enabled": True},
]


def _ms_date(v) -> str:
    from datetime import datetime
    try:
        return datetime.fromtimestamp(int(v) / 1000).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""


class Companies(Collector):
    info = SourceInfo("company", "公司官网", "公司官网", "mixed",
                      note="腾讯、字节、小米、美团、网易、米哈游的招聘官网；飞书招聘的公司可以自己添加")

    async def collect(self, criteria, cfg, settings):
        kws = keywords_of(criteria)
        companies = [c for c in (cfg.get("companies") or DEFAULT_COMPANIES) if c.get("enabled", True)]
        out: list[Job] = []
        errors: list[str] = []
        async with self.client() as http:
            for comp in companies:
                fn = getattr(self, f"_{comp['type']}", None)
                if not fn:
                    continue
                try:
                    for kw in kws:
                        out += await fn(http, comp, kw, criteria, cfg, settings)
                        await asyncio.sleep(0.8)
                except Exception as e:  # 一家公司出错不影响其他公司
                    errors.append(f"{comp['name']}：{type(e).__name__} {e}"[:120])
        if errors and not out:
            raise CollectorError("network", "；".join(errors))
        if errors:
            from .. import db
            db.log("warn", "部分公司官网检索失败：" + "；".join(errors), "company")
        return out

    async def _tencent(self, http, comp, kw, criteria, cfg, settings):
        jobs = await Tencent().collect({**criteria, "keywords": [kw]}, cfg, settings)
        for j in jobs:
            j.source, j.platform = "company", "腾讯官网"
            j.external_id = f"tencent-{j.external_id}"
        return jobs

    async def _feishu(self, http, comp, kw, criteria, cfg, settings):
        host = comp["host"]
        h = {"portal-channel": comp.get("channel", "saas-career"), "portal-platform": "pc",
             "website-path": comp.get("path", "index"), "env": "undefined", "Referer": f"https://{host}/"}
        # 每家公司单独一个客户端：多家飞书招聘的 csrf cookie 同名，放在一起会冲突
        async with self.client() as fh:
            r = await fh.post(f"https://{host}/api/v1/csrf/token", json={"portal_entrance": 1}, headers=h)
            r.raise_for_status()
            token = (fh.cookies.get("atsx-csrf-token") or "").replace("%3D", "=")
            return await self._feishu_search(fh, comp, kw, h, token)

    async def _feishu_search(self, http, comp, kw, h, token):
        host = comp["host"]
        body = {"keyword": kw, "limit": 30, "offset": 0, "job_category_id_list": [], "tag_id_list": [],
                "location_code_list": [], "subject_id_list": [], "recruitment_id_list": [],
                "portal_type": comp.get("portal_type", 6), "job_function_id_list": [], "storefront_id_list": [],
                "portal_entrance": 1}
        r = await http.post(f"https://{host}/api/v1/search/job/posts", json=body, headers={**h, "x-csrf-token": token})
        r.raise_for_status()
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(d.get("message") or d.get("code"))
        detail = comp.get("detail") or comp.get("path", "index")
        out = []
        for p in (d.get("data") or {}).get("job_post_list") or []:
            city = ((p.get("city_info") or {}).get("name")) or ""
            cities = [c.get("name") for c in (p.get("city_list") or []) if c.get("name")]
            rt = ((p.get("recruit_type") or {}).get("name")) or ""
            out.append(Job(
                source="company", external_id=f"{comp['id']}-{p['id']}", title=p.get("title") or "",
                url=f"https://{host}/{detail}/position/{p['id']}/detail",
                company=comp["name"], city="、".join(cities) or city,
                region=REGION_OVERSEAS if any(x in (city + "".join(cities)) for x in ("新加坡", "美国", "伦敦", "Singapore")) else REGION_DOMESTIC,
                job_type="intern" if "实习" in rt else "fulltime",
                tags=[x for x in (((p.get("job_category") or {}).get("name")),) if x],
                description=f"{p.get('description') or ''}\n{p.get('requirement') or ''}"[:2500],
                platform=f"{comp['name']}官网", published_at=_ms_date(p.get("publish_time")),
            ))
        return out

    async def _meituan(self, http, comp, kw, criteria, cfg, settings):
        body = {"page": {"pageNo": 1, "pageSize": 30}, "jobShareType": "1", "keywords": kw, "cityList": [],
                "department": [], "jfJgList": [], "jobType": [{"code": "3", "subCode": []}], "typeCode": [], "specialCode": []}
        r = await http.post("https://zhaopin.meituan.com/api/official/job/getJobList", json=body,
                            headers={"x-requested-with": "XMLHttpRequest", "Referer": "https://zhaopin.meituan.com/web/social"})
        r.raise_for_status()
        out = []
        for p in ((r.json().get("data") or {}).get("list") or []):
            jid = p.get("jobUnionId")
            out.append(Job(
                source="company", external_id=f"meituan-{jid}", title=p.get("name") or "",
                url=f"https://zhaopin.meituan.com/web/position/detail?jobUnionId={jid}&highlightType=social",
                company="美团", city="、".join(c.get("name") for c in (p.get("cityList") or []) if c.get("name")),
                job_type="fulltime", tags=[x for x in (p.get("jobFamily"),) if x],
                description=f"{p.get('jobDuty') or ''}\n{p.get('jobRequirement') or ''}"[:2500],
                platform="美团官网", published_at=_ms_date(p.get("refreshTime") or p.get("firstPostTime")),
            ))
        return out

    async def _netease(self, http, comp, kw, criteria, cfg, settings):
        r = await http.post("https://hr.163.com/api/hr163/position/queryPage",
                            json={"currentPage": 1, "pageSize": 30, "keyword": kw})
        r.raise_for_status()
        out = []
        for p in (((r.json().get("data") or {}).get("list")) or []):
            out.append(Job(
                source="company", external_id=f"netease-{p['id']}", title=p.get("name") or "",
                url=f"https://hr.163.com/job-detail.html?id={p['id']}&lang=zh",
                company=f"网易 · {p['firstDepName']}" if p.get("firstDepName") else "网易",
                city="、".join(p.get("workPlaceNameList") or []) if p.get("workPlaceNameList") else "",
                experience=p.get("reqWorkYearsName") or "", education=p.get("reqEducationName") or "",
                job_type="fulltime", tags=[x for x in (p.get("firstPostTypeName"),) if x],
                description=f"{p.get('description') or ''}\n{p.get('requirement') or ''}"[:2500],
                platform="网易官网", published_at=_ms_date(p.get("updateTime")),
            ))
        return out

    async def _mihoyo(self, http, comp, kw, criteria, cfg, settings):
        r = await http.post("https://ats.openout.mihoyo.com/ats-portal/v1/job/list",
                            json={"keyword": kw, "pageNo": 1, "pageSize": 30, "channelDetailIds": [1], "hireType": 0})
        r.raise_for_status()
        out = []
        for p in (((r.json().get("data") or {}).get("list")) or []):
            out.append(Job(
                source="company", external_id=f"mihoyo-{p['id']}", title=p.get("title") or "",
                url=f"https://jobs.mihoyo.com/#/position/{p['id']}", company="米哈游",
                city="、".join(a.get("addressDetail") for a in (p.get("addressDetailList") or []) if a.get("addressDetail")),
                job_type="fulltime" if p.get("jobNature") == "全职" else "", tags=[x for x in (p.get("competencyType"),) if x],
                description=(p.get("jobSummary") or "")[:2500], platform="米哈游官网",
            ))
        return out
