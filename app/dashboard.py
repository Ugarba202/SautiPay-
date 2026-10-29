from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional
import json

from app.models import db_session
from app.ledger import Ledger
from app.rate_oracle import rate_oracle
from app.lightning_service import lightning_service
from app.config import settings

dashboard_router = APIRouter()

HTML_BASE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SautiPay — Merchant Settlement & Control Room</title>
    <style>
        :root {{
            --bg: #0d1117;
            --surface: #161b22;
            --border: #30363d;
            --text: #c9d1d9;
            --accent: #f7931a; /* Bitcoin orange */
            --green: #2ea043;
            --red: #da3633;
            --blue: #58a6ff;
        }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 20px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 15px;
            margin-bottom: 25px;
        }}
        .badge {{
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.85rem;
            font-weight: 600;
        }}
        .badge-green {{ background: rgba(46,160,67,0.2); color: var(--green); border: 1px solid var(--green); }}
        .badge-orange {{ background: rgba(247,147,26,0.2); color: var(--accent); border: 1px solid var(--accent); }}
        .badge-red {{ background: rgba(218,54,51,0.2); color: var(--red); border: 1px solid var(--red); }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 20px;
        }}
        .chain-container {{
            display: flex;
            gap: 15px;
            overflow-x: auto;
            padding: 15px 0;
        }}
        .block {{
            background: var(--surface);
            border: 2px solid var(--green);
            border-radius: 8px;
            min-width: 260px;
            padding: 15px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        }}
        .block-tampered {{
            border-color: var(--red) !important;
        }}
        .btn {{
            background: #21262d;
            color: var(--text);
            border: 1px solid var(--border);
            padding: 8px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            text-decoration: none;
            display: inline-block;
        }}
        .btn-primary {{
            background: var(--accent);
            color: #000;
            border: none;
        }}
        .btn-danger {{
            background: var(--red);
            color: #fff;
            border: none;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        th, td {{
            text-align: left;
            padding: 10px;
            border-bottom: 1px solid var(--border);
        }}
        .hash {{
            font-family: monospace;
            color: #8b949e;
            font-size: 0.85rem;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1 style="margin:0; color:var(--accent);">SautiPay ⚡ Control Room</h1>
            <p style="margin:5px 0 0 0; color:#8b949e;">Verify the payment, not the screenshot.</p>
        </div>
        <div>
            <span class="badge badge-green">CORE: ACTIVE</span>
            <span class="badge badge-orange">{rate_badge}</span>
            <span class="badge badge-blue">TESTNET / SANDBOX</span>
        </div>
    </div>
    {content}
</body>
</html>
"""

@dashboard_router.get("/", response_class=HTMLResponse)
def index_page():
    ledger = Ledger()
    try:
        rate, source, is_stale = rate_oracle.get_rate()
        rate_badge = f"{rate} sats/NGN ({source.upper()})"
    except Exception:
        rate = 1.847
        source = "fallback"
        rate_badge = "OFFLINE / DEFAULT RATE"

    # Fetch merchants
    with db_session() as conn:
        merchants = [dict(r) for r in conn.execute("SELECT * FROM merchants").fetchall()]
        recent_invoices = [dict(r) for r in conn.execute("SELECT * FROM invoices ORDER BY created_at DESC LIMIT 5").fetchall()]

    # Chain inspection for primary demo merchant
    first_merchant = merchants[0] if merchants else None
    receipts = []
    is_valid_chain = True
    if first_merchant:
        receipts = ledger.get_merchant_receipts(first_merchant["id"])
        is_valid_chain = ledger.verify_chain(first_merchant["id"])

    chain_blocks_html = ""
    if not receipts:
        chain_blocks_html = "<p style='color:#8b949e;'>No receipts minted yet. Settle an invoice to see hash blocks appear.</p>"
    else:
        for r in receipts:
            border_cls = "" if is_valid_chain else "block-tampered"
            chain_blocks_html += f"""
            <div class="block {border_cls}">
                <div style="font-weight:bold; font-size:1.1rem; color:var(--accent); margin-bottom:8px;">
                    Block #{r['seq']}
                </div>
                <div style="font-size:0.9rem; margin-bottom:4px;">
                    Amount: <strong>₦{r['amount_ngn']}</strong>
                </div>
                <div style="font-size:0.85rem; color:#8b949e; margin-bottom:4px;">
                    Rate: {r['sats_per_ngn']} sats/NGN
                </div>
                <div style="font-size:0.85rem; margin-bottom:8px;">
                    Mode: <span class="badge badge-orange">{r['value_mode']}</span>
                </div>
                <div style="font-size:0.75rem; color:#8b949e;">
                    Prev: <span class="hash">{r['prev_receipt_hash'][:12]}…</span><br>
                    Hash: <span class="hash" style="color:var(--green);">{r['receipt_hash'][:12]}…</span>
                </div>
            </div>
            """

    invoices_rows = ""
    for inv in recent_invoices:
        status_color = "var(--green)" if inv["status"] == "SETTLED" else "var(--accent)"
        invoices_rows += f"""
        <tr>
            <td>₦{inv['amount_ngn']}</td>
            <td>{inv['amount_msat'] // 1000} sats</td>
            <td><span class="hash">{inv['payment_hash'][:12]}…</span></td>
            <td style="color:{status_color}; font-weight:bold;">{inv['status']}</td>
            <td>{inv['created_at']}</td>
        </tr>
        """

    content = f"""
    <div class="grid">
        <div class="card">
            <h3>⚡ Node & Rate Oracle</h3>
            <p><strong>LND Node:</strong> <span class="hash">{settings.LND_REST_URL}</span></p>
            <p><strong>Rate:</strong> {rate} sats/NGN ({source})</p>
            <p><strong>Status:</strong> <span style="color:var(--green);">Ready for Invoices</span></p>
        </div>
        <div class="card">
            <h3>👤 Active Demo Merchant</h3>
            <p><strong>Phone:</strong> {first_merchant['phone'] if first_merchant else 'None'}</p>
            <p><strong>Mode:</strong> <span class="badge badge-orange">{first_merchant['settlement_mode'] if first_merchant else 'N/A'}</span></p>
            <p><strong>Daily Limit:</strong> ₦{first_merchant['daily_limit_ngn'] if first_merchant else '50,000'}</p>
        </div>
        <div class="card">
            <h3>🛡️ Security State</h3>
            <p><strong>Chain Verification:</strong> {f'<span class="badge badge-green">CRYPTOGRAPHICALLY SOUND</span>' if is_valid_chain else f'<span class="badge badge-red">TAMPER DETECTED</span>'}</p>
            <p><strong>Decline By Default:</strong> ACTIVE</p>
            <p><strong>Receipts Count:</strong> {len(receipts)}</p>
        </div>
    </div>

    <div class="card" style="margin-bottom:25px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <h3>⛓️ Live Hash-Chained Receipt Ledger</h3>
            <a href="/receipts/{first_merchant['id'] if first_merchant else ''}" class="btn">Inspect Full Chain</a>
        </div>
        <div class="chain-container">
            {chain_blocks_html}
        </div>
    </div>

    <div class="card">
        <h3>📄 Recent Invoices</h3>
        <table>
            <thead>
                <tr>
                    <th>NGN</th>
                    <th>Sats</th>
                    <th>Payment Hash</th>
                    <th>Status</th>
                    <th>Created</th>
                </tr>
            </thead>
            <tbody>
                {invoices_rows if invoices_rows else '<tr><td colspan="5" style="color:#8b949e;">No invoices created yet.</td></tr>'}
            </tbody>
        </table>
    </div>
    """
    return HTMLResponse(HTML_BASE.format(rate_badge=rate_badge, content=content))

@dashboard_router.get("/receipts", response_class=HTMLResponse)
@dashboard_router.get("/receipts/", response_class=HTMLResponse)
@dashboard_router.get("/receipts/{merchant_id}", response_class=HTMLResponse)
def receipts_chain_page(merchant_id: Optional[str] = None):
    ledger = Ledger()
    
    # If no merchant_id supplied in path, pick first merchant from DB
    if not merchant_id:
        with db_session() as conn:
            m = conn.execute("SELECT id FROM merchants LIMIT 1").fetchone()
            if m:
                merchant_id = m["id"]
            else:
                merchant_id = "default"

    receipts = ledger.get_merchant_receipts(merchant_id)
    is_valid = ledger.verify_chain(merchant_id)

    rows = ""
    for r in receipts:
        rows += f"""
        <tr>
            <td><strong>#{r['seq']}</strong></td>
            <td>₦{r['amount_ngn']}</td>
            <td>{r['sats_per_ngn']}</td>
            <td>{r['value_mode']}</td>
            <td><span class="hash">{r['prev_receipt_hash']}</span></td>
            <td><span class="hash" style="color:var(--green);">{r['receipt_hash']}</span></td>
            <td>{r['created_at']}</td>
        </tr>
        """

    status_badge = '<span class="badge badge-green">CHAIN VALID & UNTAMPERED</span>' if is_valid else '<span class="badge badge-red">CHAIN INTEGRITY BROKEN (TAMPER DETECTED)</span>'

    content = f"""
    <div style="margin-bottom:15px;">
        <a href="/" class="btn">← Back to Control Room</a>
    </div>
    <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <h2>Merchant Receipt Ledger (Merchant: <span class="hash">{merchant_id}</span>)</h2>
            {status_badge}
        </div>
        <table>
            <thead>
                <tr>
                    <th>Seq</th>
                    <th>Amount</th>
                    <th>Rate</th>
                    <th>Mode</th>
                    <th>Previous Hash</th>
                    <th>Receipt Hash</th>
                    <th>Timestamp</th>
                </tr>
            </thead>
            <tbody>
                {rows if rows else '<tr><td colspan="7">No receipts.</td></tr>'}
            </tbody>
        </table>
    </div>
    """
    return HTMLResponse(HTML_BASE.format(rate_badge="LEDGER AUDIT", content=content))

@dashboard_router.get("/merchants", response_class=HTMLResponse)
def merchants_page():
    with db_session() as conn:
        merchants = [dict(r) for r in conn.execute("SELECT * FROM merchants").fetchall()]

    rows = ""
    for m in merchants:
        rows += f"""
        <tr>
            <td><span class="hash">{m['id'][:8]}…</span></td>
            <td><strong>{m['phone']}</strong></td>
            <td><span class="badge badge-orange">{m['settlement_mode']}</span></td>
            <td>₦{m['daily_limit_ngn']}</td>
            <td>{m['created_at']}</td>
        </tr>
        """

    content = f"""
    <div style="margin-bottom:15px;">
        <a href="/" class="btn">← Back to Control Room</a>
    </div>
    <div class="card">
        <h2>Registered Merchants</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Phone</th>
                    <th>Mode</th>
                    <th>Daily Limit</th>
                    <th>Registered At</th>
                </tr>
            </thead>
            <tbody>
                {rows if rows else '<tr><td colspan="5">No merchants seeded.</td></tr>'}
            </tbody>
        </table>
    </div>
    """
    return HTMLResponse(HTML_BASE.format(rate_badge="MERCHANTS", content=content))

@dashboard_router.get("/m", response_class=HTMLResponse)
def mobile_fallback_page():
    """
    Demo-day hardware fallback view (§8):
    Shown on a spare phone on the desk if SMS gateway hiccups.
    Big bold SETTLED notification that updates in real-time.
    """
    with db_session() as conn:
        recent_payment = conn.execute(
            """
            SELECT p.*, i.amount_ngn, r.receipt_hash, r.value_mode
            FROM payments p
            JOIN invoices i ON p.invoice_id = i.id
            JOIN receipts r ON r.invoice_id = i.id
            ORDER BY p.settled_at DESC LIMIT 1
            """
        ).fetchone()

    if recent_payment:
        pay = dict(recent_payment)
        status_html = f"""
        <div style="background:#2ea043; border-radius:16px; padding:30px; text-align:center; color:#fff; box-shadow:0 8px 24px rgba(0,0,0,0.6);">
            <div style="font-size:1.2rem; text-transform:uppercase; letter-spacing:1px; margin-bottom:10px;">Payment Verified & Settled ⚡</div>
            <div style="font-size:3.5rem; font-weight:800; margin:15px 0;">₦{pay['amount_ngn']}</div>
            <div style="font-size:1.1rem; opacity:0.9;">Mode: <strong>{pay['value_mode']}</strong></div>
            <div style="margin-top:20px; font-family:monospace; font-size:0.85rem; opacity:0.8;">
                Ref: {pay['receipt_hash'][:16]}…<br>
                Settled: {pay['settled_at'][:19]} UTC
            </div>
        </div>
        """
    else:
        status_html = """
        <div style="background:#21262d; border-radius:16px; padding:40px; text-align:center; color:#8b949e;">
            <div style="font-size:2rem; margin-bottom:10px;">⏳</div>
            <div style="font-size:1.2rem;">Awaiting Lightning Settlement…</div>
            <p style="margin-top:10px;">Generate invoice via USSD *384# to receive funds.</p>
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="3">
        <title>SautiPay Merchant View</title>
        <style>
            body {{
                background: #0d1117;
                color: #c9d1d9;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                margin: 0;
                padding: 20px;
                display: flex;
                flex-direction: column;
                justify-content: center;
                min-height: 90vh;
            }}
        </style>
    </head>
    <body>
        <div style="text-align:center; margin-bottom:30px;">
            <h1 style="color:#f7931a; margin:0;">SautiPay</h1>
            <p style="margin:5px 0 0 0; color:#8b949e;">Live Merchant Terminal</p>
        </div>
        {status_html}
    </body>
    </html>
    """
    return HTMLResponse(html)
