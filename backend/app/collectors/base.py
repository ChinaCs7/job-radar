"""采集器基类。

每个信源一个采集器，只负责一件事：按搜索条件把平台上的数据取回来，转成 Job 列表。
筛选、去重、打分在 pipeline.py 里统一做，采集器不管。

出错时抛 CollectorError 并标明类型，界面据此给出不同的提示：
- login：需要登录或登录失效 → 引导去「账号」页
- blocked：被平台风控 / 要求验证 → 暂停这个信源，提示人工处理，不要重试
- config：缺配置（比如没填 key）
- network：网络问题，下一轮自动重试
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from ..models import Job

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


class CollectorError(Exception):
    def __init__(self, kind: str, message: str, partial=None):
        super().__init__(message)
        self.kind = kind
        self.partial = partial or []


@dataclass
class SourceInfo:
    id: str
    name: str
    group: str            # 招聘平台 / 公司官网 / 社区 / 海外与远程 / 全网搜索
    region: str           # 主要覆盖：domestic / overseas / mixed
    needs_login: bool = False
    needs_key: bool = False
    note: str = ""


class Collector:
    info: SourceInfo

    async def collect(self, criteria: dict, cfg: dict, settings: dict) -> list[Job]:
        raise NotImplementedError

    @staticmethod
    def client(headers: dict | None = None, **kw) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=20, headers={"User-Agent": UA, **(headers or {})}, follow_redirects=True, **kw)


def keywords_of(criteria: dict) -> list[str]:
    kws = [k.strip() for k in criteria.get("keywords", []) if k.strip()]
    if not kws:
        raise CollectorError("config", "还没有设置搜索关键词")
    return kws


def text_matches(text: str, keywords: list[str]) -> bool:
    """本地关键词匹配：用于没有搜索接口、只能拉最新列表的信源（V2EX、电鸭、RemoteOK）。
    关键词里的空格当作「都要出现」，例如「AI Agent」要求 ai 和 agent 都在。"""
    t = text.lower()
    for kw in keywords:
        parts = [p for p in re.split(r"\s+", kw.lower()) if p]
        if parts and all(p in t for p in parts):
            return True
    return False


_TAG = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    s = re.sub(r"<(br|p|/p|li)[^>]*>", "\n", s or "", flags=re.I)
    s = _TAG.sub("", s)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#x27;", "'"), ("&#x2F;", "/"), ("&nbsp;", " ")):
        s = s.replace(a, b)
    return re.sub(r"\n{3,}", "\n\n", s).strip()
