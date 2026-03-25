#!/usr/bin/env python3
"""
NSE Daily Briefing Emailer
==========================
Fetches live NSE / commodity / currency data, generates a rich HTML email,
and sends it to jainsandeep729@gmail.com via Gmail SMTP.

SETUP (one-time):
  1. Enable 2-Step Verification on your Google account:
     https://myaccount.google.com/security
  2. Create a Gmail App Password:
     https://myaccount.google.com/apppasswords
     → Select app: "Mail"  |  Select device: "Other (custom name)" → "NSE Briefing"
     → Copy the 16-char password shown
  3. Set environment variables (add to ~/.bashrc or ~/.zshrc):
       export GMAIL_USER="jainsandeep729@gmail.com"
       export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"   # paste 16-char key
     OR: edit the FALLBACK values directly in the CONFIG section below.

RUNNING MANUALLY:
  python3 nse_briefing_emailer.py

SCHEDULING (run daily at 4 PM):
  crontab -e
  Add: 0 16 * * 1-5 /usr/bin/python3 /path/to/nse_briefing_emailer.py
  (1-5 = Monday–Friday only, skip weekends)
"""

import smtplib
import ssl
import os
import json
import urllib.request
import urllib.error
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────
# CONFIG — edit these if not using env vars
# ─────────────────────────────────────────────
GMAIL_USER         = os.environ.get("GMAIL_USER",         "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL    = "jainsandeep729@gmail.com"

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

IST = timezone(timedelta(hours=5, minutes=30))

def ist_now():
    return datetime.now(IST)

def fmt_date():
    return ist_now().strftime("%A, %d %B %Y")

def fmt_time():
    return ist_now().strftime("%I:%M %p IST")

def fetch_yahoo(symbol):
    """Fetch a single Yahoo Finance quote. Returns dict or None."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1d&range=1d"
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        meta = data["chart"]["result"][0]["meta"]
        price   = meta.get("regularMarketPrice", 0)
        prev    = meta.get("chartPreviousClose", price)
        change  = price - prev
        pct     = (change / prev * 100) if prev else 0
        return {"price": price, "change": change, "pct": pct}
    except Exception as e:
        print(f"  [warn] Could not fetch {symbol}: {e}")
        return None

def arrow(val):
    return "▲" if val >= 0 else "▼"

def color(val):
    return "#48bb78" if val >= 0 else "#fc8181"

def sign(val):
    return "+" if val >= 0 else ""

def fmt_num(n, decimals=2):
    """Format number with commas."""
    return f"{n:,.{decimals}f}"

# ─────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────

SYMBOLS = {
    "nifty50":   "^NSEI",
    "sensex":    "^BSESN",
    "banknifty": "^NSEBANK",
    "vix":       "^INDIAVIX",
    "niftyit":   "^CNXIT",
    "niftypharma":"^CNXPHARMA",
    "niftyauto": "^CNXAUTO",
    "niftymetal": "^CNXMETAL",
    "niftyfmcg": "^CNXFMCG",
    "midcap":    "^NSEMDCP50",
    "gold_usd":  "GC=F",          # COMEX Gold futures
    "usdinr":    "INR=X",
    "eurinr":    "EURINR=X",
}

def fetch_all():
    print("Fetching market data...")
    results = {}
    for key, sym in SYMBOLS.items():
        print(f"  {sym}...", end=" ", flush=True)
        d = fetch_yahoo(sym)
        results[key] = d
        print("ok" if d else "FAILED")
    return results

def fetch_nifty_candles(symbol="^NSEI", days=5):
    """Fetch last N daily OHLC candles for a symbol. Returns list of dicts or []."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1d&range=10d"   # fetch 10d buffer to guarantee 5 trading days
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        q = result["indicators"]["quote"][0]
        opens  = q.get("open",  [])
        highs  = q.get("high",  [])
        lows   = q.get("low",   [])
        closes = q.get("close", [])
        candles = []
        for i in range(len(timestamps)):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            if None in (o, h, l, c):
                continue
            dt = datetime.fromtimestamp(timestamps[i], tz=IST)
            candles.append({
                "date":  dt.strftime("%d %b"),
                "open":  o,
                "high":  h,
                "low":   l,
                "close": c,
            })
        # Return last `days` completed candles
        return candles[-days:] if len(candles) >= days else candles
    except Exception as e:
        print(f"  [warn] Could not fetch candle data for {symbol}: {e}")
        return []

# ─────────────────────────────────────────────
# HTML GENERATION
# ─────────────────────────────────────────────

STYLE = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Inter', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; background: #f0f4f8; color: #2d3748; }
.wrap { max-width: 680px; margin: 0 auto; background: #ffffff; border-radius: 14px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }
.hdr { background: linear-gradient(135deg, #ffffff, #eef2ff); padding: 24px 28px; border-bottom: 2px solid #e2e8f0; }
.hdr h1 { font-size: 1.4rem; font-weight: 700; color: #1a202c; }
.hdr .sub { font-size: 0.82rem; color: #718096; margin-top: 4px; }
.hdr .meta { font-size: 0.8rem; color: #4a6fa5; margin-top: 8px; }
.body { padding: 24px 28px; background: #ffffff; }
.sec { font-size: 0.65rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; color: #a0aec0; margin: 24px 0 12px; border-left: 3px solid #667eea; padding-left: 8px; }
.row3 { display: grid; grid-template-columns: repeat(3,1fr); gap: 12px; }
.row2 { display: grid; grid-template-columns: repeat(2,1fr); gap: 12px; }
.row4 { display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; }
.card { background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; }
.lbl { font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #718096; }
.val { font-size: 1.5rem; font-weight: 700; color: #1a202c; margin: 5px 0 3px; letter-spacing: -0.5px; }
.chg { font-size: 0.82rem; font-weight: 600; }
.bar-wrap { margin-top: 10px; height: 3px; background: #e2e8f0; border-radius: 2px; }
.bar { height: 100%; border-radius: 2px; }
.sc-lbl { font-size: 0.65rem; font-weight: 700; text-transform: uppercase; color: #718096; letter-spacing: 0.5px; }
.sc-val { font-size: 0.85rem; font-weight: 700; color: #1a202c; margin: 4px 0 2px; }
.sc-chg { font-size: 0.75rem; font-weight: 600; }
.hl { background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px; }
.hl-item { display: flex; gap: 10px; padding: 9px 0; border-bottom: 1px solid #edf2f7; }
.hl-item:last-child { border-bottom: none; }
.hl-ico { font-size: 1rem; min-width: 20px; }
.hl-txt { font-size: 0.83rem; color: #4a5568; line-height: 1.5; }
.hl-txt b { color: #2d3748; }
.ftr { padding: 16px 28px; background: #f7fafc; border-top: 1px solid #e2e8f0; font-size: 0.72rem; color: #a0aec0; text-align: center; }
.ftr a { color: #667eea; text-decoration: none; }
.vix-row { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.vix-pill { background: #edf2f7; border-radius: 20px; padding: 4px 14px; font-size: 0.8rem; color: #4a5568; }
.vix-pill b { color: #d69e2e; }
</style>
"""

def idx_card(label, data, accent_up="#48bb78", accent_dn="#fc8181"):
    if not data:
        return f'<div class="card"><div class="lbl">{label}</div><div class="val" style="color:#4a5568">N/A</div></div>'
    p, c, pct = data["price"], data["change"], data["pct"]
    col = color(c)
    bar_w = min(abs(pct) * 15, 90)
    bar_col = "#48bb78" if c >= 0 else "#fc8181"
    border = "rgba(72,187,120,0.35)" if c >= 0 else "rgba(252,129,129,0.35)"
    bg = "rgba(72,187,120,0.06)" if c >= 0 else "rgba(252,129,129,0.06)"
    return f"""
<div class="card" style="border-color:{border};background:{bg}">
  <div class="lbl">{label}</div>
  <div class="val">{fmt_num(p,2)}</div>
  <div class="chg" style="color:{col}">{arrow(c)} {sign(c)}{fmt_num(c,2)} ({sign(pct)}{fmt_num(pct,2)}%)</div>
  <div class="bar-wrap"><div class="bar" style="width:{bar_w}%;background:{bar_col}"></div></div>
</div>"""

def sec_card(label, data):
    if not data:
        return f'<div class="card" style="text-align:center"><div class="sc-lbl">{label}</div><div class="sc-val">N/A</div></div>'
    p, c, pct = data["price"], data["change"], data["pct"]
    col = color(c)
    return f"""
<div class="card" style="text-align:center">
  <div class="sc-lbl">{label}</div>
  <div class="sc-val">{fmt_num(p,2)}</div>
  <div class="sc-chg" style="color:{col}">{arrow(c)} {sign(pct)}{fmt_num(pct,2)}%</div>
</div>"""

def asset_card(icon, label, data, price_prefix="", sub=""):
    if not data:
        return f'<div class="card"><div class="sc-lbl">{icon} {label}</div><div class="sc-val">N/A</div></div>'
    p, c, pct = data["price"], data["change"], data["pct"]
    col = color(c)
    border = "rgba(214,158,46,0.4)" if "Gold" in label else "rgba(99,179,237,0.4)"
    return f"""
<div class="card" style="border-color:{border}">
  <div style="font-size:1.2rem;margin-bottom:4px">{icon}</div>
  <div class="sc-lbl">{label}</div>
  <div class="sc-val">{price_prefix}{fmt_num(p,2)}</div>
  <div class="sc-chg" style="color:{col}">{arrow(c)} {sign(pct)}{fmt_num(pct,2)}%</div>
  {f'<div style="font-size:0.68rem;color:#a0aec0;margin-top:3px">{sub}</div>' if sub else ""}
</div>"""

def build_candle_chart_img(candles):
    """
    Render a candlestick chart as a PNG using Pillow.
    Returns a (png_bytes, html_tag) tuple where html_tag references the image
    via cid:nifty_chart — the correct, email-client-safe way to embed images.
    Falls back to (None, fallback_html) if data or Pillow is absent.
    """
    if not candles:
        return None, '<div style="text-align:center;color:#a0aec0;font-size:0.8rem;padding:16px">Chart data unavailable</div>'

    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
    except ImportError:
        return None, '<div style="text-align:center;color:#a0aec0;font-size:0.8rem;padding:16px">Chart requires Pillow (pip install pillow)</div>'

    # ── Layout (2× for retina, displayed at half size) ────────────
    SCALE   = 2
    W, H    = 580 * SCALE, 260 * SCALE   # taller to fit bigger labels
    PAD_L   = 80 * SCALE                 # wider for Y-axis price labels
    PAD_R   = 16 * SCALE
    PAD_T   = 24 * SCALE
    PAD_B   = 50 * SCALE                 # taller for X-axis date labels
    CW      = W - PAD_L - PAD_R    # chart area width
    CH      = H - PAD_T - PAD_B    # chart area height

    # ── Colours ───────────────────────────────────────────────────
    BG          = (247, 250, 252)
    GRID_COL    = (226, 232, 240)
    LABEL_COL   = (160, 174, 192)
    DATE_COL    = (113, 128, 150)
    BULL_FILL   = (72,  187, 120)
    BULL_STROKE = (47,  133,  90)
    BEAR_FILL   = (252, 129, 129)
    BEAR_STROKE = (197,  48,  48)

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # ── Font — search common paths on Windows / Linux / macOS ─────
    _FONT_CANDIDATES = [
        # Windows
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        # macOS
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    def _load_font(size):
        for path in _FONT_CANDIDATES:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return ImageFont.load_default()

    font_sm  = _load_font(18 * SCALE)
    font_med = _load_font(18 * SCALE)

    n     = len(candles)
    col_w = CW / n

    # ── Price range ───────────────────────────────────────────────
    y_min = min(c["low"]  for c in candles)
    y_max = max(c["high"] for c in candles)
    pad   = (y_max - y_min) * 0.10 or 10
    y_min -= pad
    y_max += pad
    y_span = y_max - y_min

    def to_y(price):
        return int(PAD_T + CH * (1 - (price - y_min) / y_span))

    def to_x(i, frac=0.5):
        return int(PAD_L + col_w * i + col_w * frac)

    # ── Rounded rectangle helper ──────────────────────────────────
    def rounded_rect(draw, xy, radius, fill, outline):
        x0, y0, x1, y1 = xy
        r = min(radius, (x1 - x0) // 2, max((y1 - y0) // 2, 1))
        draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill, outline=outline)

    # ── Grid lines & Y-axis labels ────────────────────────────────
    n_grid = 4
    for gi in range(n_grid + 1):
        gp  = y_min + y_span * gi / n_grid
        gy  = to_y(gp)
        draw.line([(PAD_L, gy), (W - PAD_R, gy)], fill=GRID_COL, width=SCALE)
        lbl = f"{gp:,.0f}"
        bbox = draw.textbbox((0, 0), lbl, font=font_sm)
        tw   = bbox[2] - bbox[0]
        draw.text((PAD_L - tw - 4 * SCALE, gy - (bbox[3] - bbox[1]) // 2),
                  lbl, font=font_sm, fill=LABEL_COL)

    # ── Candles ───────────────────────────────────────────────────
    body_frac = 0.55
    for i, c in enumerate(candles):
        bull   = c["close"] >= c["open"]
        fill   = BULL_FILL   if bull else BEAR_FILL
        stroke = BULL_STROKE if bull else BEAR_STROKE

        cx     = to_x(i, 0.5)
        bw     = int(col_w * body_frac)
        bx0    = cx - bw // 2
        bx1    = bx0 + bw

        yo     = to_y(c["open"])
        yc     = to_y(c["close"])
        yh     = to_y(c["high"])
        yl     = to_y(c["low"])

        by0    = min(yo, yc)
        by1    = max(yo, yc)
        if by1 - by0 < SCALE:
            by1 = by0 + SCALE          # doji: at least 1 display pixel

        # Wick
        draw.line([(cx, yh), (cx, yl)], fill=stroke, width=max(SCALE, 2))
        # Body
        rounded_rect(draw, (bx0, by0, bx1, by1), radius=2 * SCALE,
                     fill=fill, outline=stroke)

        # Date label centred below candle
        lbl  = c["date"]
        bbox = draw.textbbox((0, 0), lbl, font=font_med)
        tw   = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, H - PAD_B + 6 * SCALE),
                  lbl, font=font_med, fill=DATE_COL)

    # ── Save PNG to bytes ─────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()

    display_w = W // SCALE   # 580px — render at normal size in email
    html_tag = (
        f'<img src="cid:nifty_chart" '
        f'width="{display_w}" '
        f'style="width:100%;max-width:{display_w}px;height:auto;display:block;'
        f'border-radius:8px;margin:0 auto" '
        f'alt="NIFTY 50 — Last 5 Days Candlestick Chart"/>'
    )
    return png_bytes, html_tag


def build_html(data, candles=None):
    today     = fmt_date()
    now_time  = fmt_time()

    n50   = data.get("nifty50")
    bse   = data.get("sensex")
    bn    = data.get("banknifty")
    vix   = data.get("vix")
    nit   = data.get("niftyit")
    nph   = data.get("niftypharma")
    nau   = data.get("niftyauto")
    nmt   = data.get("niftymetal")
    nfm   = data.get("niftyfmcg")
    gold  = data.get("gold_usd")
    usd   = data.get("usdinr")
    eur   = data.get("eurinr")

    vix_txt = ""
    if vix:
        vix_txt = f"""
<div class="vix-row">
  <div class="vix-pill">India VIX &nbsp;<b>{fmt_num(vix['price'],2)}</b></div>
  <div style="font-size:0.78rem;color:#718096">{arrow(vix['change'])} {sign(vix['pct'])}{fmt_num(vix['pct'],2)}% from previous close</div>
</div>"""

    # Build candle chart — returns (png_bytes, html_tag) via CID attachment
    candle_section = ""
    chart_img_bytes = None
    if candles is not None:
        chart_img_bytes, chart_img_html = build_candle_chart_img(candles)
        # Legend row
        legend = (
            '<div style="margin-bottom:14px;">'
            '<span style="display:inline-block;vertical-align:middle;width:14px;height:14px;background:#48bb78;border-radius:3px;margin-right:7px;"></span>'
            '<span style="display:inline-block;vertical-align:middle;font-size:0.85rem;color:#4a5568;margin-right:28px;">Bullish close</span>'
            '<span style="display:inline-block;vertical-align:middle;width:14px;height:14px;background:#fc8181;border-radius:3px;margin-right:7px;"></span>'
            '<span style="display:inline-block;vertical-align:middle;font-size:0.85rem;color:#4a5568;">Bearish close</span>'
            '</div>'
        )
        candle_section = f"""
    <div class="sec">NIFTY 50 — Last 5 Days Candlestick</div>
    <div class="card" style="padding:16px">
      {legend}
      {chart_img_html}
    </div>"""

    inr_label = "USD / INR"
    inr_sub   = "Higher = weaker Rupee"
    eur_label = "EUR / INR"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>{STYLE}</head>
<body>
<div class="wrap">

  <div class="hdr">
    <h1>📊 NSE Daily Market Briefing</h1>
    <div class="sub">National Stock Exchange of India — End of Day Summary</div>
    <div class="meta">{today} &nbsp;·&nbsp; Generated {now_time} &nbsp;·&nbsp; <span style="color:#e53e3e">Market Closed</span></div>
  </div>

  <div class="body">

    <div class="sec">Major Indices</div>
    <div class="row3">
      {idx_card("NIFTY 50", n50)}
      {idx_card("BSE SENSEX", bse)}
      {idx_card("BANK NIFTY", bn)}
    </div>
    {vix_txt}
    {candle_section}

    <div class="sec">Commodities &amp; Currency</div>
    <div class="row4">
      {asset_card("🥇", "Gold (USD/oz)", gold, "$", "COMEX Futures")}
      {asset_card("💱", inr_label, usd, "₹", inr_sub)}
      {asset_card("💶", eur_label, eur, "₹", "")}
      {asset_card("📈", "Nifty Metal", nmt, "", "")}
    </div>

    <div class="sec">Sector Performance</div>
    <div class="row4">
      {sec_card("Nifty IT", nit)}
      {sec_card("Nifty Pharma", nph)}
      {sec_card("Nifty Auto", nau)}
      {sec_card("Nifty FMCG", nfm)}
    </div>

    <div class="sec">Key Highlights</div>
    <div class="hl">
      <div class="hl-item"><div class="hl-ico">📊</div><div class="hl-txt">
        <b>Nifty 50</b> {f"closed at {fmt_num(n50['price'],2)} — {arrow(n50['change'])} {sign(n50['pct'])}{fmt_num(n50['pct'],2)}% from previous close." if n50 else "data unavailable."}
        &nbsp;<b>Sensex</b> {f"at {fmt_num(bse['price'],2)} ({sign(bse['pct'])}{fmt_num(bse['pct'],2)}%)." if bse else "data unavailable."}
      </div></div>
      <div class="hl-item"><div class="hl-ico">🏦</div><div class="hl-txt">
        <b>Bank Nifty</b> {f"closed at {fmt_num(bn['price'],2)} — {arrow(bn['change'])} {sign(bn['pct'])}{fmt_num(bn['pct'],2)}%." if bn else "data unavailable."}
        Banking sector performance was a key swing factor for the day.
      </div></div>
      <div class="hl-item"><div class="hl-ico">🥇</div><div class="hl-txt">
        <b>Gold (USD)</b> {f"at ${fmt_num(gold['price'],2)}/oz — {arrow(gold['change'])} {sign(gold['pct'])}{fmt_num(gold['pct'],2)}% from previous session." if gold else "data unavailable."}
        Domestic MCX Gold prices may differ based on INR moves.
      </div></div>
      <div class="hl-item"><div class="hl-ico">💱</div><div class="hl-txt">
        <b>USD/INR</b> {f"at ₹{fmt_num(usd['price'],2)} — {'Rupee strengthened' if usd['change'] < 0 else 'Rupee weakened'} {abs(usd['pct']):.2f}% vs USD." if usd else "data unavailable."}
        RBI monitors the Rupee closely around these levels.
      </div></div>
      <div class="hl-item"><div class="hl-ico">🔬</div><div class="hl-txt">
        <b>India VIX</b> {f"at {fmt_num(vix['price'],2)} ({sign(vix['pct'])}{fmt_num(vix['pct'],2)}%) — {'Fear levels subdued; bullish signal.' if vix['price'] < 15 else 'Elevated VIX; caution advised.' if vix['price'] > 20 else 'Moderate volatility — watch closely.'}" if vix else "data unavailable."}
      </div></div>
    </div>

  </div>

  <div class="ftr">
    Auto-generated by NSE Briefing Bot · {today} · Data via Yahoo Finance &amp; NSE India<br/>
    <a href="https://www.nseindia.com">nseindia.com</a> &nbsp;·&nbsp; <a href="https://finance.yahoo.com">finance.yahoo.com</a>
  </div>

</div>
</body>
</html>"""
    return html, chart_img_bytes

# ─────────────────────────────────────────────
# EMAIL SENDER
# ─────────────────────────────────────────────

def send_email(html_body, subject, chart_img_bytes=None):
    if GMAIL_APP_PASSWORD == "YOUR_APP_PASSWORD_HERE":
        print("\n⚠️  GMAIL_APP_PASSWORD not configured.")
        print("   Set the env var GMAIL_APP_PASSWORD or edit this script.")
        print("\n   Saving HTML to nse_briefing_preview.html for preview...")
        with open("nse_briefing_preview.html", "w") as f:
            f.write(html_body)
        print("   Saved! Open nse_briefing_preview.html in your browser.\n")
        return False

    # Build the correct MIME structure for HTML email with an embedded image:
    #   multipart/mixed
    #     multipart/alternative
    #       text/plain  (fallback)
    #       multipart/related
    #         text/html
    #         image/png  (Content-ID: nifty_chart)  ← chart attachment
    plain = "Your NSE Daily Briefing is attached. Please view in an HTML-capable email client."

    if chart_img_bytes:
        related = MIMEMultipart("related")
        related.attach(MIMEText(html_body, "html"))
        img_part = MIMEImage(chart_img_bytes, _subtype="png")
        img_part.add_header("Content-ID", "<nifty_chart>")
        img_part.add_header("Content-Disposition", "inline", filename="nifty_chart.png")
        related.attach(img_part)

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(plain, "plain"))
        alt.attach(related)

        msg = MIMEMultipart("mixed")
        msg.attach(alt)
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
        print(f"✅ Email sent to {RECIPIENT_EMAIL}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("❌ Authentication failed. Check your App Password.")
        return False
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  NSE Daily Briefing Emailer")
    print(f"  {fmt_date()} · {fmt_time()}")
    print("=" * 50)

    market_data = fetch_all()
    print("Fetching NIFTY 50 candle data (last 5 days)...")
    nifty_candles = fetch_nifty_candles("^NSEI", days=5)
    print(f"  Got {len(nifty_candles)} candles.")
    html_body, chart_img_bytes = build_html(market_data, candles=nifty_candles)
    subject     = f"📊 NSE Briefing · {fmt_date()}"

    print(f"\nSending to: {RECIPIENT_EMAIL}")
    send_email(html_body, subject, chart_img_bytes=chart_img_bytes)
