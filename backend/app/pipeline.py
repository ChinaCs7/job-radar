"""方案筛选规则。执行流程位于 execution：采集→事实去重入库→方案初筛→AI 评估。
不符合条件的候选保留过滤理由，避免重抓后重复评估，也便于追查漏项。
"""
from __future__ import annotations

import asyncio
import re

from . import db, llm
from .collectors import REGISTRY, CollectorError
from .config import load_settings
from .models import REGION_DOMESTIC, REGION_OVERSEAS, Job, cluster_key, parse_salary_min_k


_REMOTE = re.compile(r"远程|居家|在家办公|线上办公|可远程|remote|work from home|wfh", re.I)


def passes(j: dict, c: dict) -> tuple[bool, str]:
    """j 是 Job 的字段字典（入库前）或数据库行（整理后），两者字段名一致。"""
    text = f"{j.get('title', '')} {j.get('company', '')}"
    for w in c.get("exclude") or []:
        if w and w.lower() in text.lower():
            return False, f"含排除词「{w}」"
    regions = c.get("regions") or {}
    region_ok = (j.get("region") == REGION_DOMESTIC and regions.get("domestic")) or \
                (j.get("region") == REGION_OVERSEAS and regions.get("overseas")) or \
                (j.get("remote") and regions.get("remote"))
    if not region_ok:
        return False, "地区不在范围内"
    cities = [x.strip().removesuffix("市") for x in c.get("cities") or [] if x.strip()]
    city = j.get("city") or ""
    if cities and city and j.get("region") == REGION_DOMESTIC and not j.get("remote"):
        if not any(x in city for x in cities):
            return False, f"城市「{city}」不在范围内"
    lo = j.get("salary_min_k")
    if c.get("salary_min_k") and lo is not None and lo < c["salary_min_k"] * 0.8:
        # 留 20% 余量：薪资区间下限常常压得偏低，上限可能够
        return False, f"薪资下限 {lo}K 低于要求"
    jt = j.get("job_type")
    if jt and c.get("job_types") and jt not in c["job_types"]:
        return False, "岗位类型不在范围内"
    age = age_days(j.get("published_at") or "")
    if c.get("max_age_days") and age is not None and age > int(c["max_age_days"]):
        return False, f"发布于 {age} 天前，太旧了"
    return True, ""


def age_days(published: str) -> int | None:
    """发布时间距今几天；格式不认识就返回 None（不因此过滤）。"""
    from datetime import date
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", published or "")
    if not m:
        return None
    try:
        return (date.today() - date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days
    except ValueError:
        return None


def keyword_score(j: Job, keywords: list[str]) -> int | None:
    """没有大模型时的粗略匹配分：关键词在标题里 70，只在正文里 50。"""
    t, d = j.title.lower(), j.description.lower()
    if any(k.lower() in t for k in keywords):
        return 70
    if any(k.lower() in d for k in keywords):
        return 50
    return None


from .execution import run_source, enrich_pending
