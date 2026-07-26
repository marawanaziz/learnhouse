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


def _shell(title, inner, payment=True):
    """Branded page wrapper. `payment=False` drops the Stripe footer — on a
    sponsored-access page it directly contradicts the page ("nothing to pay")
    and makes a free grant seat look like it's about to ask for a card."""
    foot = ("© Birth &amp; Baby University · Secure checkout by Stripe" if payment
            else "© Birth &amp; Baby University")
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title} · Birth &amp; Baby University</title>{_FONTS}"
        f"<style>{_BASE_CSS}</style></head><body>"
        f"<div class='nav'><div class='wrap'><img src='{LOGO}' alt='Birth & Baby University'></div></div>"
        f"{inner}"
        f"<div class='foot'>{foot}</div>"
        f"</body></html>"
    )


def _price(cents, cur="usd"):
    return f"${cents/100:,.0f}" if cents % 100 == 0 else f"${cents/100:,.2f}"


def _price_block(p, discount_cents=0, coupon_code=""):
    """Price line for the checkout page. With a URL coupon applied we show the
    original struck through next to the amount actually charged, so the buyer
    can see the discount landed before they ever reach Stripe."""
    if discount_cents and discount_cents > 0:
        net = max(0, p.price_cents - discount_cents)
        return (
            "<div class='price' style='margin:18px 0;display:flex;align-items:baseline;gap:12px'>"
            f"<span style='font-size:.55em;color:#8a97a3;text-decoration:line-through'>"
            f"{_price(p.price_cents, p.currency)}</span>"
            f"<span>{_price(net, p.currency)}</span></div>"
            "<div style='display:inline-block;background:#EBF7FF;border:1px solid rgba(0,178,255,.35);"
            "border-radius:999px;padding:6px 16px;font-size:.8rem;font-weight:700;color:#113D5D;"
            f"letter-spacing:.08em;text-transform:uppercase'>Discount applied &mdash; save "
            f"{_price(discount_cents, p.currency)}</div>"
        )
    return f"<div class='price' style='margin:18px 0'>{_price(p.price_cents, p.currency)}</div>"


def store_page(products, base):
    cards = ""
    if not products:
        cards = ("<p style='margin:40px 0;color:#6b6f79'>No products published yet. "
                 "Add products in the admin, then they appear here.</p>")
    for p in products:
        label = {"bundle": "Bundle", "ebook": "E-book"}.get(p.kind, "Training")
        cta = "Buy &amp; download" if p.kind == "ebook" else "Enroll now"
        cards += (
            f"<div class='card'><div class='thumb'"
            + (f" style=\"background:#fff url('{p.image_url}') center/cover\"" if p.image_url else "")
            + f"></div><div class='body'>"
            f"<span class='pill'>{label}</span>"
            f"<h3>{p.name}</h3>"
            f"<p style='color:#4a5b68;font-size:.92rem'>{(p.description or '')[:130]}</p>"
            f"<div class='price'>{_price(p.price_cents, p.currency)}</div>"
            f"<a class='btn' href='{base}/api/v1/bbu/buy/{p.id}'>{cta}</a>"
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


def waitlist_page(p, base, program):
    """Shown instead of the pay button when every upcoming cohort is full."""
    inner = (
        f"<div class='checkout'>"
        f"<span class='eyebrow'>Join the waitlist</span>"
        f"<h1 style='font-size:2rem;margin:12px 0 6px'>{p.name}</h1>"
        f"<p style='color:#4a5b68;margin-bottom:6px'>Our upcoming cohorts are currently full. "
        f"Add your details and we'll message you the moment a spot opens up — no charge to join.</p>"
        f"<div style='height:10px'></div>"
        f"<label for='wname'>Your name</label>"
        f"<input id='wname' type='text' placeholder='First and last name'>"
        f"<label for='wemail' style='margin-top:10px;display:block'>Email</label>"
        f"<input id='wemail' type='email' placeholder='you@example.com' required>"
        f"<label for='wphone' style='margin-top:10px;display:block'>Mobile (for a text when a spot opens)</label>"
        f"<input id='wphone' type='tel' placeholder='(555) 555-5555'>"
        f"<div style='height:18px'></div>"
        f"<button class='btn' style='width:100%' id='join'>Join the waitlist →</button>"
        f"<div class='methods' id='wmsg'></div>"
        f"</div>"
        f"<script>"
        f"const jb=document.getElementById('join');"
        f"jb.onclick=async()=>{{"
        f"const email=document.getElementById('wemail').value;"
        f"if(!email){{document.getElementById('wmsg').textContent='Please enter your email.';return;}}"
        f"jb.textContent='Joining…';jb.disabled=true;"
        f"const r=await fetch('{base}/api/v1/bbu/cohort-waitlist',{{method:'POST',"
        f"headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{product_id:{p.id},"
        f"email,name:document.getElementById('wname').value,phone:document.getElementById('wphone').value}})}});"
        f"const d=await r.json();"
        f"if(d.ok){{document.querySelector('.checkout').innerHTML="
        f"\"<div style='text-align:center'><div style='font-size:3rem'>✅</div>"
        f"<h1 style='font-size:1.8rem;margin:12px 0'>You're on the list!</h1>"
        f"<p style='color:#4a5b68'>We'll reach out the moment a spot opens up.\"+"
        f"(d.position?(' You're #'+d.position+' in line.'):'')+\"</p></div>\";}}"
        f"else{{jb.textContent='Try again';jb.disabled=false;document.getElementById('wmsg').textContent=(d.error||'Something went wrong.');}}"
        f"}};"
        f"</script>"
    )
    return _shell(f"Waitlist · {p.name}", inner)


def checkout_page(p, pub_key, base, sold_out=False, program="", coupon_code="", discount_cents=0):
    if sold_out:
        return waitlist_page(p, base, program)
    is_ebook = getattr(p, "kind", "") == "ebook"
    eyebrow = "Buy the e-book" if is_ebook else "Enroll"
    email_label = ("Email for your download link &amp; receipt" if is_ebook
                   else "Email for your access &amp; receipt")
    inner = (
        f"<div class='checkout'>"
        f"<span class='eyebrow'>{eyebrow}</span>"
        f"<h1 style='font-size:2rem;margin:12px 0 6px'>{p.name}</h1>"
        f"<p style='color:#4a5b68;margin-bottom:8px'>{(p.description or '')[:200]}</p>"
        f"{_price_block(p, discount_cents, coupon_code)}"
        f"<label for='email'>{email_label}</label>"
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
        f"headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{product_id:{p.id},email,ref:decodeURIComponent(ref),coupon:'{coupon_code}'}})}});"
        f"const d=await r.json();"
        f"if(d.url){{window.location=d.url}}else if(d.waitlist){{window.location='{base}/api/v1/bbu/buy/{p.id}'}}else{{btn.textContent='Error — try again';btn.disabled=false;}}"
        f"}};"
        f"</script>"
    )
    return _shell(f"Enroll · {p.name}", inner)


def success_page(order, base):
    paid = order and order.status == "paid"
    is_ebook = bool(order and getattr(order, "download_token", ""))
    if is_ebook:
        headline = "Your download is ready!"
        status_line = "Thanks for your purchase — grab your e-book below." if paid \
            else "Payment received — preparing your download."
        cta = (f"<a class='btn' href='{base}/api/v1/bbu/ebook/download/{order.download_token}'>"
               f"⬇ Download your e-book</a>"
               f"<p style='margin-top:14px;color:#6b6f79;font-size:.85rem'>"
               f"We've also emailed this link to you.</p>")
    else:
        headline = "You're in!"
        status_line = "Your enrollment is confirmed — you're signed in and ready to start." if paid \
            else "Payment received — finalizing your enrollment."
        # Deep-link to the course they actually bought. "/courses" made a buyer
        # hunt for it, and a bundle buyer landed on a list with no indication of
        # what was theirs.
        first = ""
        try:
            first = [u for u in (order.course_uuids or "").split(",") if u][0] if order else ""
        except Exception:
            first = ""
        target = f"{base}/course/{first}" if first else f"{base}/courses"
        label = "Start your course →" if first else "Go to my courses →"
        prefill = ""
        try:
            prefill = ((order.extra or {}).get("customer_name") or "") if order else ""
        except Exception:
            prefill = ""
        # Finish the account here rather than before payment: an extra two
        # fields in front of checkout costs sales on a 24-hour offer, and at
        # this point they are already signed in, so this is a plain
        # "set my own password".
        cta = (
            f"<a class='btn' href='{target}'>{label}</a>"
            f"<div style='margin-top:26px;padding-top:22px;border-top:1px solid rgba(17,61,93,.1);text-align:left'>"
            f"<div class='eyebrow' style='margin-bottom:6px'>One last step</div>"
            f"<p style='color:#4a5b68;font-size:.92rem;margin-bottom:12px'>"
            f"Set a password so you can sign back in any time. You're already "
            f"signed in — this takes ten seconds.</p>"
            f"<label for='acc-name'>Your name</label>"
            f"<input id='acc-name' value='{prefill}' placeholder='First and last name'>"
            f"<label for='acc-pw' style='display:block;margin-top:12px'>Choose a password</label>"
            f"<input id='acc-pw' type='password' placeholder='At least 8 characters'>"
            f"<button class='btn' style='margin-top:14px;width:100%' onclick='saveAcct()'>"
            f"Save &amp; finish</button>"
            f"<p id='acc-msg' style='margin-top:10px;font-size:.85rem;color:#6b6f79'></p>"
            f"</div>"
            f"<script>function saveAcct(){{"
            f"var n=document.getElementById('acc-name').value,"
            f"p=document.getElementById('acc-pw').value,"
            f"m=document.getElementById('acc-msg');"
            f"if(p.length<8){{m.textContent='Please use at least 8 characters.';return;}}"
            f"m.textContent='Saving...';"
            f"fetch('{base}/api/v1/bbu/complete-account',{{method:'POST',"
            f"credentials:'include',headers:{{'Content-Type':'application/json'}},"
            f"body:JSON.stringify({{name:n,password:p}})}})"
            f".then(function(r){{return r.json().then(function(d){{return {{ok:r.ok,d:d}};}});}})"
            f".then(function(x){{m.textContent=x.ok?'Saved — you can now sign in with '"
            f"+x.d.email+' any time.':(x.d.detail||'Something went wrong.');}})"
            f".catch(function(){{m.textContent='Something went wrong.';}});}}</script>"
        )
    # Reseller/bulk pack: link the buyer straight to their self-serve seat portal.
    seat_token = ((getattr(order, "extra", None) or {}).get("seat_owner_token")) if order else None
    if seat_token:
        seats = (getattr(order, "extra", None) or {}).get("seat_count", "")
        headline = "Your seats are ready!"
        status_line = (f"You've got {seats} seats to share with your team."
                       if seats else "Share access with your team below.")
        cta = (f"<a class='btn' href='{base}/api/v1/bbu/seats/portal?token={seat_token}'>"
               f"Manage &amp; share your seats →</a>"
               f"<p style='margin-top:12px;color:#6b6f79;font-size:.85rem'>"
               f"Bookmark this — it's your private link to view and share seats anytime.</p>")
    inner = (
        f"<div class='checkout' style='text-align:center'>"
        f"<div style='font-size:3rem'>{'📘' if is_ebook else '🎉'}</div>"
        f"<h1 style='font-size:2rem;margin:12px 0'>{headline}</h1>"
        f"<p style='color:#4a5b68'>{status_line}</p>"
        + (f"<p style='margin-top:10px;color:#6b6f79;font-size:.9rem'>Receipt sent to {order.email}</p>" if order and order.email else "")
        + f"<div style='height:24px'></div>"
        f"{cta}"
        f"</div>"
    )
    return _shell(headline, inner)
