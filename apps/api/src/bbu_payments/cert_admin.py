"""BBU Certificate Manager — one admin page to assign each course a certificate
template + validity tier (1yr / 3yr / none) and layout, without re-running any
script. Mirrors the affiliate-admin pattern: admin-key gated, self-contained
branded HTML. Lets Anna manage the 1yr vs 3yr vs BOLD groupings easily.

Mounted at /api/v1/bbu/cert-admin.
  GET  /                 branded management page (HTML)
  GET  /data             {courses:[{course_uuid,name,published,config}], templates:[...]}
  POST /save             upsert a course's BBU certificate config (or clear it)
"""
import os
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.courses.courses import Course
from src.db.courses.certifications import Certifications
from src.bbu_payments.branding import NAVY, SKY, STEEL, ICE, PAPER, LOGO, _FONTS

router = APIRouter()
ADMIN_KEY = os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")

# The 13 BBU certificate templates + their default layout.
TEMPLATES = [
    ("bbu_cert-01", "Certified Labor Doula (CLD) — navy", "certification"),
    ("bbu_cert-02", "Certified Postpartum Doula (CPD) — navy", "certification"),
    ("bbu_cert-03", "Certified Labor Doula (CLD) — light", "certification"),
    ("bbu_cert-04", "Certified Labor Doula (CLD) — light alt", "certification"),
    ("bbu_cert-05", "Certified Postpartum Doula (CPD) — completion", "completion"),
    ("bbu_cert-06", "Comfort Measures (3 hr)", "completion"),
    ("bbu_cert-07", "Breastfeeding (3 hr)", "completion"),
    ("bbu_cert-08", "Intro to Childbirth (4 hr)", "completion"),
    ("bbu_cert-09", "Preparing for Your Hospital Birth (4 hr)", "completion"),
    ("bbu_cert-10", "Bringing Home Baby (4 hr)", "completion"),
    ("bbu_cert-11", "Breastfeeding for Perinatal Professionals (3 CEU)", "completion"),
    ("bbu_cert-12", "Newborn Care for Perinatal Professionals (3 CEU)", "completion"),
    ("bbu_cert-13", "Comfort Measures for Perinatal Professionals (3 CEU)", "completion"),
]
TEMPLATE_KEYS = {t[0] for t in TEMPLATES}


def _check(request: Request, body_key: str = ""):
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key") or body_key
    if not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


def _tpl_name_from_url(url: str) -> str:
    if not url:
        return ""
    return os.path.basename(url).replace(".png", "")


@router.get("/data")
async def data(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    courses = (await db_session.execute(
        select(Course).where(Course.org_id == 1).order_by(Course.name)
    )).scalars().all()
    certs = (await db_session.execute(select(Certifications))).scalars().all()
    cert_by_course = {c.course_id: c for c in certs}
    out = []
    for c in courses:
        cfg = (cert_by_course.get(c.id).config if cert_by_course.get(c.id) else {}) or {}
        out.append({
            "course_uuid": c.course_uuid,
            "name": c.name,
            "published": bool(c.published),
            "config": {
                "template": _tpl_name_from_url(cfg.get("bbu_template", "")),
                "layout": cfg.get("bbu_layout", ""),
                "validity_years": int(cfg.get("bbu_validity_years", 0) or 0),
                "certification_name": cfg.get("certification_name", ""),
                "enabled": bool(cfg.get("certificate_pattern") == "bbu"),
            },
        })
    return {"courses": out,
            "templates": [{"key": k, "label": lbl, "layout": lay} for k, lbl, lay in TEMPLATES]}


@router.post("/save")
async def save(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    body = await request.json()
    _check(request, body.get("key", ""))
    cu = (body.get("course_uuid") or "").strip()
    template = (body.get("template") or "").strip()
    layout = (body.get("layout") or "").strip()
    validity = int(body.get("validity_years", 0) or 0)
    cert_name = (body.get("certification_name") or "").strip()

    course = (await db_session.execute(
        select(Course).where(Course.course_uuid == cu)
    )).scalars().first()
    if not course:
        raise HTTPException(404, "Course not found")
    existing = (await db_session.execute(
        select(Certifications).where(Certifications.course_id == course.id)
    )).scalars().first()

    # Empty template = disable/clear the certificate for this course.
    if not template:
        if existing:
            await db_session.delete(existing)
            await db_session.commit()
        return {"course_uuid": cu, "enabled": False}

    if template not in TEMPLATE_KEYS:
        raise HTTPException(400, "Unknown template")
    if layout not in ("certification", "completion"):
        layout = dict((k, lay) for k, _, lay in TEMPLATES).get(template, "completion")

    config = {
        "certificate_pattern": "bbu",
        "bbu_template": f"/api/v1/bbu/cert-template/{template}.png",
        "bbu_layout": layout,
        "bbu_validity_years": validity,
        "certification_name": cert_name or course.name,
        "certification_type": "professional" if layout == "certification" else "completion",
        "certification_description": (existing.config.get("certification_description")
                                      if existing and existing.config else "") or f"Awarded through Birth & Baby University for {course.name}.",
    }
    if existing:
        existing.config = config
        existing.update_date = str(datetime.now())
        db_session.add(existing)
    else:
        db_session.add(Certifications(
            course_id=course.id or 0, config=config,
            certification_uuid=f"certification_{uuid4()}",
            creation_date=str(datetime.now()), update_date=str(datetime.now()),
        ))
    await db_session.commit()
    return {"course_uuid": cu, "enabled": True, "template": template,
            "layout": layout, "validity_years": validity}


@router.get("/", response_class=HTMLResponse)
async def page(request: Request):
    _check(request)
    key = request.query_params.get("key", "")
    tpl_options = "".join(
        f"<option value='{k}' data-layout='{lay}'>{lbl}</option>" for k, lbl, lay in TEMPLATES
    )
    html = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Certificate Manager · Birth &amp; Baby University</title>{_FONTS}
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Open Sans',system-ui,sans-serif;color:{NAVY};background:{PAPER}}}
h1,h2{{font-family:'Playfair Display',Georgia,serif}}
.nav{{background:#fff;border-bottom:1px solid rgba(17,61,93,.08);padding:16px 0}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 22px}}
.nav img{{height:52px}}
.head{{padding:26px 0 6px}}
.eyebrow{{font-family:'League Spartan',sans-serif;font-weight:600;letter-spacing:.24em;
text-transform:uppercase;font-size:.7rem;color:{STEEL}}}
.head h1{{font-size:2rem;margin:6px 0 2px}}
.head p{{color:#5b6b78;font-size:.95rem}}
.legend{{display:flex;gap:14px;flex-wrap:wrap;margin:16px 0 10px;font-size:.8rem;color:#5b6b78}}
.pill{{background:{ICE};color:{STEEL};border-radius:999px;padding:3px 12px;font-family:'League Spartan';font-weight:600}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:14px;overflow:hidden;
box-shadow:0 10px 30px rgba(17,61,93,.06);margin:8px 0 40px}}
th{{text-align:left;font-family:'League Spartan';font-weight:700;font-size:.72rem;letter-spacing:.08em;
text-transform:uppercase;color:{STEEL};padding:12px 14px;border-bottom:2px solid {ICE};background:#fbfdff}}
td{{padding:10px 14px;border-bottom:1px solid rgba(17,61,93,.06);font-size:.9rem;vertical-align:middle}}
tr:hover td{{background:#fbfdff}}
select{{font-family:'Open Sans';padding:7px 9px;border:1px solid rgba(17,61,93,.2);border-radius:8px;
font-size:.85rem;background:#fff;max-width:260px}}
.cname{{font-weight:600;max-width:280px}}
.unpub{{color:#b0b7bd;font-size:.72rem;font-family:'League Spartan';letter-spacing:.06em;margin-left:6px}}
.btn{{font-family:'League Spartan',sans-serif;font-weight:700;background:{NAVY};color:#fff;border:none;
border-radius:999px;padding:7px 16px;font-size:.8rem;cursor:pointer;transition:background .2s}}
.btn:hover{{background:{STEEL}}}
.btn.saved{{background:#1f9d55}}
.btn.ghost{{background:#eef4f9;color:{NAVY}}}
.tier1 td:first-child{{box-shadow:inset 4px 0 0 {SKY}}}
.tier3 td:first-child{{box-shadow:inset 4px 0 0 {NAVY}}}
.bar{{display:flex;gap:10px;align-items:center;margin:0 0 14px}}
.search{{flex:1;max-width:360px;padding:9px 13px;border:1px solid rgba(17,61,93,.2);border-radius:10px;font-size:.9rem}}
.count{{color:#6b7680;font-size:.82rem}}
</style></head><body>
<div class='nav'><div class='wrap'><img src='{LOGO}' alt='Birth & Baby University'></div></div>
<div class='wrap'>
  <div class='head'>
    <span class='eyebrow'>Admin</span>
    <h1>Certificate Manager</h1>
    <p>Assign each course a certificate design and validity. Standard trainings = 1 year · Cross-certifications = 3 years · Short courses = completion (no expiry).</p>
  </div>
  <div class='legend'>
    <span class='pill'>1&nbsp;year</span> standard training
    <span class='pill'>3&nbsp;years</span> cross-certification / mentorship
    <span class='pill'>None</span> completion certificate
  </div>
  <div class='bar'>
    <input class='search' id='q' placeholder='Filter courses (e.g. BOLD, doula, breastfeeding)…'>
    <span class='count' id='count'></span>
  </div>
  <table>
    <thead><tr><th>Course</th><th>Certificate template</th><th>Layout</th><th>Validity</th><th></th></tr></thead>
    <tbody id='rows'><tr><td colspan='5' style='padding:30px;text-align:center;color:#8a949c'>Loading…</td></tr></tbody>
  </table>
</div>
<script>
const KEY = {key!r};
const TPL_OPTIONS = `<option value=''>— none —</option>{tpl_options}`;
let COURSES = [];
async function load() {{
  const r = await fetch('/api/v1/bbu/cert-admin/data?key='+encodeURIComponent(KEY));
  const d = await r.json();
  COURSES = d.courses; render();
}}
function tierClass(v){{ return v==1?'tier1':(v==3?'tier3':''); }}
function render() {{
  const q = (document.getElementById('q').value||'').toLowerCase();
  const rows = document.getElementById('rows');
  const list = COURSES.filter(c => c.name.toLowerCase().includes(q));
  document.getElementById('count').textContent = list.length + ' / ' + COURSES.length + ' courses';
  rows.innerHTML = list.map((c,i) => {{
    const cf = c.config;
    return `<tr class='${{tierClass(cf.validity_years)}}' data-uuid='${{c.course_uuid}}'>
      <td class='cname'>${{c.name}}${{c.published?'':"<span class='unpub'>DRAFT</span>"}}</td>
      <td><select class='tpl'>${{TPL_OPTIONS}}</select></td>
      <td><select class='lay'>
        <option value='completion'>Completion</option>
        <option value='certification'>Certification</option>
      </select></td>
      <td><select class='val'>
        <option value='0'>None</option>
        <option value='1'>1 year</option>
        <option value='3'>3 years</option>
      </select></td>
      <td><button class='btn ghost save'>Save</button></td>
    </tr>`;
  }}).join('') || `<tr><td colspan='5' style='padding:30px;text-align:center;color:#8a949c'>No matches</td></tr>`;
  // set current values + wire
  [...rows.querySelectorAll('tr[data-uuid]')].forEach(tr => {{
    const c = list.find(x=>x.course_uuid===tr.dataset.uuid);
    tr.querySelector('.tpl').value = c.config.template || '';
    tr.querySelector('.lay').value = c.config.layout || 'completion';
    tr.querySelector('.val').value = String(c.config.validity_years||0);
    // auto-set layout from template default when template changes
    tr.querySelector('.tpl').addEventListener('change', e => {{
      const opt = e.target.selectedOptions[0];
      if (opt && opt.dataset.layout) tr.querySelector('.lay').value = opt.dataset.layout;
    }});
    tr.querySelector('.save').addEventListener('click', () => save(tr));
  }});
}}
async function save(tr) {{
  const btn = tr.querySelector('.save');
  btn.textContent = 'Saving…'; btn.disabled = true;
  const payload = {{
    key: KEY, course_uuid: tr.dataset.uuid,
    template: tr.querySelector('.tpl').value,
    layout: tr.querySelector('.lay').value,
    validity_years: parseInt(tr.querySelector('.val').value||'0',10),
  }};
  try {{
    const r = await fetch('/api/v1/bbu/cert-admin/save', {{method:'POST',
      headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(payload)}});
    if (!r.ok) throw new Error();
    const c = COURSES.find(x=>x.course_uuid===tr.dataset.uuid);
    c.config.template = payload.template; c.config.layout = payload.layout; c.config.validity_years = payload.validity_years;
    tr.className = payload.template ? tierClass(payload.validity_years) : '';
    btn.textContent = 'Saved ✓'; btn.classList.remove('ghost'); btn.classList.add('saved');
    setTimeout(()=>{{ btn.textContent='Save'; btn.classList.add('ghost'); btn.classList.remove('saved'); btn.disabled=false; }}, 1400);
  }} catch(e) {{ btn.textContent='Error — retry'; btn.disabled=false; }}
}}
document.getElementById('q').addEventListener('input', render);
load();
</script></body></html>"""
    return HTMLResponse(html)
