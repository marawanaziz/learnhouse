"""BBU Operations Console — one in-app admin page (session-gated) to operate the
clean-room engines that were previously API/curl-only: coupons, cohorts,
credentials, and reseller seat codes. Mirrors the Cert Manager pattern
(self-contained branded HTML, session-or-key auth). Mounted at /api/v1/bbu/admin.

The page's JS calls this module's own JSON endpoints with the session cookie, so
the admin key never reaches the browser. Each endpoint calls the same service
layer the key-gated routers use — no duplicated business logic.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import User
from src.db.courses.courses import Course
from src.bbu_admin.auth import authorize_admin
from src.bbu_payments.models import BBUCoupon, BBUProduct
from src.bbu_payments import coupons as coupon_svc
from src.bbu_cohorts.models import BBUCohort
from src.bbu_cohorts import service as cohort_svc
from src.bbu_credentials.models import BBUCredential, BBUCeuLedger
from src.bbu_credentials import service as cred_svc
from src.bbu_seats.models import BBUSeatCode
from src.bbu_seats.router import _gen_code
from src.bbu_payments.branding import NAVY, SKY, ICE, PAPER

router = APIRouter()
ORG = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _auth(request: Request, db: AsyncSession, body: dict = None):
    await authorize_admin(request, db, (body or {}).get("key", ""))


async def _user(db: AsyncSession, email: str) -> User:
    u = (await db.execute(select(User).where(
        User.email == (email or "").strip().lower()))).scalars().first()
    if not u:
        raise HTTPException(404, "User not found")
    return u


# ===========================================================================
# Coupons
# ===========================================================================
@router.get("/coupons")
async def coupons_list(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    rows = (await db_session.execute(select(BBUCoupon).where(BBUCoupon.org_id == ORG))).scalars().all()
    return [{
        "id": c.id, "code": c.code, "kind": c.kind,
        "value": (f"{c.percent_off}%" if c.kind == "percent" else f"${(c.amount_off_cents or 0)/100:.2f}"),
        "min": round((c.min_amount_cents or 0) / 100, 2),
        "max_redemptions": c.max_redemptions, "times_redeemed": c.times_redeemed,
        "expires_at": (c.expires_at or "")[:10], "active": bool(c.active),
    } for c in rows]


@router.post("/coupons")
async def coupons_create(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    code = (b.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "code required")
    if await coupon_svc.find_by_code(db_session, ORG, code):
        raise HTTPException(409, "That code already exists")
    c = BBUCoupon(
        org_id=ORG, code=code, kind=b.get("kind", "percent"),
        percent_off=int(b.get("percent_off", 0) or 0),
        amount_off_cents=round(float(b.get("amount_off", 0) or 0) * 100),
        min_amount_cents=round(float(b.get("min_amount", 0) or 0) * 100),
        max_redemptions=int(b.get("max_redemptions", 0) or 0),
        expires_at=(b.get("expires_at") or ""), active=True, created_at=_now())
    try:
        coupon_svc.ensure_stripe_objects(c)
    except Exception as e:
        raise HTTPException(502, f"Stripe error: {e}")
    db_session.add(c)
    await db_session.commit()
    return {"ok": True}


@router.post("/coupons/{cid}/toggle")
async def coupons_toggle(cid: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    c = (await db_session.execute(select(BBUCoupon).where(
        BBUCoupon.id == cid, BBUCoupon.org_id == ORG))).scalars().first()
    if not c:
        raise HTTPException(404, "Not found")
    c.active = not c.active
    (coupon_svc.reactivate_stripe if c.active else coupon_svc.deactivate_stripe)(c)
    db_session.add(c)
    await db_session.commit()
    return {"active": c.active}


# ===========================================================================
# Cohorts
# ===========================================================================
@router.get("/cohorts")
async def cohorts_list(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    rows = (await db_session.execute(select(BBUCohort).where(
        BBUCohort.org_id == ORG).order_by(BBUCohort.id.desc()))).scalars().all()
    out = []
    for c in rows:
        out.append({
            "id": c.id, "name": c.name, "program": c.program, "status": c.status,
            "capacity": c.capacity, "active_members": await cohort_svc.active_count(db_session, c.id),
            "credential_type": c.credential_type, "start_date": c.start_date, "end_date": c.end_date,
        })
    return out


@router.post("/cohorts")
async def cohorts_create(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    program = b.get("program", "doula")
    c = BBUCohort(
        org_id=ORG, name=b.get("name", "Untitled Cohort"), program=program,
        course_uuid=(b.get("course_uuid") or "").strip(),
        capacity=int(b.get("capacity", 0) or 0),
        access_months=int(b.get("access_months", 12 if program == "agency" else 6)),
        credential_type=(b.get("credential_type") or "").strip().lower(),
        start_date=b.get("start_date", ""), end_date=b.get("end_date", ""),
        status="open", created_at=_now(), updated_at=_now())
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    if c.course_uuid:
        await cohort_svc.ensure_usergroup(db_session, c)
    return {"ok": True, "id": c.id}


@router.get("/cohorts/{cid}/roster")
async def cohorts_roster(cid: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    members = await cohort_svc.roster(db_session, cid)
    uids = [m.user_id for m in members]
    users = {}
    if uids:
        rows = (await db_session.execute(select(User).where(User.id.in_(uids)))).scalars().all()
        users = {u.id: u for u in rows}
    return [{
        "email": getattr(users.get(m.user_id), "email", ""),
        "name": f"{getattr(users.get(m.user_id), 'first_name', '')} {getattr(users.get(m.user_id), 'last_name', '')}".strip(),
        "status": m.status,
    } for m in members]


@router.post("/cohorts/{cid}/action")
async def cohorts_action(cid: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    c = (await db_session.execute(select(BBUCohort).where(BBUCohort.id == cid))).scalars().first()
    if not c:
        raise HTTPException(404, "Cohort not found")
    action = b.get("action")
    if action == "close":
        return await cohort_svc.close(db_session, c, revoke_access=True)
    u = await _user(db_session, b.get("email", ""))
    if action == "enroll":
        return await cohort_svc.enroll(db_session, c, u.id)
    if action == "complete":
        return await cohort_svc.complete(db_session, c, u.id)
    if action == "remove":
        return await cohort_svc.remove(db_session, c, u.id)
    raise HTTPException(400, "unknown action")


# ===========================================================================
# Credentials
# ===========================================================================
@router.get("/credentials")
async def credentials_user(request: Request, email: str, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    u = await _user(db_session, email)
    creds = (await db_session.execute(select(BBUCredential).where(
        BBUCredential.org_id == ORG, BBUCredential.user_id == u.id))).scalars().all()
    total = await cred_svc.approved_ceu_total(db_session, ORG, u.id)
    ledger = (await db_session.execute(select(BBUCeuLedger).where(
        BBUCeuLedger.org_id == ORG, BBUCeuLedger.user_id == u.id))).scalars().all()
    return {
        "email": u.email, "ceu_total": total,
        "credentials": [cred_svc.to_dict(c, total) for c in creds],
        "ledger": [{"ceu": r.ceu_count, "source": r.source, "ref": r.source_ref,
                    "approved": r.approved} for r in ledger],
    }


@router.post("/credentials/action")
async def credentials_action(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    u = await _user(db_session, b.get("email", ""))
    action = b.get("action")
    ctype = (b.get("credential_type") or "birth").strip().lower()
    if action == "issue":
        mode = (b.get("mode") or "provisional").lower()
        if mode == "full":
            await cred_svc.issue_full_direct(db_session, ORG, u.id, ctype, source="manual", source_ref="admin")
        else:
            await cred_svc.issue_provisional(db_session, ORG, u.id, ctype, source_ref="admin")
        return {"ok": True}
    if action == "award_ceu":
        await cred_svc.award_ceu(db_session, ORG, u.id, int(b.get("count", 0)),
                                 source="manual", source_ref=b.get("note", ""))
        return {"ok": True, "ceu_total": await cred_svc.approved_ceu_total(db_session, ORG, u.id)}
    if action == "renew":
        cred = (await db_session.execute(select(BBUCredential).where(
            BBUCredential.org_id == ORG, BBUCredential.user_id == u.id,
            BBUCredential.credential_type == ctype))).scalars().first()
        if not cred:
            raise HTTPException(404, "Credential not found")
        ok, reason = await cred_svc.renew(db_session, cred)
        return {"ok": ok, "reason": reason}
    raise HTTPException(400, "unknown action")


# ===========================================================================
# Seat codes
# ===========================================================================
@router.get("/seats")
async def seats_batches(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    rows = (await db_session.execute(select(BBUSeatCode).where(BBUSeatCode.org_id == ORG))).scalars().all()
    agg = {}
    for r in rows:
        a = agg.setdefault(r.batch_label, {"batch_label": r.batch_label, "total": 0,
                                           "redeemed": 0, "unused": 0, "void": 0,
                                           "owner_email": r.owner_email})
        a["total"] += 1
        a[r.status if r.status in ("redeemed", "void") else "unused"] += 1
    return list(agg.values())


@router.post("/seats/generate")
async def seats_generate(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    count = max(1, min(500, int(b.get("count", 1))))
    course_uuids = [u for u in (b.get("course_uuids") or []) if u]
    if b.get("product_id") and not course_uuids:
        p = (await db_session.execute(select(BBUProduct).where(
            BBUProduct.id == int(b["product_id"])))).scalars().first()
        if p:
            course_uuids = [u for u in (p.course_uuids or "").split(",") if u]
    if not course_uuids:
        raise HTTPException(400, "course_uuids or product_id required")
    label = b.get("batch_label") or f"batch-{_now()[:10]}"
    codes = []
    for _ in range(count):
        code = _gen_code()
        while (await db_session.execute(select(BBUSeatCode).where(BBUSeatCode.code == code))).scalars().first():
            code = _gen_code()
        db_session.add(BBUSeatCode(org_id=ORG, code=code, batch_label=label,
                                   course_uuids=",".join(course_uuids),
                                   owner_email=(b.get("owner_email") or "").strip().lower(),
                                   status="unused", created_at=_now()))
        codes.append(code)
    await db_session.commit()
    return {"batch_label": label, "count": len(codes), "codes": codes}


@router.get("/courses")
async def courses_list(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """Course picker for cohort/seat forms."""
    await _auth(request, db_session)
    rows = (await db_session.execute(select(Course).where(
        Course.org_id == ORG).order_by(Course.name))).scalars().all()
    return [{"course_uuid": c.course_uuid, "name": c.name} for c in rows]


# ===========================================================================
# Store merchandising — edit each offer's category + order-bump add-ons.
# ===========================================================================
@router.get("/offers")
async def offers_list(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    rows = (await db_session.execute(select(BBUProduct).where(
        BBUProduct.org_id == ORG).order_by(BBUProduct.name))).scalars().all()
    return [{
        "id": p.id, "name": p.name, "kind": p.kind,
        "price": round((p.price_cents or 0) / 100, 2),
        "category": p.category or "",
        "public": bool(p.public),
        "bump_ids": [int(x) for x in (p.bump_offer_ids or "").split(",") if x.strip().isdigit()],
        "cohort_program": p.cohort_program or "",
        "cohort_id": p.cohort_id,
    } for p in rows]


@router.post("/offers/{pid}/merchandising")
async def offers_merch(pid: int, request: Request, db_session: AsyncSession = Depends(get_db_session)):
    b = await request.json()
    await _auth(request, db_session, b)
    p = (await db_session.execute(select(BBUProduct).where(
        BBUProduct.id == pid, BBUProduct.org_id == ORG))).scalars().first()
    if not p:
        raise HTTPException(404, "Offer not found")
    if "category" in b:
        p.category = (b.get("category") or "")
    if "bump_ids" in b:
        p.bump_offer_ids = ",".join(str(int(x)) for x in (b.get("bump_ids") or [])
                                    if str(x).isdigit() and int(x) != pid)
    if "cohort_program" in b:
        prog = (b.get("cohort_program") or "").strip()
        p.cohort_program = prog if prog in ("doula", "agency") else ""
    if "cohort_id" in b:
        cid = b.get("cohort_id")
        p.cohort_id = int(cid) if str(cid or "").isdigit() and int(cid) > 0 else None
    db_session.add(p)
    await db_session.commit()
    return {"ok": True}


# ===========================================================================
# The page
# ===========================================================================
@router.get("/", response_class=HTMLResponse)
async def page(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    await _auth(request, db_session)
    return HTMLResponse(_PAGE)


_PAGE = f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Operations Console · Birth &amp; Baby University</title>
<style>
:root{{--navy:{NAVY};--sky:{SKY};--ice:{ICE};--paper:{PAPER}}}
*{{box-sizing:border-box}}body{{margin:0;font-family:'Open Sans',system-ui,sans-serif;color:#1b2733;background:var(--paper)}}
header{{background:var(--navy);color:#fff;padding:1.4rem 1.5rem}}
header h1{{margin:0;font-family:'Playfair Display',Georgia,serif;font-size:1.4rem}}
.tabs{{display:flex;gap:.3rem;background:var(--navy);padding:0 1.5rem}}
.tab{{padding:.7rem 1.1rem;color:#cfe4f5;cursor:pointer;border-bottom:3px solid transparent;font-size:.9rem;font-weight:600}}
.tab.on{{color:#fff;border-color:var(--sky)}}
.wrap{{max-width:1050px;margin:1.5rem auto;padding:0 1.2rem}}
.panel{{display:none}}.panel.on{{display:block}}
.card{{background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(17,61,93,.08);padding:1.2rem;margin-bottom:1.2rem}}
h2{{font-size:1.05rem;color:var(--navy);margin:.2rem 0 1rem}}
table{{width:100%;border-collapse:collapse;font-size:.86rem}}
th,td{{padding:.55rem .6rem;text-align:left;border-bottom:1px solid #eef3f8}}
th{{background:var(--ice);color:var(--navy)}}
input,select{{padding:.5rem .6rem;border:1px solid #cdd9e5;border-radius:8px;font-size:.86rem;margin:.2rem}}
button{{background:var(--navy);color:#fff;border:0;padding:.55rem 1rem;border-radius:8px;font-weight:600;cursor:pointer;font-size:.85rem}}
button.ghost{{background:#e7eef5;color:var(--navy)}}
.row{{display:flex;flex-wrap:wrap;align-items:center;gap:.2rem;margin-bottom:.6rem}}
.badge{{padding:.15rem .5rem;border-radius:20px;font-size:.75rem;font-weight:600}}
.on-b{{background:#dff5e6;color:#1c7a41}}.off-b{{background:#fde8e8;color:#b42318}}
.muted{{color:#7d93a6;font-size:.8rem}}
</style></head><body>
<header><h1>Operations Console</h1><div class=muted style="color:#cfe4f5">Coupons · Cohorts · Credentials · Seat codes</div></header>
<div class=tabs>
  <div class="tab on" data-t="coupons">Coupons</div>
  <div class="tab" data-t="cohorts">Cohorts</div>
  <div class="tab" data-t="credentials">Credentials</div>
  <div class="tab" data-t="seats">Seat codes</div>
  <div class="tab" data-t="store">Store</div>
</div>
<div class=wrap>
  <div class="panel on" id=p-coupons>
    <div class=card><h2>Create a promo code</h2>
      <div class=row>
        <input id=c-code placeholder="CODE (e.g. LAUNCH20)">
        <select id=c-kind><option value=percent>% off</option><option value=amount>$ off</option></select>
        <input id=c-val type=number placeholder="amount" style="width:90px">
        <input id=c-min type=number placeholder="min $ (opt)" style="width:100px">
        <input id=c-max type=number placeholder="max uses (opt)" style="width:110px">
        <input id=c-exp type=date>
        <button onclick=createCoupon()>Create</button>
      </div><div class=muted id=c-msg></div>
    </div>
    <div class=card><h2>Coupons</h2><table id=t-coupons><thead><tr><th>Code</th><th>Value</th><th>Min</th><th>Used</th><th>Expires</th><th>Status</th><th></th></tr></thead><tbody></tbody></table></div>
  </div>

  <div class="panel" id=p-cohorts>
    <div class=card><h2>Create a cohort</h2>
      <div class=row>
        <input id=co-name placeholder="Name (e.g. Sept 2026 Doula Mentorship)" style="width:300px">
        <select id=co-prog><option value=doula>doula</option><option value=agency>agency</option></select>
        <select id=co-course></select>
        <input id=co-cap type=number placeholder="capacity (0=∞)" style="width:130px">
        <select id=co-cred><option value="">no credential</option><option value=birth>birth</option><option value=postpartum>postpartum</option><option value=both>both</option></select>
        <button onclick=createCohort()>Create</button>
      </div><div class=muted id=co-msg></div>
    </div>
    <div class=card><h2>Cohorts</h2><table id=t-cohorts><thead><tr><th>Name</th><th>Program</th><th>Members</th><th>Cap</th><th>Cred</th><th>Status</th><th></th></tr></thead><tbody></tbody></table></div>
    <div class=card id=roster-card style=display:none><h2>Roster — <span id=roster-name></span></h2>
      <div class=row><input id=co-email placeholder="member email"><button onclick="cohortAct('enroll')">Enroll</button><button class=ghost onclick="cohortAct('complete')">Mark complete</button><button class=ghost onclick="cohortAct('remove')">Remove</button></div>
      <table id=t-roster><thead><tr><th>Name</th><th>Email</th><th>Status</th></tr></thead><tbody></tbody></table>
    </div>
  </div>

  <div class="panel" id=p-credentials>
    <div class=card><h2>Look up a member's credentials</h2>
      <div class=row><input id=cr-email placeholder="member email" style="width:280px"><button onclick=loadCred()>Look up</button></div>
      <div id=cr-out></div>
    </div>
    <div class=card><h2>Actions</h2>
      <div class=row>
        <input id=cra-email placeholder="member email">
        <select id=cra-type><option value=birth>birth</option><option value=postpartum>postpartum</option></select>
        <button onclick="credAct('issue','provisional')">Issue provisional</button>
        <button class=ghost onclick="credAct('issue','full')">Issue full</button>
        <button class=ghost onclick="credAct('renew')">Renew</button>
      </div>
      <div class=row><input id=cra-ceu type=number placeholder="CEUs" style="width:90px"><button class=ghost onclick="credAct('award_ceu')">Award CEUs</button></div>
      <div class=muted id=cra-msg></div>
    </div>
  </div>

  <div class="panel" id=p-seats>
    <div class=card><h2>Generate seat codes (reseller / bulk)</h2>
      <div class=row>
        <input id=s-label placeholder="batch label (e.g. Hospital X 16-pack)" style="width:280px">
        <select id=s-course></select>
        <input id=s-count type=number placeholder="how many" style="width:110px">
        <input id=s-owner placeholder="owner email (opt)" style="width:200px">
        <button onclick=genSeats()>Generate</button>
      </div><div class=muted id=s-msg></div>
      <textarea id=s-codes style="width:100%;height:0;border:0;opacity:0;position:absolute"></textarea>
    </div>
    <div class=card><h2>Batches</h2><table id=t-seats><thead><tr><th>Batch</th><th>Owner</th><th>Total</th><th>Redeemed</th><th>Unused</th></tr></thead><tbody></tbody></table></div>
  </div>

  <div class="panel" id=p-store>
    <div class=card><h2>Store merchandising</h2>
      <p class=muted style="margin-top:-.6rem">Set each offer's category (store bucket), order-bump add-ons, and — for mentorship offers — the cohort a purchase enrolls into. Changes are live immediately.</p>
      <table id=t-store><thead><tr><th>Offer</th><th>Price</th><th>Category</th><th>Order-bump add-ons</th><th>Cohort enroll</th></tr></thead><tbody></tbody></table>
    </div>
  </div>
</div>
<script>
const API='/api/v1/bbu/admin';
const j=(u,o)=>fetch(API+u,Object.assign({{credentials:'include',headers:{{'Content-Type':'application/json'}}}},o||{{}})).then(r=>r.json());
function esc(s){{return String(s==null?'':s).replace(/[&<>]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]))}}
// tabs
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
  document.querySelectorAll('.panel').forEach(x=>x.classList.remove('on'));
  t.classList.add('on'); document.getElementById('p-'+t.dataset.t).classList.add('on');
  if(t.dataset.t==='cohorts')loadCohorts(); if(t.dataset.t==='seats')loadSeats(); if(t.dataset.t==='store')loadStore();
}});
// Store merchandising
const CATS=['','Birth Classes','Postpartum Classes','Spanish Classes','Professional Training','Bundles','eBooks'];
let STORE=[]; let COHORTS=[];
function cohortSel(o){{
  const cur = o.cohort_id ? ('id:'+o.cohort_id) : (o.cohort_program ? ('prog:'+o.cohort_program) : '');
  let opts = `<option value="" ${{cur===''?'selected':''}}>— not a cohort —</option>`
    + `<option value="prog:doula" ${{cur==='prog:doula'?'selected':''}}>Next open Doula Mentorship</option>`
    + `<option value="prog:agency" ${{cur==='prog:agency'?'selected':''}}>Next open Agency cohort</option>`;
  const specific = COHORTS.filter(c=>c.status!=='closed');
  if(specific.length) opts += `<optgroup label="Specific cohort">`
    + specific.map(c=>`<option value="id:${{c.id}}" ${{cur==='id:'+c.id?'selected':''}}>${{esc(c.name)}} (${{esc(c.program)}}·${{esc(c.status)}})</option>`).join('') + `</optgroup>`;
  return `<select onchange="saveCohort(${{o.id}},this.value)">${{opts}}</select>`;
}}
function renderStore(){{
  document.querySelector('#t-store tbody').innerHTML=STORE.map(o=>{{
    const opts=CATS.map(c=>`<option value="${{esc(c)}}" ${{o.category===c?'selected':''}}>${{c||'—'}}</option>`).join('');
    const bumps=STORE.filter(x=>x.id!==o.id).map(x=>`<label style="display:block;font-size:.78rem"><input type=checkbox ${{o.bump_ids.includes(x.id)?'checked':''}} onchange="toggleBump(${{o.id}},${{x.id}},this.checked)"> ${{esc(x.name)}} ($${{x.price}})</label>`).join('');
    const n=o.bump_ids.length;
    return `<tr><td><b>${{esc(o.name)}}</b></td><td>$${{o.price}}</td>`
      +`<td><select onchange="saveCat(${{o.id}},this.value)">${{opts}}</select></td>`
      +`<td><details><summary style="cursor:pointer;color:#3a91c6">${{n?n+' add-on'+(n>1?'s':''):'none'}}</summary><div style="max-height:150px;overflow:auto;padding:.3rem 0">${{bumps}}</div></details></td>`
      +`<td>${{cohortSel(o)}}</td></tr>`;
  }}).join('');
}}
function loadStore(){{Promise.all([j('/offers'),j('/cohorts')]).then(([d,c])=>{{
  STORE=d||[]; COHORTS=c||[]; renderStore();
}})}}
function saveCohort(id,val){{
  const o=STORE.find(x=>x.id===id); if(!o)return;
  let body={{cohort_program:'',cohort_id:0}};
  if(val.startsWith('prog:')) body.cohort_program=val.slice(5);
  else if(val.startsWith('id:')) body.cohort_id=parseInt(val.slice(3),10);
  o.cohort_program=body.cohort_program; o.cohort_id=body.cohort_id||null;
  j('/offers/'+id+'/merchandising',{{method:'POST',body:JSON.stringify(body)}});
}}
function saveCat(id,cat){{j('/offers/'+id+'/merchandising',{{method:'POST',body:JSON.stringify({{category:cat}})}})}}
function toggleBump(id,bumpId,on){{
  const o=STORE.find(x=>x.id===id); if(!o)return;
  o.bump_ids = on ? [...new Set([...o.bump_ids,bumpId])] : o.bump_ids.filter(x=>x!==bumpId);
  j('/offers/'+id+'/merchandising',{{method:'POST',body:JSON.stringify({{bump_ids:o.bump_ids}})}});
}}
// Coupons
function loadCoupons(){{j('/coupons').then(d=>{{
  document.querySelector('#t-coupons tbody').innerHTML=(d||[]).map(c=>
    `<tr><td><b>${{esc(c.code)}}</b></td><td>${{esc(c.value)}}</td><td>${{c.min?'$'+c.min:'—'}}</td>`
    +`<td>${{c.times_redeemed}}${{c.max_redemptions?'/'+c.max_redemptions:''}}</td><td>${{c.expires_at||'—'}}</td>`
    +`<td><span class="badge ${{c.active?'on-b':'off-b'}}">${{c.active?'Active':'Off'}}</span></td>`
    +`<td><button class=ghost onclick="toggleCoupon(${{c.id}})">${{c.active?'Deactivate':'Activate'}}</button></td></tr>`).join('');
}})}}
function createCoupon(){{
  const kind=document.getElementById('c-kind').value, v=+document.getElementById('c-val').value;
  const body={{code:document.getElementById('c-code').value,kind:kind,
    percent_off:kind==='percent'?v:0, amount_off:kind==='amount'?v:0,
    min_amount:+document.getElementById('c-min').value||0,
    max_redemptions:+document.getElementById('c-max').value||0,
    expires_at:document.getElementById('c-exp').value?document.getElementById('c-exp').value+'T23:59:59+00:00':''}};
  j('/coupons',{{method:'POST',body:JSON.stringify(body)}}).then(r=>{{
    document.getElementById('c-msg').textContent=r.ok?'Created ✓':(r.detail||'Error'); if(r.ok)loadCoupons();}});
}}
function toggleCoupon(id){{j('/coupons/'+id+'/toggle',{{method:'POST'}}).then(loadCoupons)}}
// Cohorts
let curCohort=null;
function loadCohorts(){{
  j('/courses').then(cs=>{{document.getElementById('co-course').innerHTML='<option value="">— course —</option>'+cs.map(c=>`<option value="${{c.course_uuid}}">${{esc(c.name)}}</option>`).join('')}});
  j('/cohorts').then(d=>{{
    document.querySelector('#t-cohorts tbody').innerHTML=(d||[]).map(c=>
      `<tr><td><b>${{esc(c.name)}}</b></td><td>${{esc(c.program)}}</td><td>${{c.active_members}}</td>`
      +`<td>${{c.capacity||'∞'}}</td><td>${{esc(c.credential_type||'—')}}</td><td>${{esc(c.status)}}</td>`
      +`<td><button class=ghost onclick="openRoster(${{c.id}},'${{esc(c.name)}}')">Roster</button></td></tr>`).join('');
  }});
}}
function createCohort(){{
  const body={{name:document.getElementById('co-name').value,program:document.getElementById('co-prog').value,
    course_uuid:document.getElementById('co-course').value,capacity:+document.getElementById('co-cap').value||0,
    credential_type:document.getElementById('co-cred').value}};
  j('/cohorts',{{method:'POST',body:JSON.stringify(body)}}).then(r=>{{document.getElementById('co-msg').textContent=r.ok?'Created ✓':'Error';loadCohorts();}});
}}
function openRoster(id,name){{curCohort=id;document.getElementById('roster-card').style.display='block';
  document.getElementById('roster-name').textContent=name;loadRoster();}}
function loadRoster(){{j('/cohorts/'+curCohort+'/roster').then(d=>{{
  document.querySelector('#t-roster tbody').innerHTML=(d||[]).map(m=>`<tr><td>${{esc(m.name)}}</td><td>${{esc(m.email)}}</td><td>${{esc(m.status)}}</td></tr>`).join('');}})}}
function cohortAct(action){{
  j('/cohorts/'+curCohort+'/action',{{method:'POST',body:JSON.stringify({{action:action,email:document.getElementById('co-email').value}})}}).then(()=>{{loadRoster();loadCohorts();}});
}}
// Credentials
function loadCred(){{
  j('/credentials?email='+encodeURIComponent(document.getElementById('cr-email').value)).then(d=>{{
    if(d.detail){{document.getElementById('cr-out').innerHTML='<span class=muted>'+esc(d.detail)+'</span>';return;}}
    const creds=(d.credentials||[]).map(c=>`<tr><td>${{esc(c.credential_type)}}</td><td><span class="badge on-b">${{esc(c.status)}}</span></td><td>${{(c.issued_at||'').slice(0,10)}}</td><td>${{(c.full_expires_at||c.provisional_expires_at||'').slice(0,10)}}</td></tr>`).join('');
    document.getElementById('cr-out').innerHTML=`<p class=muted>CEU total: <b>${{d.ceu_total}}</b></p><table><thead><tr><th>Type</th><th>Status</th><th>Issued</th><th>Valid through</th></tr></thead><tbody>${{creds||'<tr><td colspan=4 class=muted>No credentials</td></tr>'}}</tbody></table>`;
  }});
}}
function credAct(action,mode){{
  const body={{action:action,mode:mode,email:document.getElementById('cra-email').value,
    credential_type:document.getElementById('cra-type').value,count:+document.getElementById('cra-ceu').value||0}};
  j('/credentials/action',{{method:'POST',body:JSON.stringify(body)}}).then(r=>{{
    document.getElementById('cra-msg').textContent=r.ok?('Done ✓'+(r.ceu_total!=null?' (CEU: '+r.ceu_total+')':'')):(r.reason||r.detail||'Error');}});
}}
// Seats
function loadSeats(){{
  j('/courses').then(cs=>{{document.getElementById('s-course').innerHTML='<option value="">— course —</option>'+cs.map(c=>`<option value="${{c.course_uuid}}">${{esc(c.name)}}</option>`).join('')}});
  j('/seats').then(d=>{{document.querySelector('#t-seats tbody').innerHTML=(d||[]).map(b=>`<tr><td><b>${{esc(b.batch_label)}}</b></td><td>${{esc(b.owner_email||'—')}}</td><td>${{b.total}}</td><td>${{b.redeemed}}</td><td>${{b.unused}}</td></tr>`).join('');}});
}}
function genSeats(){{
  const body={{batch_label:document.getElementById('s-label').value,course_uuids:[document.getElementById('s-course').value].filter(Boolean),
    count:+document.getElementById('s-count').value||1,owner_email:document.getElementById('s-owner').value}};
  j('/seats/generate',{{method:'POST',body:JSON.stringify(body)}}).then(r=>{{
    if(r.codes){{document.getElementById('s-msg').innerHTML='Generated '+r.count+' codes:<br><code>'+r.codes.join('  ')+'</code>';loadSeats();}}
    else document.getElementById('s-msg').textContent=r.detail||'Error';}});
}}
loadCoupons();
</script></body></html>"""
