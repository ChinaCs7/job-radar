"""统一的岗位格式。每个采集器都把自己平台的数据转成 Job，后面的去重、打分、展示只认这一种格式。"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

# 地区：国内 / 海外；远程是单独的标记（国内远程、海外远程都存在）
REGION_DOMESTIC = "domestic"
REGION_OVERSEAS = "overseas"

JOB_TYPES = {"fulltime": "全职", "parttime": "兼职", "intern": "实习", "contract": "合同 / 外包"}


@dataclass
class Job:
    source: str                 # 采集器 id，例：boss / tencent / websearch
    external_id: str            # 平台内的 id；没有就用链接
    title: str
    url: str                    # 原始链接，必填
    company: str = ""
    city: str = ""
    region: str = REGION_DOMESTIC
    remote: bool = False
    salary: str = ""            # 原文，例：「25-40K·14薪」
    salary_min_k: float | None = None   # 解析出的月薪下限（K，人民币口径近似），用于筛选
    job_type: str = ""          # fulltime / parttime / intern / contract；空 = 未知
    experience: str = ""
    education: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""       # 摘要或正文开头
    platform: str = ""          # 内容实际所在的站点；websearch 来的会是「小红书」之类
    published_at: str = ""      # 平台给的发布时间（ISO），没有就空
    needs_enrich: bool = False  # 内容是随手写的帖子，需要大模型整理
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.source}:{self.external_id}".encode()).hexdigest()[:16]

    @property
    def cluster_key(self) -> str:
        """展示归组：公司、岗位名、城市和类型；不覆盖原始平台记录。"""
        return cluster_key(self.company, self.title, self.city, self.job_type)


_PUNCT = re.compile(r"[\s\-_·•|｜/\\()（）\[\]【】,，.。:：!！?？'\"]+")
_NOISE = re.compile(r"(急招|诚聘|高薪|直招|内推|远程|base.{0,4}|hc\d+)", re.I)


_CITIES = ("北京", "上海", "深圳", "广州", "杭州", "厦门", "成都", "武汉", "南京", "西安", "苏州", "天津", "重庆",
           "长沙", "合肥", "珠海", "香港", "新加坡", "中国")
_CO_SUFFIX = ("信息技术", "网络技术", "网络科技", "科技", "技术", "网络", "信息", "有限责任", "有限", "责任", "公司",
              "股份", "集团", "控股", "inc", "ltd", "llc", "corp")
_TITLE_NOISE = re.compile(r"(社招|校招|\d+(\.\d+)?\s*([-~至]\s*\d+(\.\d+)?)?\s*[kK千万][^\s]{0,6}|20\d\d届?)")


def norm_company(company: str) -> str:
    """「腾讯科技（深圳）有限公司」「腾讯 · CSIG」→「腾讯」：去掉部门、括号、城市和公司后缀。"""
    c = re.split(r"\s*[·•|｜]\s*", (company or "").lower())[0]
    c = re.sub(r"[（(][^）)]*[）)]", "", c)
    for w in _CITIES + _CO_SUFFIX:
        c = c.replace(w, "")
    return _PUNCT.sub("", c)


def norm_title(title: str) -> str:
    """去掉岗位名里的城市、括号里的地点 / 急招、薪资、届别，只留岗位本身。"""
    t = (title or "").lower()
    t = re.sub(r"[（(\[【][^）)\]】]*[）)\]】]", lambda m: "" if any(w in m.group(0) for w in _CITIES + ("急", "远程", "招")) else m.group(0), t)
    t = _TITLE_NOISE.sub("", _NOISE.sub("", t))
    for w in _CITIES:
        t = re.sub(rf"[-_—]\s*{w}\s*$", "", t)
    return _PUNCT.sub("", t)


def cluster_key(company: str, title: str, city: str = '', job_type: str = '') -> str:
    """同公司、岗位名、城市和类型的记录保守归组，身份仍由平台 ID 区分。"""
    c, t = norm_company(company), norm_title(title)
    if not c or not t:
        return ""
    return hashlib.sha1(f"{c}|{t}|{city.strip().removesuffix('市')}|{job_type}".encode()).hexdigest()[:16]


_K = re.compile(r"(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*([kK千])")
_K1 = re.compile(r"(\d+(?:\.\d+)?)\s*([kK千])")
_WAN = re.compile(r"(\d+(?:\.\d+)?)\s*[-~至到]?\s*(\d+(?:\.\d+)?)?\s*万")
_DAY = re.compile(r"(\d+)\s*[-~]?\s*(\d+)?\s*元\s*/\s*天")


def parse_salary_min_k(text: str) -> float | None:
    """尽力从薪资原文里取月薪下限（K）。解析不了就返回 None，筛选时不会因此丢掉岗位。"""
    if not text:
        return None
    s = text.replace(" ", "")
    if m := _DAY.search(s):
        return round(int(m.group(1)) * 21.75 / 1000, 1)
    if m := _K.search(s):
        return float(m.group(1))
    if m := _WAN.search(s):
        lo = float(m.group(1))
        # 「30-50万/年」按年薪折算；「2-3万」默认月薪
        return round(lo * 10 / 12, 1) if ("年" in s or lo >= 10) else lo * 10
    if m := _K1.search(s):
        return float(m.group(1))
    return None
