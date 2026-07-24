"""BBU-branded HTML for the affiliate program (join, portal, admin).

Reuses the shell + brand tokens from branding.py so the affiliate pages match
the storefront/checkout. Self-contained (inline CSS/JS) so nothing depends on
the Next.js frontend build.
"""
from src.bbu_payments.branding import _shell, _price, NAVY, STEEL, ICE


def _money(cents):
    return _price(cents or 0)


# --------------------------------------------------------------------------- #
def join_page(base):
    inner = (
        f"<div class='checkout'>"
        f"<span class='eyebrow'>Affiliate Program</span>"
        f"<h1 style='font-size:2rem;margin:12px 0 6px'>Earn 50% for every referral</h1>"
        f"<p style='color:#4a5b68;margin-bottom:8px'>Share Birth &amp; Baby University's trainings and classes, "
        f"and earn 50% commission on every enrollment you send — paid straight to your bank.</p>"
        f"<div style='height:14px'></div>"
        f"<label for='name'>Your name</label>"
        f"<input id='name' type='text' placeholder='Jane Doe'>"
        f"<div style='height:14px'></div>"
        f"<label for='email'>Email</label>"
        f"<input id='email' type='email' placeholder='you@example.com' required>"
        f"<div style='height:22px'></div>"
        f"<button class='btn' style='width:100%' id='go'>Create my affiliate account →</button>"
        f"<div class='methods'>Payouts handled securely by Stripe — you'll connect your bank next.</div>"
        f"</div>"
        f"<script>"
        f"const b=document.getElementById('go');"
        f"b.onclick=async()=>{{"
        f"const name=document.getElementById('name').value,email=document.getElementById('email').value;"
        f"if(!email){{alert('Enter your email');return}}"
        f"b.textContent='Setting up…';b.disabled=true;"
        f"const r=await fetch('{base}/api/v1/bbu/affiliate/join',{{method:'POST',"
        f"headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name,email}})}});"
        f"const d=await r.json();"
        f"if(d.onboarding_url){{window.location=d.onboarding_url}}else{{b.textContent='Error — try again';b.disabled=false}}"
        f"}};"
        f"</script>"
    )
    return _shell("Affiliate Program", inner)


# --------------------------------------------------------------------------- #
def portal_page(affiliate, earnings, payouts, base):
    link = f"{base}/api/v1/bbu/store?ref={affiliate.ref_code}"
    active = affiliate.status == "active"
    status_banner = "" if active else (
        f"<div class='card' style='padding:18px;margin-bottom:22px;background:{ICE}'>"
        f"<b>Finish setup:</b> connect your bank to start earning. "
        f"<a style='color:{STEEL};font-weight:600' href='{base}/api/v1/bbu/affiliate/onboard/{affiliate.ref_code}'>Complete Stripe onboarding →</a>"
        f"</div>"
    )
    stat = lambda label, val: (
        f"<div class='card' style='padding:22px'><div style='font-family:League Spartan;"
        f"font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:#6b6f79'>{label}</div>"
        f"<div class='price' style='margin-top:6px'>{val}</div></div>"
    )
    stats = (
        f"<div class='grid' style='grid-template-columns:repeat(4,1fr);gap:16px;margin:22px 0'>"
        + stat("Referred sales", str(earnings['sales']))
        + stat("Pending", _money(earnings['pending']))
        + stat("Available", _money(earnings['available']))
        + stat("Paid out", _money(earnings['paid']))
        + "</div>"
    )
    payout_rows = "".join(
        f"<tr><td style='padding:8px 4px'>{p.period or '—'}</td><td>{_money(p.amount_cents)}</td>"
        f"<td><span class='pill'>{p.status}</span></td></tr>" for p in payouts
    ) or "<tr><td colspan='3' style='padding:12px 4px;color:#6b6f79'>No payouts yet — they'll appear here after your first monthly run.</td></tr>"

    inner = (
        f"<div class='wrap' style='max-width:900px;margin:44px auto'>"
        f"<span class='eyebrow'>Affiliate Dashboard</span>"
        f"<h1 style='font-size:2rem;margin:10px 0 4px'>Welcome{', ' + affiliate.name if affiliate.name else ''}</h1>"
        f"<p style='color:#4a5b68'>Status: <b style='color:{NAVY}'>{affiliate.status}</b> · Commission: <b>{int((affiliate.commission_rate or 0.5)*100)}%</b></p>"
        f"<div style='height:22px'></div>{status_banner}"
        f"<div class='card' style='padding:22px'>"
        f"<div style='font-family:League Spartan;font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:#6b6f79;margin-bottom:8px'>Your referral link</div>"
        f"<div style='display:flex;gap:10px;align-items:center'>"
        f"<input id='reflink' readonly value='{link}' style='flex:1'>"
        f"<button class='btn' style='padding:12px 20px' onclick=\"navigator.clipboard.writeText('{link}');this.textContent='Copied!'\">Copy</button>"
        f"</div></div>"
        f"{stats}"
        f"<div class='card' style='padding:22px'>"
        f"<h3 style='font-size:1.1rem;margin-bottom:10px'>Payout history</h3>"
        f"<table style='width:100%;border-collapse:collapse;font-size:.92rem'>"
        f"<thead><tr style='text-align:left;color:#6b6f79;font-family:League Spartan;font-size:.72rem;letter-spacing:.1em;text-transform:uppercase'>"
        f"<th style='padding:6px 4px'>Period</th><th>Amount</th><th>Status</th></tr></thead>"
        f"<tbody>{payout_rows}</tbody></table></div>"
        f"</div>"
    )
    return _shell("Affiliate Dashboard", inner)


# --------------------------------------------------------------------------- #
def admin_page(settings, affs, totals, earned, base, admin_key=""):
    rows = ""
    for a in affs:
        rows += (
            f"<tr>"
            f"<td style='padding:8px 4px'>{a.name or '—'}<br><span style='color:#6b6f79;font-size:.82rem'>{a.email}</span></td>"
            f"<td><code>{a.ref_code}</code></td>"
            f"<td><span class='pill'>{a.status}</span></td>"
            f"<td>{int((a.commission_rate if a.commission_rate is not None else settings.default_commission_rate)*100)}%</td>"
            f"<td>{_money(earned.get(a.id,0))}</td>"
            f"</tr>"
        )
    rows = rows or "<tr><td colspan='5' style='padding:12px 4px;color:#6b6f79'>No affiliates yet.</td></tr>"

    def setting_input(label, field, value, typ="text"):
        return (
            f"<label style='display:block;margin-top:10px'>{label}"
            f"<input data-field='{field}' type='{typ}' value='{value}' style='margin-top:4px'></label>"
        )

    inner = (
        f"<div class='wrap' style='max-width:1080px;margin:44px auto'>"
        f"<span class='eyebrow'>Affiliate Admin</span>"
        f"<h1 style='font-size:2rem;margin:10px 0 18px'>Affiliate program</h1>"
        f"<div class='grid' style='grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px'>"
        f"<div class='card' style='padding:22px'><div class='eyebrow'>Pending</div><div class='price'>{_money(totals['pending'])}</div></div>"
        f"<div class='card' style='padding:22px'><div class='eyebrow'>Available to pay</div><div class='price'>{_money(totals['available'])}</div></div>"
        f"<div class='card' style='padding:22px'><div class='eyebrow'>Paid out</div><div class='price'>{_money(totals['paid'])}</div></div>"
        f"</div>"
        f"<div style='display:flex;gap:12px;margin-bottom:24px'>"
        f"<button class='btn' id='runpay'>Run payouts now</button>"
        f"<button class='btn' id='drypay' style='background:{STEEL}'>Preview (dry run)</button>"
        f"</div>"
        # settings editor
        f"<div class='card' style='padding:24px;margin-bottom:24px'>"
        f"<h3 style='font-size:1.15rem;margin-bottom:6px'>Program settings</h3>"
        f"<p style='color:#6b6f79;font-size:.88rem'>Everything here is editable — no code changes needed.</p>"
        f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:0 20px'>"
        + setting_input("Commission rate (0.50 = 50%)", "default_commission_rate", settings.default_commission_rate)
        + setting_input("Commissionable events (comma-sep)", "commissionable_events", settings.commissionable_events)
        + setting_input("Commission basis", "commission_basis", settings.commission_basis)
        + setting_input("Attribution window (days)", "attribution_window_days", settings.attribution_window_days, "number")
        + setting_input("Refund hold (days)", "refund_hold_days", settings.refund_hold_days, "number")
        + setting_input("Min payout (cents)", "min_payout_cents", settings.min_payout_cents, "number")
        + setting_input("Payout schedule", "payout_schedule", settings.payout_schedule)
        + f"</div>"
        f"<button class='btn' id='savecfg' style='margin-top:16px'>Save settings</button>"
        f"</div>"
        # affiliates table
        f"<div class='card' style='padding:24px'>"
        f"<h3 style='font-size:1.15rem;margin-bottom:10px'>Affiliates ({len(affs)})</h3>"
        f"<table style='width:100%;border-collapse:collapse;font-size:.92rem'>"
        f"<thead><tr style='text-align:left;color:#6b6f79;font-family:League Spartan;font-size:.72rem;letter-spacing:.1em;text-transform:uppercase'>"
        f"<th style='padding:6px 4px'>Affiliate</th><th>Code</th><th>Status</th><th>Rate</th><th>Earned</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        f"</div>"
        f"<script>"
        f"const KEY={admin_key!r};"
        f"async function post(url,data){{data=data||{{}};if(KEY)data.key=KEY;const r=await fetch(url,{{method:'POST',"
        f"credentials:'include',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}});return r.json()}}"
        f"document.getElementById('savecfg').onclick=async()=>{{"
        f"const o={{}};document.querySelectorAll('[data-field]').forEach(i=>{{"
        f"let v=i.value;if(i.type==='number')v=parseFloat(v);o[i.dataset.field]=v}});"
        f"await post('{base}/api/v1/bbu/affiliate/admin/settings',o);alert('Saved')}};"
        f"document.getElementById('runpay').onclick=async()=>{{if(!confirm('Run real payouts now?'))return;"
        f"const d=await post('{base}/api/v1/bbu/affiliate/admin/payouts/run',{{}});alert(JSON.stringify(d.results,null,1))}};"
        f"document.getElementById('drypay').onclick=async()=>{{"
        f"const d=await post('{base}/api/v1/bbu/affiliate/admin/payouts/run',{{dry_run:true}});alert('Preview:\\n'+JSON.stringify(d.results,null,1))}};"
        f"</script>"
    )
    return _shell("Affiliate Admin", inner)
