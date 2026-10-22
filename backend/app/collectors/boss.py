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
- 返回了岗位但薪资全为空 → 没登录（未登录时 Boss 不给薪资）
- 页面被跳到登录页或安全验证页 → login / blocked
"""
from __future__ import annotations

import asyncio
import base64
import json
import random
from pathlib import Path
from urllib.parse import urlencode

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
    jobs = (data.get("zpData") or {}).get("jobList") or []
    if not jobs:
        return "empty", "没有符合条件的岗位"
    if not any((j.get("salaryDesc") or "").strip() for j in jobs):
        return "login", "Boss 未登录（拿不到薪资）"
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

    async def next(self, timeout: float) -> dict | None:
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while (left := end - loop.time()) > 0:
            try:
                ev = await asyncio.wait_for(self.page.events.get(), left)
            except asyncio.TimeoutError:
                return None
            m, p = ev["method"], ev.get("params", {})
            if m == "Network.responseReceived" and JOBLIST in p.get("response", {}).get("url", ""):
                self.pending.add(p["requestId"])
            elif m == "Network.loadingFinished" and p.get("requestId") in self.pending:
                self.pending.discard(p["requestId"])
                body = await self.page.send("Network.getResponseBody", {"requestId": p["requestId"]})
                text = body.get("body", "")
                if body.get("base64Encoded"):
                    text = base64.b64decode(text).decode("utf-8", "replace")
                try:
                    return json.loads(text)
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
        kws = keywords_of(criteria)
        cities = [c for c in (city_code(x) for x in criteria.get("cities") or []) if c] or [NATIONWIDE]
        combos = [(k, c) for k in kws for c in cities][: int(cfg.get("max_combos", 3))]
        max_pages = int(cfg.get("max_pages", 1))
        out: list[Job] = []
        async with browser.browser_slot(), browser.CDPPage() as page:
            await page.send("Network.enable")
            await page.send("Page.enable")
            cap = _Capture(page)
            for i, (kw, city) in enumerate(combos):
                if i:
                    await asyncio.sleep(random.uniform(6, 15))   # 组合之间停一会儿，像人在换条件
                await page.send("Page.navigate", {"url": search_url(kw, city)})
                for pg in range(1, max_pages + 1):
                    if pg > 1:
                        await asyncio.sleep(random.uniform(2, 4))
                        await _human_scroll(page)
                    data = await cap.next(25 if pg == 1 else 15)
                    state, why = classify(data)
                    if state in ("blocked", "login"):
                        raise CollectorError(state, why)
                    if state != "ok":
                        break
                    out += [j for j in map(map_job, data["zpData"]["jobList"]) if j]
                    if data["zpData"].get("hasMore") is False:
                        break
        return out
