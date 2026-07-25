"""BBU HSA/FSA payment page — custom-amount Stripe checkout for invoices.

Replaces the old Thrivecart gift-card workaround (team review, Jul 2026). A
customer opens the page, enters the amount from their invoice + a memo, and pays
by card. Stripe Checkout auto-enables every card method configured on the
account (HSA/FSA cards are ordinary cards, so they just work). Admins can share
a pre-filled link: /api/v1/bbu/hsa-fsa?amount=150&memo=Birth%20class%20balance

Mounted at /api/v1/bbu/hsa-fsa.
  GET  /               HTML pay page (public; optional ?amount=&memo=&email= prefill)
  POST /checkout       {amount_dollars, memo, email} -> {url} (Stripe Checkout)
  GET  /thanks         simple thank-you page (Stripe success_url)
"""
import os
import stripe

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter()
stripe.api_key = os.environ.get("BBU_STRIPE_SECRET_KEY", "")
ORG_NAME = "Birth & Baby University"


def _base_url(request: Request) -> str:
    return os.environ.get("BBU_PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


@router.post("/checkout")
async def create_checkout(request: Request):
    if not stripe.api_key:
        raise HTTPException(500, "Stripe not configured")
    body = await request.json()
    try:
        amount = float(body.get("amount_dollars") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount < 1:
        raise HTTPException(400, "Enter a valid amount (min $1).")
    cents = int(round(amount * 100))
    memo = (body.get("memo") or "Payment").strip()[:250]
    email = (body.get("email") or "").strip() or None
    base = _base_url(request)
    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=email,
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"{ORG_NAME} — {memo}"[:300]},
                "unit_amount": cents,
            },
            "quantity": 1,
        }],
        success_url=f"{base}/api/v1/bbu/hsa-fsa/thanks",
        cancel_url=f"{base}/api/v1/bbu/hsa-fsa",
        metadata={"bbu_kind": "hsa_fsa_invoice", "memo": memo},
    )
    return {"url": session.url}


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def pay_page(request: Request):
    amount = _esc(request.query_params.get("amount", ""))
    memo = _esc(request.query_params.get("memo", ""))
    email = _esc(request.query_params.get("email", ""))
    html = f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>Pay with HSA / FSA — {ORG_NAME}</title>
<style>
:root{{--navy:#113d5d;--sky:#3a91c6}}
*{{box-sizing:border-box}}body{{font-family:'League Spartan',-apple-system,Segoe UI,sans-serif;margin:0;
background:linear-gradient(157deg,#0d3350,#164e77,#3f7cb4,#79b4e6);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.card{{background:#fff;border-radius:22px;max-width:440px;width:100%;padding:34px;box-shadow:0 24px 60px rgba(0,0,0,.25)}}
h1{{font-family:'Playfair Display',serif;color:var(--navy);margin:0 0 4px;font-size:1.5rem}}
p.sub{{color:#6b6f79;margin:0 0 22px;font-size:.95rem}}
label{{display:block;font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;color:#6b6f79;margin:14px 0 5px;font-weight:700}}
input{{width:100%;padding:13px 14px;border:1px solid rgba(17,61,93,.22);border-radius:12px;font-size:1rem}}
input:focus{{outline:none;border-color:var(--sky);box-shadow:0 0 0 3px rgba(58,145,198,.15)}}
.amt{{position:relative}}.amt span{{position:absolute;left:14px;top:13px;color:#6b6f79;font-size:1rem}}.amt input{{padding-left:28px}}
button{{width:100%;margin-top:24px;background:var(--navy);color:#fff;border:none;border-radius:12px;padding:15px;font-size:1.05rem;font-weight:700;cursor:pointer;font-family:inherit}}
button:hover{{background:#0d3350}}button:disabled{{opacity:.6;cursor:default}}
.note{{margin-top:16px;font-size:.8rem;color:#6b6f79;text-align:center}}
.err{{color:#b3261e;font-size:.85rem;margin-top:10px;min-height:1em}}
</style></head><body>
<div class=card>
  <h1>Pay with HSA / FSA</h1>
  <p class=sub>Enter the amount from your invoice and pay securely by card — HSA and FSA cards are accepted.</p>
  <label for=amount>Amount (USD)</label>
  <div class=amt><span>$</span><input id=amount type=number min=1 step=0.01 inputmode=decimal placeholder="0.00" value="{amount}"></div>
  <label for=memo>What is this for?</label>
  <input id=memo type=text placeholder="e.g. Childbirth class balance / invoice #123" value="{memo}">
  <label for=email>Email for your receipt</label>
  <input id=email type=email placeholder="you@example.com" value="{email}">
  <div class=err id=err></div>
  <button id=pay onclick=go()>Continue to secure payment →</button>
  <p class=note>🔒 Payments are processed securely by Stripe. {ORG_NAME} never sees your card details.</p>
</div>
<script>
async function go(){{
  var b=document.getElementById('pay'),e=document.getElementById('err');e.textContent='';
  var amount=parseFloat(document.getElementById('amount').value||'0');
  var memo=document.getElementById('memo').value.trim();
  var email=document.getElementById('email').value.trim();
  if(!(amount>=1)){{e.textContent='Please enter an amount of at least $1.';return}}
  if(!memo){{e.textContent='Please add a short note for what this payment is for.';return}}
  b.disabled=true;b.textContent='Redirecting…';
  try{{
    var r=await fetch('/api/v1/bbu/hsa-fsa/checkout',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{amount_dollars:amount,memo:memo,email:email}})}});
    var d=await r.json();
    if(d.url){{window.location=d.url}}else{{e.textContent=d.detail||'Something went wrong.';b.disabled=false;b.textContent='Continue to secure payment →'}}
  }}catch(x){{e.textContent='Network error — please try again.';b.disabled=false;b.textContent='Continue to secure payment →'}}
}}
</script></body></html>"""
    return HTMLResponse(html)


@router.get("/thanks", response_class=HTMLResponse)
async def thanks(request: Request):
    html = f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'><title>Thank you — {ORG_NAME}</title>
<style>body{{font-family:'League Spartan',sans-serif;background:linear-gradient(157deg,#0d3350,#3f7cb4);min-height:100vh;
display:flex;align-items:center;justify-content:center;margin:0;padding:20px}}
.card{{background:#fff;border-radius:22px;max-width:440px;padding:40px;text-align:center;box-shadow:0 24px 60px rgba(0,0,0,.25)}}
h1{{font-family:'Playfair Display',serif;color:#113d5d}}p{{color:#6b6f79}}</style></head>
<body><div class=card><div style='font-size:3rem'>✅</div><h1>Payment received</h1>
<p>Thank you! A receipt has been emailed to you. If you have any questions, reply to your receipt or contact our team.</p>
</div></body></html>"""
    return HTMLResponse(html)
