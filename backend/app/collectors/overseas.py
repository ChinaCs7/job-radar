"""海外招聘平台：借 JobSpy（MIT）一次搜 LinkedIn / Indeed / Google Jobs 等。

JobSpy 是同步库，内部用 requests，所以放到线程里跑，不阻塞调度器。
LinkedIn 对频繁请求很敏感，默认间隔 3 小时，每个关键词只取 20 条。
"""
from __future__ import annotations

import asyncio
import math

from ..models import REGION_OVERSEAS, Job
from .base import Collector, CollectorError, SourceInfo, keywords_of, strip_html, text_matches

SITE_NAMES = {"linkedin": "LinkedIn", "indeed": "Indeed", "google": "Google Jobs",
              "glassdoor": "Glassdoor", "zip_recruiter": "ZipRecruiter"}


def _clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


class JobSpy(Collector):
    info = SourceInfo("jobspy", "LinkedIn / Indeed", "海外与远程", "overseas",
                      note="经 JobSpy 采集 LinkedIn、Indeed、Google Jobs")

    async def collect(self, criteria, cfg, settings):
        kws = keywords_of(criteria)
        sites = cfg.get("sites") or ["linkedin", "indeed"]
        location = cfg.get("location") or ""
        country = cfg.get("country_indeed") or "USA"
        try:
            from jobspy import scrape_jobs
        except ImportError as e:
            raise CollectorError("config", f"缺少 JobSpy：{e}")

        def run(kw: str):
            return scrape_jobs(site_name=sites, search_term=kw, google_search_term=f"{kw} jobs {location}".strip(),
                               location=location or None, results_wanted=int(cfg.get("results", 20)),
                               hours_old=int(cfg.get("hours_old", 72)), country_indeed=country,
                               is_remote=bool(cfg.get("remote_only", False)), verbose=0)

        out: list[Job] = []
        for kw in kws:
            df = await asyncio.to_thread(run, kw)
            for rec in df.to_dict("records"):
                rec = {k: _clean(v) for k, v in rec.items()}
                site = rec.get("site") or ""
                lo, interval = rec.get("min_amount"), rec.get("interval") or ""
                cur = rec.get("currency") or ""
                salary = ""
                if lo:
                    hi = rec.get("max_amount")
                    salary = f"{cur} {int(lo):,}{'-' + format(int(hi), ',') if hi else ''} / {interval}".strip()
                monthly_k = None
                if lo and cur == "USD":
                    per_year = {"yearly": 1, "monthly": 12, "hourly": 2080, "weekly": 52, "daily": 260}.get(interval, 1)
                    monthly_k = round(lo * per_year * 7.1 / 12 / 1000, 1)
                out.append(Job(
                    source="jobspy", external_id=str(rec.get("id") or rec.get("job_url")),
                    title=rec.get("title") or "", url=rec.get("job_url") or "",
                    company=rec.get("company") or "", city=rec.get("location") or "",
                    region=REGION_OVERSEAS, remote=bool(rec.get("is_remote")),
                    salary=salary, salary_min_k=monthly_k,
                    job_type={"fulltime": "fulltime", "parttime": "parttime", "internship": "intern",
                              "contract": "contract"}.get(str(rec.get("job_type") or "").split(",")[0], ""),
                    description=(rec.get("description") or "")[:3000],
                    platform=SITE_NAMES.get(site, site), published_at=str(rec.get("date_posted") or ""),
                    raw={"site": site, "job_url_direct": rec.get("job_url_direct")},
                ))
        return [j for j in out if j.url]


class Remotive(Collector):
    """Remotive 公开接口（远程岗位）。条款要求链接回原页面并注明来源。"""
    info = SourceInfo("remotive", "Remotive", "海外与远程", "overseas", note="海外远程岗位")

    async def collect(self, criteria, cfg, settings):
        out: list[Job] = []
        async with self.client(headers={"User-Agent": "job-radar/0.1"}) as c:
            for kw in keywords_of(criteria):
                r = await c.get("https://remotive.com/api/remote-jobs", params={"search": kw, "limit": 50})
                r.raise_for_status()
                for p in r.json().get("jobs") or []:
                    out.append(Job(
                        source="remotive", external_id=str(p["id"]), title=p.get("title") or "", url=p.get("url") or "",
                        company=p.get("company_name") or "", city=p.get("candidate_required_location") or "Remote",
                        region=REGION_OVERSEAS, remote=True, salary=p.get("salary") or "",
                        job_type={"full_time": "fulltime", "part_time": "parttime", "contract": "contract",
                                  "internship": "intern"}.get(p.get("job_type") or "", ""),
                        tags=(p.get("tags") or [])[:6], description=strip_html(p.get("description") or "")[:2500],
                        platform="Remotive", published_at=(p.get("publication_date") or "")[:19],
                    ))
                await asyncio.sleep(1)
        return out


class Himalayas(Collector):
    info = SourceInfo("himalayas", "Himalayas", "海外与远程", "overseas", note="海外远程岗位，带薪资和时区要求")

    async def collect(self, criteria, cfg, settings):
        out: list[Job] = []
        async with self.client(headers={"User-Agent": "job-radar/0.1"}) as c:
            for kw in keywords_of(criteria):
                r = await c.get("https://himalayas.app/jobs/api/search", params={"q": kw})
                r.raise_for_status()
                for p in r.json().get("jobs") or []:
                    url = p.get("guid") or p.get("applicationLink") or ""
                    lo, hi, cur = p.get("minSalary"), p.get("maxSalary"), p.get("currency") or ""
                    salary = f"{cur} {lo:,}-{hi:,} / {p.get('salaryPeriod') or ''}".strip() if lo and hi else ""
                    out.append(Job(
                        source="himalayas", external_id=url, title=p.get("title") or "", url=url,
                        company=p.get("companyName") or "", city="、".join(p.get("locationRestrictions") or []) or "Remote",
                        region=REGION_OVERSEAS, remote=True, salary=salary,
                        salary_min_k=round(lo * 7.1 / 12 / 1000, 1) if lo and cur == "USD" and p.get("salaryPeriod") == "annual" else None,
                        job_type="fulltime" if "Full" in (p.get("employmentType") or "") else "",
                        tags=(p.get("categories") or [])[:5],
                        description=strip_html(p.get("description") or "")[:2500] or (p.get("excerpt") or ""),
                        platform="Himalayas", published_at=_ts_iso(p.get("pubDate")),
                    ))
                await asyncio.sleep(1)
        return out


class WeWorkRemotely(Collector):
    """We Work Remotely 的 RSS（编程、DevOps、产品等分类），本地按关键词过滤。"""
    info = SourceInfo("wwr", "We Work Remotely", "海外与远程", "overseas", note="海外远程岗位（RSS）")
    FEEDS = ("remote-programming-jobs", "remote-full-stack-programming-jobs", "remote-back-end-programming-jobs",
             "remote-devops-sysadmin-jobs", "remote-product-jobs")

    async def collect(self, criteria, cfg, settings):
        import xml.etree.ElementTree as ET
        kws = keywords_of(criteria)
        out: list[Job] = []
        async with self.client(headers={"User-Agent": "job-radar/0.1"}) as c:
            for feed in self.FEEDS:
                r = await c.get(f"https://weworkremotely.com/categories/{feed}.rss")
                r.raise_for_status()
                for item in ET.fromstring(r.content).iter("item"):
                    g = lambda t: (item.findtext(t) or "").strip()
                    title, desc = g("title"), strip_html(g("description"))
                    if not text_matches(f"{title}\n{desc}", kws):
                        continue
                    company, _, role = title.partition(": ")
                    out.append(Job(
                        source="wwr", external_id=g("guid") or g("link"), title=role or title, url=g("link"),
                        company=company if role else "", city=g("region") or "Remote", region=REGION_OVERSEAS,
                        remote=True, tags=[g("category")] if g("category") else [], description=desc[:2500],
                        platform="We Work Remotely", published_at=_rfc822(g("pubDate")),
                    ))
                await asyncio.sleep(0.5)
        return out


def _rfc822(v: str) -> str:
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(v).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""


def _ts_iso(v) -> str:
    from datetime import datetime
    try:
        return datetime.fromtimestamp(int(v)).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""
