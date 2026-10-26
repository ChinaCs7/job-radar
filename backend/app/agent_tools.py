"""AI 助手的「写」能力：帮使用者改搜索条件 / 开关信源。

关键设计（和读工具不同）：模型不能直接改设置。它只能调用 propose_settings 提出一个方案，
方案先存在这里，界面弹出确认卡片（当前 → 建议），使用者点「应用」后，由 apply_proposal 这段代码
校验参数再写入。模型说「已经帮你改好了」不算数，真正生效只有使用者点按钮这一条路。
"""
from __future__ import annotations

import io
import json
from . import db, plans
from .plan_context import current_plan, scope
import re
import uuid
import zipfile

from .collectors import REGISTRY
from .config import load_settings, save_settings

_PROPOSALS: dict[str, dict] = {}   # 进程内保存；重启后旧卡片会提示「已过期」

FIELD_LABEL = {"keywords": "关键词", "cities": "城市", "salary_min_k": "月薪下限", "job_types": "岗位类型",
               "regions": "地区", "exclude": "排除词", "max_age_days": "发布时间", "profile": "关于你"}
TYPE_LABEL = {"fulltime": "全职", "parttime": "兼职", "intern": "实习", "contract": "合同 / 外包"}
AGE_OPTIONS = (0, 3, 7, 14, 30, 60)


# ---------- 读附件（简历） ----------

_PHONE = re.compile(r"(?<!\d)(\+?86[-\s]?)?1[3-9]\d[-\s]?\d{4}[-\s]?\d{4}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_IDCARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")


def mask_contacts(text: str) -> tuple[str, int]:
    """发给大模型之前去掉手机号、邮箱、身份证号。返回（处理后的文字，去掉了几处）。"""
    n = 0
    for pat, rep in ((_EMAIL, "[邮箱已隐藏]"), (_IDCARD, "[证件号已隐藏]"), (_PHONE, "[手机号已隐藏]")):
        text, k = pat.subn(rep, text)
        n += k
    return text, n


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    if name.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", "ignore")
    raise ValueError("只支持 PDF、Word（.docx）、TXT、Markdown")


# ---------- 工具 ----------

def current_settings() -> dict:
    s = load_settings()
    c = s["criteria"]
    return {
        "搜索条件": {**c, "job_types": [TYPE_LABEL.get(t, t) for t in c["job_types"]]},
        "信源": [{"id": sid, "名称": col.info.name, "分组": col.info.group,
                  "开启": bool(s["sources"].get(sid, {}).get("enabled")),
                  "需要登录": col.info.needs_login, "海外": col.info.region == "overseas"}
                 for sid, col in REGISTRY.items()],
    }


def _clean_criteria(p: dict) -> dict:
    """校验并规范模型给的参数；不认识的字段、不合法的值直接丢掉。"""
    out: dict = {}

    def strs(v, n):
        if not isinstance(v, list):
            return None
        return [str(x).strip()[:40] for x in v if str(x).strip()][:n]

    if v := strs(p.get("keywords"), 30):
        out["keywords"] = v
    if (v := strs(p.get("cities"), 6)) is not None:
        out["cities"] = v
    if (v := strs(p.get("exclude"), 20)) is not None:
        out["exclude"] = v
    if isinstance(p.get("job_types"), list):
        jt = [t for t in p["job_types"] if t in TYPE_LABEL]
        if jt:
            out["job_types"] = jt
    if isinstance(p.get("regions"), dict):
        r = {k: bool(p["regions"].get(k)) for k in ("domestic", "overseas", "remote")}
        if any(r.values()):
            out["regions"] = r
    if p.get("salary_min_k") is not None:
        try:
            out["salary_min_k"] = max(0, min(200, int(float(p["salary_min_k"]))))
        except (TypeError, ValueError):
            pass
    if p.get("max_age_days") is not None:
        try:
            d = int(p["max_age_days"])
            out["max_age_days"] = min(AGE_OPTIONS[1:], key=lambda x: abs(x - d)) if d else 0
        except (TypeError, ValueError):
            pass
    if isinstance(p.get("profile"), str) and p["profile"].strip():
        out["profile"] = mask_contacts(p["profile"].strip()[:800])[0]
    return out


def _fmt(field: str, v) -> str:
    if field == "job_types":
        return "、".join(TYPE_LABEL.get(t, t) for t in v) or "—"
    if field == "regions":
        return "、".join(n for k, n in (("domestic", "国内"), ("overseas", "海外"), ("remote", "远程")) if v.get(k)) or "—"
    if field == "max_age_days":
        return f"最近 {v} 天" if v else "不限"
    if field == "salary_min_k":
        return f"{v}K" if v else "不限"
    if isinstance(v, list):
        return "、".join(v) or "不限"
    return str(v) if v not in (None, "") else "—"


def propose(args: dict) -> dict:
    s = load_settings()
    cur = s["criteria"]
    crit = _clean_criteria(args)
    changes = [{"field": f, "label": FIELD_LABEL[f], "before": _fmt(f, cur.get(f)), "after": _fmt(f, v)}
               for f, v in crit.items() if v != cur.get(f)]
    en = [x for x in args.get("enable_sources") or [] if x in REGISTRY and not s["sources"].get(x, {}).get("enabled")]
    dis = [x for x in args.get("disable_sources") or [] if x in REGISTRY and s["sources"].get(x, {}).get("enabled")]
    if not changes and not en and not dis:
        return {"ok": False, "message": "这个方案和当前设置完全一样，没有需要改的"}
    pid = uuid.uuid4().hex[:10]
    payload={"criteria": {c["field"]: crit[c["field"]] for c in changes}, "enable": en, "disable": dis}
    db.conn().execute('INSERT INTO proposals(id,plan_id,revision,payload,created_at) VALUES(?,?,?,?,?)',
        (pid,current_plan.get(),plans.get()['revision'],json.dumps(payload,ensure_ascii=False),db.now()))
    db.conn().commit()
    return {
        "ok": True, "proposal_id": pid, "changes": changes,
        "enable_sources": [REGISTRY[x].info.name for x in en], "disable_sources": [REGISTRY[x].info.name for x in dis],
        "reason": str(args.get("reason") or "")[:300],
        "注意": "方案还没有生效。界面会给用户一张确认卡片，用户点了「应用」才会保存。不要说已经改好了。",
    }


def apply_proposal(pid: str) -> dict:
    with db._write_lock:
        row=db.conn().execute("SELECT * FROM proposals WHERE id=? AND state='pending'",(pid,)).fetchone()
        if not row: raise KeyError("这个建议已处理或不存在，请重新生成")
        target=plans.get(row['plan_id'])
        if target['revision']!=row['revision']: raise ValueError("方案已变化，这张建议卡已过期，请重新生成")
        p=json.loads(row['payload'])
        src={**{x:{'enabled':True} for x in p['enable']},**{x:{'enabled':False} for x in p['disable']}}
        plans.update(target['id'],{'criteria':p['criteria'],'sources':src,'revision':row['revision']})
        db.conn().execute("UPDATE proposals SET state='applied' WHERE id=?",(pid,)); db.conn().commit()
    return {'ok':True,'plan_id':target['id']}


def discard(pid: str) -> None:
    db.conn().execute("UPDATE proposals SET state='discarded' WHERE id=? AND state='pending'",(pid,))
    db.conn().commit()
