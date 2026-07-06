"""BBU-branded HTML for the storefront + Stripe checkout.

Brand system (Branding.pdf, Jul 2026): Playfair Display Bold + League Spartan +
Open Sans; palette #90cbf0 / #6da0db / #113d5d / #f8f8f8 (+ #3a91c6, #ebf7ff).
Self-contained pages (inline CSS, Stripe.js from js.stripe.com) so the payment
flow is demonstrable without touching the Next.js frontend build.
"""

NAVY = "#113d5d"
SKY = "#90cbf0"
PERI = "#6da0db"
STEEL = "#3a91c6"
ICE = "#ebf7ff"
PAPER = "#f8f8f8"
LOGO = "https://birthandbabyuniversity.com/wp-content/uploads/2024/03/birth-and-baby-logo-tm.png"

_FONTS = (
    "<link rel='preconnect' href='https://fonts.googleapis.com'>"
    "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
    "<link href='https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&"
    "family=League+Spartan:wght@400;500;600;700&family=Open+Sans:wght@400;500;600&display=swap' rel='stylesheet'>"
)

_BASE_CSS = f"""
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Open Sans',system-ui,sans-serif;color:{NAVY};background:{PAPER};line-height:1.6}}
h1,h2,h3{{font-family:'Playfair Display',Georgia,serif;color:{NAVY};line-height:1.1}}
.eyebrow{{font-family:'League Spartan',sans-serif;font-weight:600;letter-spacing:.28em;
text-transform:uppercase;font-size:.72rem;color:{STEEL}}}
.nav{{background:#fff;border-bottom:1px solid rgba(17,61,93,.08);padding:18px 0}}
.wrap{{max-width:1120px;margin:0 auto;padding:0 24px}}
.nav img{{height:64px}}
.btn{{font-family:'League Spartan',sans-serif;font-weight:700;letter-spacing:.04em;
background:{NAVY};color:#fff;border:none;border-radius:999px;padding:15px 34px;font-size:1rem;
cursor:pointer;text-decoration:none;display:inline-block;transition:transform .2s,background .2s}}
.btn:hover{{background:{STEEL};transform:translateY(-1px)}}
.hero{{background:linear-gradient(180deg,#fff 0%,{ICE} 100%);padding:64px 0 72px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:26px;margin:44px 0}}
.card{{background:#fff;border:1px solid rgba(17,61,93,.08);border-radius:18px;overflow:hidden;
display:flex;flex-direction:column;transition:box-shadow .3s,transform .3s}}
.card:hover{{box-shadow:0 20px 50px rgba(17,61,93,.14);transform:translateY(-4px)}}
.card .thumb{{height:150px;background:linear-gradient(135deg,{SKY},{PERI})}}
.card .body{{padding:22px;display:flex;flex-direction:column;gap:10px;flex:1}}
.card h3{{font-size:1.22rem}}
.price{{font-family:'League Spartan',sans-serif;font-weight:700;font-size:1.5rem;color:{NAVY}}}
.card .btn{{margin-top:auto;text-align:center;padding:12px}}
.pill{{display:inline-block;font-family:'League Spartan',sans-serif;font-weight:600;font-size:.7rem;
letter-spacing:.12em;text-transform:uppercase;color:{STEEL};background:{ICE};border-radius:999px;padding:5px 14px}}
.foot{{color:#6b6f79;font-size:.85rem;padding:40px 0;text-align:center}}
input{{font-family:'Open Sans';width:100%;padding:13px 15px;border:1px solid rgba(17,61,93,.2);
border-radius:12px;font-size:1rem;margin-top:8px}}
.checkout{{max-width:560px;margin:56px auto;background:#fff;border:1px solid rgba(17,61,93,.08);
border-radius:22px;padding:40px}}
label{{font-family:'League Spartan',sans-serif;font-weight:600;font-size:.8rem;letter-spacing:.06em;text-transform:uppercase}}
.methods{{color:#6b6f79;font-size:.82rem;margin-top:16px}}
"""


def _shell(title, inner):
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title} · Birth &amp; Baby University</title>{_FONTS}"
        f"<style>{_BASE_CSS}</style></head><body>"
        f"<div class='nav'><div class='wrap'><img src='{LOGO}' alt='Birth & Baby University'></div></div>"
        f"{inner}"
        f"<div class='foot'>© Birth &amp; Baby University · Secure checkout by Stripe</div>"
        f"</body></html>"
    )


def _price(cents, cur="usd"):
    return f"${cents/100:,.0f}" if cents % 100 == 0 else f"${cents/100:,.2f}"


def store_page(products, base):
    cards = ""
    if not products:
        cards = ("<p style='margin:40px 0;color:#6b6f79'>No products published yet. "
                 "Add products in the admin, then they appear here.</p>")
    for p in products:
        cards += (
            f"<div class='card'><div class='thumb'></div><div class='body'>"
            f"<span class='pill'>{'Bundle' if p.kind=='bundle' else 'Training'}</span>"
            f"<h3>{p.name}</h3>"
            f"<p style='color:#4a5b68;font-size:.92rem'>{(p.description or '')[:130]}</p>"
            f"<div class='price'>{_price(p.price_cents, p.currency)}</div>"
            f"<a class='btn' href='{base}/api/v1/bbu/buy/{p.id}'>Enroll now</a>"
            f"</div></div>"
        )
    inner = (
        f"<div class='hero'><div class='wrap'>"
        f"<span class='eyebrow'>Birth &amp; Baby University</span>"
        f"<h1 style='font-size:clamp(2.4rem,5vw,3.6rem);margin:14px 0 10px'>Doula training &amp; perinatal courses</h1>"
        f"<p style='max-width:620px;color:#4a5b68;font-size:1.08rem'>Nationally recognized certification training, "
        f"mentorship, and childbirth education — learn at your own pace.</p>"
        f"</div></div>"
        f"<div class='wrap'><div class='grid'>{cards}</div></div>"
    )
    return _shell("Course Catalog", inner)


def checkout_page(p, pub_key, base):
    inner = (
        f"<div class='checkout'>"
        f"<span class='eyebrow'>Enroll</span>"
        f"<h1 style='font-size:2rem;margin:12px 0 6px'>{p.name}</h1>"
        f"<p style='color:#4a5b68;margin-bottom:8px'>{(p.description or '')[:200]}</p>"
        f"<div class='price' style='margin:18px 0'>{_price(p.price_cents, p.currency)}</div>"
        f"<label for='email'>Email for your access &amp; receipt</label>"
        f"<input id='email' type='email' placeholder='you@example.com' required>"
        f"<div style='height:22px'></div>"
        f"<button class='btn' style='width:100%' id='pay'>Proceed to secure checkout →</button>"
        f"<div class='methods'>💳 Cards · HSA/FSA · Klarna · Apple Pay — powered by Stripe</div>"
        f"</div>"
        f"<script src='https://js.stripe.com/v3/'></script>"
        f"<script>"
        f"const btn=document.getElementById('pay');"
        f"btn.onclick=async()=>{{"
        f"const email=document.getElementById('email').value;"
        f"btn.textContent='Redirecting…';btn.disabled=true;"
        f"const ref=(document.cookie.match(/(?:^|; )bbu_ref=([^;]+)/)||[])[1]||'';"
        f"const r=await fetch('{base}/api/v1/bbu/checkout',{{method:'POST',"
        f"headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{product_id:{p.id},email,ref:decodeURIComponent(ref)}})}});"
        f"const d=await r.json();"
        f"if(d.url){{window.location=d.url}}else{{btn.textContent='Error — try again';btn.disabled=false;}}"
        f"}};"
        f"</script>"
    )
    return _shell(f"Enroll · {p.name}", inner)


def success_page(order, base):
    paid = order and order.status == "paid"
    status_line = ("Your enrollment is confirmed." if paid
                   else "Payment received — finalizing your enrollment.")
    inner = (
        f"<div class='checkout' style='text-align:center'>"
        f"<div style='font-size:3rem'>🎉</div>"
        f"<h1 style='font-size:2rem;margin:12px 0'>You're in!</h1>"
        f"<p style='color:#4a5b68'>{status_line}</p>"
        + (f"<p style='margin-top:10px;color:#6b6f79;font-size:.9rem'>Receipt sent to {order.email}</p>" if order and order.email else "")
        + f"<div style='height:24px'></div>"
        f"<a class='btn' href='{base}/courses'>Go to my courses →</a>"
        f"</div>"
    )
    return _shell("Enrollment confirmed", inner)
