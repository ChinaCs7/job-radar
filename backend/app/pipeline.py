"""一次检索的完整流程：采集 → 按条件筛选 → 入库（去重）→ 交给大模型整理。

筛选分两次：
- 入库前：只用平台给出的确定字段筛（排除词、地区、能解析出来的薪资和类型）。
- 大模型整理后：随手写的帖子这时才有城市、薪资等字段，再筛一次；不符合的标成 filtered（不删除，
  否则下次又会被当成新岗位、再花一次钱整理）。
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


_locks: dict[str, asyncio.Lock] = {}


async def run_source(source_id: str) -> dict:
    lock = _locks.setdefault(source_id, asyncio.Lock())
    if lock.locked():
        return {"skipped": True}
    async with lock:
        s = load_settings()
        col = REGISTRY[source_id]
        cfg = s["sources"].get(source_id, {})
        crit = s["criteria"]
        run_id = db.run_start(source_id)
        db.log("info", f"开始检索 {col.info.name}", source_id)
        try:
            jobs = await col.collect(crit, cfg, s)
        except CollectorError as e:
            db.run_finish(run_id, ok=False, error=str(e), error_kind=e.kind)
            db.log("error" if e.kind != "config" else "warn", str(e), source_id)
            return {"ok": False, "error": str(e), "kind": e.kind}
        except Exception as e:  # 网络错误等：下一轮自动重试
            msg = f"{type(e).__name__}: {e}"
            db.run_finish(run_id, ok=False, error=msg, error_kind="network")
            db.log("error", f"{col.info.name} 检索失败：{msg}", source_id)
            return {"ok": False, "error": msg, "kind": "network"}

        kept: list[Job] = []
        for j in jobs:
            # 标题或标签里写了远程 / 居家 / 线上，就算远程（很多平台没有单独的远程字段）
            if not j.remote and _REMOTE.search(f"{j.title} {' '.join(j.tags)}"):
                j.remote = True
            if not j.job_type and "兼职" in j.title:
                j.job_type = "parttime"
            if j.salary_min_k is None:
                j.salary_min_k = parse_salary_min_k(j.salary)
            # 随手写的帖子此时字段还不全，等 AI 整理后再筛
            ok, _ = passes(j.__dict__, crit) if not j.needs_enrich else (True, "")
            if ok:
                kept.append(j)
        added = db.upsert_jobs(kept)
        for jid in added:
            j = next(x for x in kept if x.id == jid)
            sc = keyword_score(j, crit["keywords"])
            if sc is not None:
                db.update_job(jid, {"score": sc, "score_reason": "关键词匹配（未经 AI 整理）"})
        db.run_finish(run_id, ok=True, found=len(jobs), added=len(added))
        db.log("info", f"{col.info.name}：找到 {len(jobs)} 条，符合条件 {len(kept)} 条，新增 {len(added)} 条", source_id)
        return {"ok": True, "found": len(jobs), "kept": len(kept), "added": len(added)}


async def enrich_pending(batch: int = 10) -> int:
    """整理一批还没整理过的岗位，返回处理条数。由调度器定期调用。"""
    s = load_settings()
    if not (s["llm"].get("api_key") and s["llm"].get("enrich")):
        return 0
    rows = db.jobs_to_enrich(batch)
    if not rows:
        return 0
    try:
        items = await llm.enrich(s["llm"], s["criteria"], rows)
    except llm.LLMError as e:
        db.log("warn", f"AI 整理失败：{e}", "llm")
        return 0
    by_i = {it.get("i"): it for it in items if isinstance(it, dict)}
    for i, row in enumerate(rows):
        it = by_i.get(i)
        if not it:
            db.update_job(row["id"], {"enriched": 1})
            continue
        verdict = it.get("verdict") if it.get("verdict") in ("recommend", "maybe", "no") else ""
        upd: dict = {"enriched": 1, "score": int(it.get("score") or 0),
                     "score_reason": it.get("reason") or "", "ai_summary": it.get("summary") or "",
                     "verdict": verdict, "verdict_reason": str(it.get("reason") or "")[:120],
                     "title_zh": str(it.get("title_zh") or "")[:200]}
        # 平台没给发布时间的（帖子类），用 AI 从正文里推断的
        if not row.get("published_at") and re.match(r"\d{4}-\d{2}-\d{2}$", str(it.get("published") or "")):
            upd["published_at"] = it["published"]
        # 用 AI 给的公司简称重新算去重 key：各平台的公司全称写法不一，简称更容易对上
        short = str(it.get("company_short") or "").strip()
        title_for_key = (it.get("title") or row["title"]) if row["needs_enrich"] else row["title"]
        if short and title_for_key:
            upd["cluster_key"] = cluster_key(short, title_for_key)
        # 所有岗位：平台没给的「工作性质」「是否远程」用 AI 的判断补上，再按条件重新筛一次
        # （例如 We Work Remotely 没有类型字段，远程全职会被 AI 标成 fulltime，然后被「只要兼职」过滤掉）
        if not row["needs_enrich"]:
            if not row.get("job_type") and it.get("job_type") in ("fulltime", "parttime", "intern", "contract"):
                upd["job_type"] = it["job_type"]
            if it.get("remote") and not row["remote"]:
                upd["remote"] = 1
            merged = {**row, **upd, "remote": bool(upd.get("remote", row["remote"]))}
            ok, why = passes(merged, s["criteria"])
            if not ok:
                upd["status"], upd["score_reason"] = "filtered", why
            elif row.get("status") == "filtered":
                upd["status"] = "new"   # 重新整理后又符合条件了（比如改了搜索条件）
        if row["needs_enrich"]:
            # 随手写的帖子：用模型抽出的字段补齐；平台给的结构化字段优先保留
            for f in ("title", "company", "city", "salary", "job_type"):
                if it.get(f) and (f == "title" or not row.get(f)):
                    upd[f] = str(it[f])[:200]
            if it.get("region") in (REGION_DOMESTIC, REGION_OVERSEAS):
                upd["region"] = it["region"]
            upd["remote"] = int(bool(it.get("remote")) or row["remote"])
            upd["tags"] = (it.get("tags") or [])[:5] or row["tags"]
            upd["salary_min_k"] = parse_salary_min_k(upd.get("salary") or row["salary"])
            if "cluster_key" not in upd:
                upd["cluster_key"] = cluster_key(upd.get("company") or row["company"], upd.get("title") or row["title"])
            merged = {**row, **upd, "remote": bool(upd["remote"])}
            ok, why = passes(merged, s["criteria"])
            if it.get("is_job") is False:
                upd["status"], upd["score_reason"] = "filtered", "AI 判断不是招聘信息"
            elif not ok:
                upd["status"], upd["score_reason"] = "filtered", why
        db.update_job(row["id"], upd)
    db.log("info", f"AI 整理了 {len(rows)} 条", "llm")
    return len(rows)
