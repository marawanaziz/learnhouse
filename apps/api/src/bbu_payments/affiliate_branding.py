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
        f"if(d.onboarding_url){{window.top.location=d.onboarding_url}}else{{b.textContent='Error — try again';b.disabled=false}}"
        f"}};"
        f"</script>"
    )
    return _shell("Affiliate Program", inner)


# --------------------------------------------------------------------------- #
def portal_page(affiliate, earnings, payouts, base):
    link = f"{base}/api/v1/bbu/r/{affiliate.ref_code}"
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
    referral_rows = "".join(
        f"<tr><td style='padding:8px 4px'>{row.get('date') or '—'}</td>"
        f"<td>{row.get('customer') or 'Referral'}</td>"
        f"<td>{row.get('product') or '—'}</td>"
        f"<td>{_money(row.get('sale_amount_cents'))}</td>"
        f"<td>{_money(row.get('commission_amount_cents'))}</td>"
        f"<td><span class='pill'>{row.get('status') or 'pending'}</span></td></tr>"
        for row in earnings.get("details", [])
    ) or "<tr><td colspan='6' style='padding:12px 4px;color:#6b6f79'>No referred sales yet.</td></tr>"

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
        f"<div class='card' style='padding:22px;margin-bottom:22px;overflow-x:auto'>"
        f"<h3 style='font-size:1.1rem;margin-bottom:10px'>Referral history</h3>"
        f"<table style='width:100%;border-collapse:collapse;font-size:.92rem;min-width:700px'>"
        f"<thead><tr style='text-align:left;color:#6b6f79;font-family:League Spartan;font-size:.72rem;letter-spacing:.1em;text-transform:uppercase'>"
        f"<th style='padding:6px 4px'>Date</th><th>Customer</th><th>Product</th><th>Sale</th><th>Commission</th><th>Status</th></tr></thead>"
        f"<tbody>{referral_rows}</tbody></table></div>"
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
def _detail_js(base: str) -> str:
    """Extra admin JS (plain string so JS braces don't need f-string escaping)."""
    js = r"""
const MINI="border:1px solid #cfe0ec;background:#f4f9fd;color:#113d5d;border-radius:999px;padding:5px 11px;font-size:.76rem;cursor:pointer;font-family:'League Spartan',sans-serif;font-weight:700";
function cpy(t,b){navigator.clipboard.writeText(t).then(function(){var o=b.textContent;b.textContent='Copied ✓';setTimeout(function(){b.textContent=o},1200)})}
function esc(s){return (s==null?'':String(s)).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c]})}
async function getj(u){var url=KEY?(u+(u.indexOf('?')>-1?'&':'?')+'key='+encodeURIComponent(KEY)):u;var r=await fetch(url,{credentials:'include'});return r.json()}
function linkRow(label,link){if(!link)return '';return '<div style="margin:6px 0"><div style="font-size:.7rem;color:#6b6f79;text-transform:uppercase;letter-spacing:.08em;font-family:League Spartan">'+label+'</div><div style="display:flex;gap:6px;align-items:center"><input readonly value="'+esc(link)+'" style="flex:1;padding:7px 9px;border:1px solid rgba(17,61,93,.2);border-radius:8px;font-size:.8rem"><button style="'+MINI+'" onclick="cpy(\''+link+'\',this)">Copy</button></div></div>'}
async function openDetail(id){
  var d=await getj('__BASE__/api/v1/bbu/affiliate/admin/detail/'+id);
  if(d.detail){alert(d.detail);return}
  var ref=(d.referred||[]).map(function(r){return '<tr><td style="padding:5px 4px">'+esc(r.email)+'</td><td>'+esc(r.product)+'</td><td>$'+r.amount+'</td><td>'+esc(r.status)+'</td><td style="color:#6b6f79">'+esc(r.date)+'</td></tr>'}).join('')||'<tr><td colspan=5 style="color:#6b6f79;padding:8px 4px">No referred enrollments yet.</td></tr>';
  var com=(d.commissions||[]).map(function(c){return '<tr><td style="padding:5px 4px">$'+c.amount+'</td><td>'+esc(c.status)+'</td><td>'+esc(c.event)+'</td><td style="color:#6b6f79">'+esc(c.date)+'</td></tr>'}).join('')||'<tr><td colspan=4 style="color:#6b6f79;padding:8px 4px">None yet.</td></tr>';
  var totalEarned=(d.earned.pending+d.earned.available+d.earned.paid).toFixed(2);
  var CARD='background:#fff;border-radius:14px;padding:18px;box-shadow:0 6px 18px rgba(17,61,93,.05);margin-bottom:16px';
  var STAT='flex:1;min-width:110px;background:#fff;border-radius:12px;padding:14px;box-shadow:0 6px 18px rgba(17,61,93,.05)';
  document.getElementById('detailbody').innerHTML=
    '<div style="position:sticky;top:0;background:#fff;border-bottom:1px solid #e2ebf2;padding:18px 22px;display:flex;justify-content:space-between;align-items:center">'
    +'<div><div style="font-size:1.3rem;font-weight:700;color:#113d5d;font-family:Playfair Display,serif">'+esc(d.name||d.email)+'</div>'
    +'<div style="color:#6b6f79;font-size:.85rem">'+esc(d.email)+' · '+esc(d.ref_code)+' · '+esc(d.status)+' · '+d.rate+'%</div></div>'
    +'<div style="display:flex;gap:6px">'
    +'<button style="'+MINI+'" onclick="setAff('+id+',\''+(d.status==='suspended'?'active':'suspended')+'\')">'+(d.status==='suspended'?'Reactivate':'Suspend')+'</button>'
    +'<button style="border:1px solid #f0c9c9;background:#fdf3f3;color:#a12a2a;border-radius:999px;padding:5px 11px;font-size:.76rem;cursor:pointer;font-family:League Spartan;font-weight:700" onclick="delAff('+id+')">Remove</button>'
    +'<button style="'+MINI+'" onclick="document.getElementById(\'detail\').style.display=\'none\'">Close</button></div></div>'
    +'<div style="padding:20px 22px">'
    +'<div style="display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap">'
    +'<div style="'+STAT+'"><div style="font-size:.7rem;color:#6b6f79;text-transform:uppercase">Clicks</div><div style="font-size:1.4rem;font-weight:700;color:#113d5d">'+d.clicks+'</div></div>'
    +'<div style="'+STAT+'"><div style="font-size:.7rem;color:#6b6f79;text-transform:uppercase">Leads</div><div style="font-size:1.4rem;font-weight:700;color:#113d5d">'+(d.leads||0)+'</div></div>'
    +'<div style="'+STAT+'"><div style="font-size:.7rem;color:#6b6f79;text-transform:uppercase">Enrolled</div><div style="font-size:1.4rem;font-weight:700;color:#113d5d">'+d.converted+'</div></div>'
    +'<div style="'+STAT+'"><div style="font-size:.7rem;color:#6b6f79;text-transform:uppercase">Earned</div><div style="font-size:1.4rem;font-weight:700;color:#113d5d">$'+totalEarned+'</div></div></div>'
    +'<div style="'+CARD+'"><h3 style="margin:0 0 8px;font-size:1rem;color:#113d5d">Their links — copy &amp; send</h3>'+linkRow('Referral link (share this)',d.referral_link)+linkRow('Private earnings portal',d.portal_link)+'</div>'
    +'<div style="'+CARD+'"><h3 style="margin:0 0 8px;font-size:1rem;color:#113d5d">Who enrolled through them ('+d.converted+')</h3>'
    +'<table style="width:100%;border-collapse:collapse;font-size:.85rem"><thead><tr style="text-align:left;color:#6b6f79;font-size:.7rem;text-transform:uppercase"><th style="padding:4px">Email</th><th>Product</th><th>Amount</th><th>Status</th><th>Date</th></tr></thead><tbody>'+ref+'</tbody></table></div>'
    +'<div style="'+CARD+'"><h3 style="margin:0 0 8px;font-size:1rem;color:#113d5d">Commissions — pending $'+d.earned.pending+' · available $'+d.earned.available+' · paid $'+d.earned.paid+'</h3>'
    +'<table style="width:100%;border-collapse:collapse;font-size:.85rem"><thead><tr style="text-align:left;color:#6b6f79;font-size:.7rem;text-transform:uppercase"><th style="padding:4px">Amount</th><th>Status</th><th>Event</th><th>Date</th></tr></thead><tbody>'+com+'</tbody></table></div>'
    +'</div>';
  document.getElementById('detail').style.display='flex';
}
async function setAff(id,status){var d=await post('__BASE__/api/v1/bbu/affiliate/admin/set-status',{id:id,status:status});if(d.ok){location.reload()}else{alert(d.detail||'Error')}}
async function delAff(id){if(!confirm('Remove this affiliate? Their referral link will stop working. This cannot be undone.'))return;var d=await post('__BASE__/api/v1/bbu/affiliate/admin/set-status',{id:id,delete:true});if(d.ok){document.getElementById('detail').style.display='none';location.reload()}else{alert(d.detail||'Error')}}
document.getElementById('addaff').onclick=async function(){var name=document.getElementById('na-name').value;var email=document.getElementById('na-email').value;if(!email){alert('Email required');return}var d=await post('__BASE__/api/v1/bbu/affiliate/admin/create',{name:name,email:email});if(d.ok){alert('Added. Referral code: '+d.ref_code);location.reload()}else{alert(d.detail||'Error')}};
"""
    return js.replace("__BASE__", base)


def admin_page(settings, affs, totals, earned, base, admin_key=""):
    _mini = "border:1px solid #cfe0ec;background:#f4f9fd;color:#113d5d;border-radius:999px;padding:5px 11px;font-size:.76rem;cursor:pointer;font-family:'League Spartan',sans-serif;font-weight:700"
    rows = ""
    for a in affs:
        rate_pct = int((a.commission_rate if a.commission_rate is not None else settings.default_commission_rate) * 100)
        reflink = f"{base}/api/v1/bbu/r/{a.ref_code}"
        rows += (
            f"<tr>"
            f"<td style='padding:8px 4px'><a href='#' onclick='openDetail({a.id});return false' style='color:#113d5d;font-weight:700;text-decoration:none'>{a.name or a.email}</a>"
            f"<br><span style='color:#6b6f79;font-size:.82rem'>{a.email}</span></td>"
            f"<td><code>{a.ref_code}</code></td>"
            f"<td><span class='pill'>{a.status}</span></td>"
            f"<td>{rate_pct}%</td>"
            f"<td>{_money(earned.get(a.id,0))}</td>"
            f"<td style='white-space:nowrap'><button style=\"{_mini}\" onclick=\"cpy('{reflink}',this)\">Copy link</button> "
            f"<button style=\"{_mini}\" onclick='openDetail({a.id})'>View</button></td>"
            f"</tr>"
        )
    rows = rows or "<tr><td colspan='6' style='padding:12px 4px;color:#6b6f79'>No affiliates yet.</td></tr>"

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
        + setting_input("Default commission rate (%) — e.g. 50", "default_commission_rate", int(round((settings.default_commission_rate or 0) * 100)), "number")
        + setting_input("Commissionable events (comma-sep)", "commissionable_events", settings.commissionable_events)
        + setting_input("Commission basis", "commission_basis", settings.commission_basis)
        + setting_input("Attribution window (days)", "attribution_window_days", settings.attribution_window_days, "number")
        + setting_input("Refund hold (days)", "refund_hold_days", settings.refund_hold_days, "number")
        + setting_input("Minimum payout ($)", "min_payout_dollars",
                      round((settings.min_payout_cents or 0) / 100, 2), "number")
        + setting_input("Payout schedule", "payout_schedule", settings.payout_schedule)
        + f"</div>"
        f"<button class='btn' id='savecfg' style='margin-top:16px'>Save settings</button>"
        f"</div>"
        # affiliates table + add
        f"<div class='card' style='padding:24px'>"
        f"<div style='display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:12px'>"
        f"<h3 style='font-size:1.15rem;margin:0'>Affiliates ({len(affs)})</h3>"
        f"<div style='display:flex;gap:6px;align-items:center'>"
        f"<input id='na-name' placeholder='Name' style='padding:7px 10px;border:1px solid rgba(17,61,93,.2);border-radius:8px;font-size:.85rem'>"
        f"<input id='na-email' placeholder='Email' style='padding:7px 10px;border:1px solid rgba(17,61,93,.2);border-radius:8px;font-size:.85rem'>"
        f"<button class='btn' style='padding:8px 16px' id='addaff'>Add affiliate</button></div></div>"
        f"<table style='width:100%;border-collapse:collapse;font-size:.92rem'>"
        f"<thead><tr style='text-align:left;color:#6b6f79;font-family:League Spartan;font-size:.72rem;letter-spacing:.1em;text-transform:uppercase'>"
        f"<th style='padding:6px 4px'>Affiliate</th><th>Code</th><th>Status</th><th>Rate</th><th>Earned</th><th></th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        f"</div>"
        # detail modal
        f"<div id='detail' style='display:none;position:fixed;inset:0;background:rgba(17,61,93,.4);z-index:50;justify-content:flex-end' onclick='if(event.target===this)this.style.display=\"none\"'>"
        f"<div style='width:100%;max-width:680px;height:100%;background:#f8f8f8;overflow-y:auto' id='detailbody'></div></div>"
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
        + _detail_js(base)
        + "</script>"
    )
    return _shell("Affiliate Admin", inner)
