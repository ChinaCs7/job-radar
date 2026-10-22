"""全网搜索兜底：用 DeepSeek Search API 按「关键词 + 招聘 + site:平台」搜小红书、脉脉、知乎、即刻、牛客等。

这些平台没法稳定直接抓，但搜索引擎收录了它们的帖子。搜出来的只是网页摘要，
不一定是招聘信息，所以全部标成 needs_enrich，交给大模型判断「是不是岗位」并抽字段，
不是岗位的会被丢掉。

接口：POST https://api.deepseek.com/v1/tools/search，和聊天接口用同一个 key，按次计费。
每轮最多发 max_queries 次请求，控制花费。
"""
from __future__ import annotations

import hashlib
from urllib.parse import urlparse

import httpx

from ..models import Job
from .base import Collector, CollectorError, SourceInfo, keywords_of

SITE_LABELS = {
    "xiaohongshu.com": "小红书", "maimai.cn": "脉脉", "zhihu.com": "知乎", "okjike.com": "即刻",
    "nowcoder.com": "牛客", "weibo.com": "微博", "douban.com": "豆瓣", "juejin.cn": "掘金",
    "v2ex.com": "V2EX", "linkedin.com": "LinkedIn", "zhipin.com": "Boss 直聘", "liepin.com": "猎聘",
    "zhaopin.com": "智联招聘", "51job.com": "前程无忧", "lagou.com": "拉勾", "github.com": "GitHub",
}


def site_label(url: str, fallback: str = "") -> str:
    host = urlparse(url).netloc.lower()
    for dom, name in SITE_LABELS.items():
        if host == dom or host.endswith("." + dom):
            return name
    return fallback or host.removeprefix("www.")


class WebSearch(Collector):
    info = SourceInfo("websearch", "全网搜索（DeepSeek）", "全网搜索", "mixed", needs_key=True,
                      note="付费（每千次 5 元）：DeepSeek 自己的搜索引擎，不用开浏览器，结果带摘要")

    async def collect(self, criteria, cfg, settings):
        llm = settings["llm"]
        if not llm.get("api_key"):
            raise CollectorError("config", "全网搜索需要先在「账号与密钥」里填 DeepSeek API key")
        kws = keywords_of(criteria)
        cities = criteria.get("cities") or []
        sites = cfg.get("sites") or []
        queries: list[str] = []
        for kw in kws:
            for s in sites:
                queries.append(f"{kw} 招聘 site:{s}")
            queries.append(f"{kw} 招聘 {' '.join(cities[:2])}".strip())
        queries = queries[: int(cfg.get("max_queries", 12))]

        out: list[Job] = []
        async with httpx.AsyncClient(timeout=30) as c:
            for q in queries:
                r = await c.post(f"{llm['base_url'].rstrip('/')}/v1/tools/search",
                                 headers={"Authorization": f"Bearer {llm['api_key']}"},
                                 json={"query": q, "count": int(cfg.get("count", 10))})
                if r.status_code == 401:
                    raise CollectorError("config", "DeepSeek key 无效，请在「账号与密钥」里检查")
                if r.status_code == 402:
                    raise CollectorError("config", "DeepSeek 账户余额不足")
                r.raise_for_status()
                from ..llm import record_usage
                record_usage(llm, "search", None, search=True)
                for item in r.json().get("results") or []:
                    url = item.get("url") or ""
                    from .webpages import looks_like_job
                    if not url or not looks_like_job(f"{item.get('title', '')} {item.get('snippet', '')}"):
                        continue
                    out.append(Job(
                        source="websearch", external_id=hashlib.sha1(url.encode()).hexdigest()[:20],
                        title=item.get("title") or "", url=url,
                        description=(item.get("summary") or item.get("snippet") or "")[:2000],
                        platform=site_label(url, item.get("site_name") or ""),
                        published_at=(item.get("date") or "")[:19], needs_enrich=True,
                        raw={"query": q, "rerank_score": item.get("rerank_score"), "authority": item.get("authority")},
                    ))
        return out
