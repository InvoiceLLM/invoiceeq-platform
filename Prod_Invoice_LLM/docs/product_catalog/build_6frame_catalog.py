"""
Generator for InvoiceEQ 6-Frame Product Catalogue
Theme: Luminous Cyber-Enterprise (Bright, Clean, Decent & Animated)
Features:
- Animated Aurora shifting ambient mesh gradient in background
- Shimmering light beam borders across keynote cards
- Breathing pulse badges & glowing hover elevators
- High-contrast crisp typography (DM Serif Display + Inter + JetBrains Mono)
- Full viewport height scroll-snap with dynamic side-dot navigation & counter
- Embedded high-res screenshots (Base64) with interactive Tab Viewer and Lightbox zoom
"""
import os
import io
import base64
from PIL import Image

DIR = r"d:\testllm\Invoice-LLM-SOLO-Dev\Prod_Invoice_LLM\docs\product_catalog"
OUT_FILE = os.path.join(DIR, "catalog_6frame.html")
WEBSITE_PUBLIC_FILE = r"d:\testllm\Invoice-LLM-SOLO-Dev\Prod_Invoice_LLM\apps\invoice-website\public\catalog.html"

def img_to_b64(fname, max_w=1280, quality=80):
    p = os.path.join(DIR, fname)
    if not os.path.exists(p):
        print(f"Warning: {fname} does not exist, creating placeholder")
        return ""
    im = Image.open(p).convert("RGB")
    if im.width > max_w:
        h = int(im.height * (max_w / im.width))
        im = im.resize((max_w, h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

print("Encoding screenshots into base64...")
B64_DASH_TOP    = img_to_b64("live_dashboard_top.png")
B64_DASH_MID    = img_to_b64("live_dashboard_mid.png")
B64_INGEST      = img_to_b64("live_ingest_top.png")
B64_AUDIT       = img_to_b64("live_audit_top.png")
B64_REVIEW      = img_to_b64("live_auditor_review.png")
B64_HISTORY     = img_to_b64("live_history_top.png")
B64_TRAINER     = img_to_b64("live_trainer_top.png")
B64_CHAT        = img_to_b64("live_chat_top.png")

print("Assembling animated bright theme HTML...")

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>InvoiceEQ — Autonomous Accounts Payable | Executive Product Catalogue</title>
  <meta name="description" content="Never trust an AI with your general ledger until it can prove its own math. Deterministic accounts payable platform rebuilding invoice totals from first principles."/>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet"/>
  <style>
    /* ════════════════════════════════════════════════════════════
       LUMINOUS CYBER-ENTERPRISE DESIGN SYSTEM
       ════════════════════════════════════════════════════════════ */
    :root {{
      --bg: #090E21;
      --panel: rgba(15, 23, 42, 0.75);
      --card: rgba(18, 30, 56, 0.72);
      --card-hover: rgba(26, 42, 78, 0.85);
      --card-inner: rgba(10, 18, 36, 0.85);
      --border: rgba(148, 163, 184, 0.16);
      --border-bright: rgba(56, 189, 248, 0.4);
      --border-active: #38BDF8;
      
      /* Vibrant Electric Brand Colors */
      --blue: #38BDF8;
      --blue-dark: #0284C7;
      --indigo: #6366F1;
      --teal: #14B8A6;
      --green: #10B981;
      --red: #F43F5E;
      --amber: #F59E0B;
      --purple: #C084FC;
      
      /* Crisp High-Contrast Luminous Text */
      --text-h: #FFFFFF;
      --text-b: #CBD5E1;
      --text-dim: #94A3B8;
      
      --serif: 'DM Serif Display', Georgia, serif;
      --sans: 'Inter', system-ui, -apple-system, sans-serif;
      --mono: 'JetBrains Mono', monospace;
      --r: 14px;
      --rs: 9px;
    }}

    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    
    html {{
      height: 100%;
      scroll-behavior: smooth;
      background: var(--bg);
    }}
    
    body {{
      height: 100%;
      background: var(--bg);
      color: var(--text-b);
      font-family: var(--sans);
      font-size: 14.5px;
      line-height: 1.62;
      -webkit-font-smoothing: antialiased;
      overflow-x: hidden;
      overflow-y: scroll;
      scroll-snap-type: y mandatory;
    }}

    /* ── ANIMATED LUMINOUS AURORA MESH BACKGROUND ── */
    .aurora-bg {{
      position: fixed;
      inset: 0;
      z-index: 0;
      pointer-events: none;
      background: 
        radial-gradient(circle at 15% 15%, rgba(56, 189, 248, 0.16) 0%, transparent 45%),
        radial-gradient(circle at 85% 25%, rgba(139, 92, 246, 0.18) 0%, transparent 48%),
        radial-gradient(circle at 50% 85%, rgba(20, 184, 166, 0.14) 0%, transparent 52%),
        radial-gradient(circle at 75% 75%, rgba(99, 102, 241, 0.13) 0%, transparent 40%);
      filter: blur(75px);
      animation: auroraShift 18s ease-in-out infinite alternate;
    }}
    @keyframes auroraShift {{
      0% {{ transform: scale(1) translate(0, 0); }}
      50% {{ transform: scale(1.06) translate(-25px, 20px); }}
      100% {{ transform: scale(1.02) translate(20px, -25px); }}
    }}

    /* Subtle High-Tech Blueprint Grid */
    body::before {{
      content: '';
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 1;
      background-image: 
        linear-gradient(rgba(56, 189, 248, 0.05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(56, 189, 248, 0.05) 1px, transparent 1px);
      background-size: 40px 40px;
    }}

    /* ── FULL-SCREEN SCROLL SNAP KEYNOTE SLIDES ── */
    .frame {{
      height: 100vh;
      min-height: 100vh;
      scroll-snap-align: start;
      scroll-snap-stop: always;
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: center;
      padding: 50px 80px;
      box-sizing: border-box;
      overflow: hidden;
      z-index: 2;
    }}

    .frame-content {{
      max-width: 1260px;
      width: 100%;
      margin: 0 auto;
      position: relative;
      z-index: 3;
    }}

    /* ── FIXED MODERN GLASS HEADER BAR ── */
    .top-bar {{
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      height: 58px;
      padding: 0 40px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      z-index: 500;
      background: rgba(9, 14, 33, 0.82);
      backdrop-filter: blur(20px);
      border-bottom: 1px solid rgba(56, 189, 248, 0.18);
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
      text-decoration: none;
    }}
    .brand-logo {{
      width: 30px;
      height: 30px;
      filter: drop-shadow(0 0 8px rgba(56, 189, 248, 0.5));
    }}
    .brand-name {{
      font-family: var(--serif);
      font-size: 21px;
      color: var(--text-h);
      letter-spacing: -0.01em;
    }}
    .brand-pill {{
      font-family: var(--mono);
      font-size: 10.5px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--blue);
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.35);
      padding: 3px 10px;
      border-radius: 20px;
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .pulse-dot {{
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--blue);
      box-shadow: 0 0 8px var(--blue);
      animation: pulseAnim 1.8s infinite;
    }}
    @keyframes pulseAnim {{
      0% {{ opacity: 0.4; transform: scale(0.9); }}
      50% {{ opacity: 1; transform: scale(1.3); }}
      100% {{ opacity: 0.4; transform: scale(0.9); }}
    }}

    .frame-counter {{
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 700;
      color: var(--text-h);
      letter-spacing: 0.12em;
      background: rgba(255, 255, 255, 0.07);
      border: 1px solid rgba(255, 255, 255, 0.18);
      padding: 5px 14px;
      border-radius: 20px;
      backdrop-filter: blur(10px);
      box-shadow: 0 0 16px rgba(56, 189, 248, 0.15);
    }}

    /* ── FIXED GLOWING SIDE DOT NAVIGATION ── */
    .side-nav {{
      position: fixed;
      right: 32px;
      top: 50%;
      transform: translateY(-50%);
      display: flex;
      flex-direction: column;
      gap: 16px;
      z-index: 500;
    }}
    .nav-dot {{
      width: 11px;
      height: 11px;
      border-radius: 50%;
      background: rgba(148, 163, 184, 0.3);
      border: 2px solid transparent;
      cursor: pointer;
      transition: all 0.28s cubic-bezier(0.16, 1, 0.3, 1);
      position: relative;
    }}
    .nav-dot:hover {{
      background: var(--blue);
      transform: scale(1.3);
      box-shadow: 0 0 14px var(--blue);
    }}
    .nav-dot.active {{
      background: #FFFFFF;
      border-color: var(--blue);
      box-shadow: 0 0 16px var(--blue), 0 0 30px rgba(56, 189, 248, 0.6);
      transform: scale(1.45);
    }}
    .nav-dot-tooltip {{
      position: absolute;
      right: 26px;
      top: 50%;
      transform: translateY(-50%) translateX(8px);
      background: rgba(15, 23, 42, 0.95);
      border: 1px solid rgba(56, 189, 248, 0.35);
      color: var(--text-h);
      font-size: 11.5px;
      font-weight: 600;
      white-space: nowrap;
      padding: 5px 12px;
      border-radius: 8px;
      opacity: 0;
      pointer-events: none;
      transition: all 0.2s ease;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
    }}
    .nav-dot:hover .nav-dot-tooltip {{
      opacity: 1;
      transform: translateY(-50%) translateX(0);
    }}

    /* ── SHIMMERING CARD BEAM EFFECT ── */
    .shimmer-card {{
      background: var(--card);
      backdrop-filter: blur(20px);
      border: 1px solid var(--border);
      border-radius: var(--r);
      position: relative;
      overflow: hidden;
      transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
    }}
    .shimmer-card:hover {{
      transform: translateY(-3px);
      border-color: var(--border-bright);
      box-shadow: 0 20px 45px -10px rgba(56, 189, 248, 0.22);
    }}
    .shimmer-card::before {{
      content: '';
      position: absolute;
      top: 0;
      left: -100%;
      width: 100%;
      height: 2px;
      background: linear-gradient(90deg, transparent, var(--blue), var(--teal), transparent);
      animation: shimmerSweep 5s infinite;
    }}
    @keyframes shimmerSweep {{
      0% {{ left: -100%; }}
      50% {{ left: 100%; }}
      100% {{ left: 100%; }}
    }}

    /* ── TYPOGRAPHY ── */
    .eyebrow {{
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.16em;
      color: var(--blue);
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .eyebrow::before {{
      content: '';
      width: 22px;
      height: 2px;
      background: linear-gradient(90deg, var(--blue), var(--teal));
      border-radius: 2px;
    }}
    .h1-headline {{
      font-family: var(--serif);
      font-size: clamp(34px, 4vw, 54px);
      line-height: 1.1;
      color: var(--text-h);
      letter-spacing: -0.015em;
      margin-bottom: 16px;
      text-shadow: 0 4px 30px rgba(56, 189, 248, 0.15);
    }}
    .h1-headline em {{
      font-style: italic;
      background: linear-gradient(135deg, #38BDF8 20%, #A78BFA 90%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .h2-headline {{
      font-family: var(--serif);
      font-size: clamp(26px, 2.7vw, 40px);
      line-height: 1.16;
      color: var(--text-h);
      letter-spacing: -0.015em;
      margin-bottom: 12px;
    }}
    .subtext {{
      font-size: 15.5px;
      line-height: 1.65;
      color: var(--text-b);
      max-width: 660px;
    }}

    /* ── BUTTONS ── */
    .btn-row {{
      display: flex;
      align-items: center;
      gap: 14px;
      margin-top: 24px;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 9px;
      font-family: var(--sans);
      font-size: 14px;
      font-weight: 600;
      padding: 12px 24px;
      border-radius: var(--rs);
      cursor: pointer;
      text-decoration: none;
      transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
      border: none;
    }}
    .btn-primary {{
      background: linear-gradient(135deg, #0284C7, #2563EB);
      color: #FFFFFF;
      box-shadow: 0 4px 20px rgba(56, 189, 248, 0.35), 0 0 0 1px rgba(255, 255, 255, 0.15) inset;
    }}
    .btn-primary:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 30px rgba(56, 189, 248, 0.55), 0 0 0 1px rgba(255, 255, 255, 0.3) inset;
    }}
    .btn-ghost {{
      background: rgba(255, 255, 255, 0.06);
      color: var(--text-h);
      border: 1px solid rgba(255, 255, 255, 0.18);
      backdrop-filter: blur(10px);
    }}
    .btn-ghost:hover {{
      border-color: var(--blue);
      background: rgba(56, 189, 248, 0.12);
      color: var(--blue);
      transform: translateY(-2px);
    }}

    /* ── STATS TILES (Frame 1) ── */
    .hero-stats-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
      margin-top: 32px;
    }}
    .h-stat {{
      background: var(--card);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border);
      border-radius: var(--rs);
      padding: 18px 20px;
      position: relative;
      transition: all 0.2s ease;
    }}
    .h-stat:hover {{
      border-color: var(--border-bright);
      transform: translateY(-2px);
    }}
    .h-stat-num {{
      font-family: var(--serif);
      font-size: 32px;
      line-height: 1;
      color: var(--text-h);
      margin-bottom: 6px;
      font-weight: 400;
    }}
    .h-stat-lbl {{
      font-size: 12.5px;
      font-weight: 700;
      color: var(--text-h);
      margin-bottom: 4px;
    }}
    .h-stat-caveat {{
      font-size: 11px;
      color: var(--text-dim);
      font-style: italic;
      line-height: 1.4;
    }}

    /* ── BROWSER CHROME MOCKUP FRAME ── */
    .b-frame {{
      background: var(--card);
      border: 1px solid rgba(56, 189, 248, 0.3);
      border-radius: var(--r);
      box-shadow: 0 24px 70px rgba(0,0,0,0.6), 0 0 50px rgba(56,189,248,0.18);
      overflow: hidden;
      position: relative;
      cursor: zoom-in;
      transition: transform 0.3s ease, box-shadow 0.3s ease;
    }}
    .b-frame:hover {{
      transform: translateY(-4px) scale(1.01);
      box-shadow: 0 30px 90px rgba(0,0,0,0.7), 0 0 60px rgba(56,189,248,0.3);
    }}
    .b-chrome {{
      height: 34px;
      background: rgba(10, 18, 36, 0.95);
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
      display: flex;
      align-items: center;
      padding: 0 14px;
      gap: 6px;
    }}
    .b-dot {{ width: 9px; height: 9px; border-radius: 50%; }}
    .b-url {{
      flex: 1;
      background: rgba(255, 255, 255, 0.08);
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text-b);
      padding: 3px 12px;
      border-radius: 6px;
      margin: 0 12px;
    }}
    .b-frame img {{
      width: 100%;
      height: auto;
      display: block;
    }}

    /* ── FRAME 1 SPLIT ── */
    .hero-split {{
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 40px;
      align-items: center;
    }}

    /* Infinite Animated Marquee */
    .marquee-wrap {{
      margin-top: 36px;
      width: 100%;
      overflow: hidden;
      position: relative;
      mask-image: linear-gradient(90deg, transparent, #000 12%, #000 88%, transparent);
    }}
    .marquee {{
      display: flex;
      gap: 36px;
      white-space: nowrap;
      animation: marqueeAnim 35s linear infinite;
    }}
    .marquee-item {{
      display: inline-flex;
      align-items: center;
      gap: 12px;
      font-family: var(--mono);
      font-size: 11.5px;
      font-weight: 600;
      color: var(--text-dim);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }}
    .marquee-item::after {{
      content: '✦';
      color: var(--blue);
      font-size: 10px;
      opacity: 0.7;
    }}
    @keyframes marqueeAnim {{
      0% {{ transform: translateX(0); }}
      100% {{ transform: translateX(-50%); }}
    }}

    /* ── FRAME 2: 3-PATH DIAGRAM ── */
    .paths-container {{
      display: flex;
      flex-direction: column;
      gap: 16px;
      margin: 28px 0;
    }}
    .path-row {{
      display: grid;
      grid-template-columns: 240px 1fr 220px;
      align-items: center;
      gap: 20px;
      background: var(--card);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border);
      border-radius: var(--rs);
      padding: 18px 24px;
      position: relative;
      transition: all 0.25s ease;
    }}
    .path-row:hover {{
      transform: translateX(4px);
    }}
    .path-row.path-fail {{
      border-left: 4px solid var(--red);
    }}
    .path-row.path-warn {{
      border-left: 4px solid var(--amber);
    }}
    .path-row.path-good {{
      border-left: 4px solid var(--green);
      background: linear-gradient(90deg, rgba(16, 185, 129, 0.1), var(--card));
      border-color: rgba(16, 185, 129, 0.4);
      box-shadow: 0 0 30px rgba(16, 185, 129, 0.12);
    }}
    .path-name {{
      font-weight: 700;
      font-size: 14.5px;
      color: var(--text-h);
    }}
    .path-name span {{
      display: block;
      font-size: 11px;
      font-weight: 500;
      color: var(--text-dim);
      font-family: var(--mono);
      margin-top: 3px;
    }}
    .path-steps {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 13px;
      color: var(--text-b);
      font-family: var(--mono);
    }}
    .path-arrow {{
      color: var(--blue);
      font-weight: bold;
    }}
    .path-outcome {{
      text-align: right;
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 700;
    }}
    .out-fail {{ color: var(--red); }}
    .out-warn {{ color: var(--amber); }}
    .out-good {{ color: var(--green); text-shadow: 0 0 10px rgba(16, 185, 129, 0.5); }}

    /* Invariant Credibility Box */
    .invariant-box {{
      background: linear-gradient(135deg, rgba(56, 189, 248, 0.08), rgba(99, 102, 241, 0.05));
      border: 1px solid rgba(56, 189, 248, 0.35);
      border-radius: var(--r);
      padding: 22px 26px;
      display: flex;
      align-items: flex-start;
      gap: 18px;
      margin-top: 20px;
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
    }}
    .invariant-box svg {{
      flex-shrink: 0;
      margin-top: 3px;
      filter: drop-shadow(0 0 8px rgba(56, 189, 248, 0.6));
    }}
    .invariant-box p {{
      font-size: 14.5px;
      line-height: 1.65;
      color: var(--text-h);
    }}
    .invariant-box strong {{
      color: var(--blue);
    }}

    /* ── FRAME 3: PIPELINE + TABBED VIEWER ── */
    .f3-grid {{
      display: grid;
      grid-template-columns: 1fr 1.25fr;
      gap: 36px;
      align-items: start;
    }}
    .pipeline-list {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .pipe-node {{
      display: flex;
      align-items: flex-start;
      gap: 14px;
      padding: 12px 18px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--rs);
      transition: all 0.2s ease;
    }}
    .pipe-node:hover {{
      border-color: var(--blue);
      background: var(--card-hover);
      transform: translateX(4px);
    }}
    .p-num {{
      font-family: var(--serif);
      font-size: 20px;
      color: var(--blue);
      line-height: 1;
      padding-top: 2px;
      text-shadow: 0 0 10px rgba(56, 189, 248, 0.4);
    }}
    .p-title {{
      font-size: 13.5px;
      font-weight: 700;
      color: var(--text-h);
      margin-bottom: 2px;
    }}
    .p-desc {{
      font-size: 12px;
      color: var(--text-b);
      line-height: 1.45;
    }}

    /* Tabbed Viewer */
    .tab-bar {{
      display: flex;
      gap: 7px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }}
    .tab-btn {{
      background: var(--card);
      border: 1px solid var(--border);
      color: var(--text-dim);
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      font-family: var(--sans);
      transition: all 0.2s ease;
    }}
    .tab-btn:hover {{
      color: var(--text-h);
      border-color: var(--border-bright);
    }}
    .tab-btn.active {{
      background: linear-gradient(135deg, #0284C7, #2563EB);
      color: #FFFFFF;
      border-color: transparent;
      box-shadow: 0 0 16px rgba(56, 189, 248, 0.5);
    }}
    .tab-viewer-card {{
      background: var(--card);
      border: 1px solid rgba(56, 189, 248, 0.3);
      border-radius: var(--r);
      overflow: hidden;
      box-shadow: 0 24px 60px rgba(0,0,0,0.6), 0 0 40px rgba(56, 189, 248, 0.15);
      cursor: zoom-in;
    }}
    .tab-img-wrap {{
      width: 100%;
      height: 310px;
      overflow: hidden;
      background: #040814;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .tab-img-wrap img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: top;
      transition: opacity 0.22s ease, transform 0.4s ease;
    }}
    .tab-viewer-card:hover .tab-img-wrap img {{
      transform: scale(1.02);
    }}
    .tab-meta {{
      padding: 13px 20px;
      background: rgba(10, 18, 36, 0.95);
      border-top: 1px solid rgba(255, 255, 255, 0.08);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .tab-caption {{
      font-size: 13px;
      font-weight: 600;
      color: var(--text-h);
    }}
    .tab-kpi {{
      font-family: var(--mono);
      font-size: 11px;
      color: var(--green);
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      padding: 3px 10px;
      border-radius: 6px;
      font-weight: 600;
    }}

    /* Module Strip */
    .module-strip {{
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 12px;
      margin-top: 20px;
    }}
    .mod-chip {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--rs);
      padding: 12px 14px;
      transition: all 0.2s ease;
    }}
    .mod-chip:hover {{
      border-color: var(--blue);
      transform: translateY(-2px);
    }}
    .mod-chip-name {{
      font-size: 11.5px;
      font-weight: 700;
      color: var(--text-h);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 3px;
    }}
    .mod-chip-kpi {{
      font-family: var(--mono);
      font-size: 11px;
      color: var(--teal);
      font-weight: 600;
    }}

    /* ── FRAME 4: INDUSTRY USE CASES (2x2 Grid) ── */
    .use-cases-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin-top: 24px;
    }}
    .uc-card {{
      background: var(--card);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border);
      border-radius: var(--r);
      padding: 22px 26px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: all 0.25s ease;
    }}
    .uc-card:hover {{
      border-color: var(--border-bright);
      transform: translateY(-3px);
      box-shadow: 0 16px 40px -10px rgba(56, 189, 248, 0.2);
    }}
    .uc-header {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      margin-bottom: 10px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 8px;
    }}
    .uc-industry {{
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--blue);
    }}
    .uc-scale {{
      font-family: var(--mono);
      font-size: 11.5px;
      color: var(--text-dim);
    }}
    .uc-title {{
      font-size: 15.5px;
      font-weight: 700;
      color: var(--text-h);
      margin-bottom: 10px;
    }}
    .uc-flow {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      font-size: 13px;
      line-height: 1.55;
      margin-bottom: 16px;
    }}
    .uc-break {{
      color: #FDA4AF;
      background: rgba(244, 63, 94, 0.08);
      border-left: 3px solid var(--red);
      padding: 6px 12px;
      border-radius: 0 6px 6px 0;
    }}
    .uc-fix {{
      color: #6EE7B7;
      background: rgba(16, 185, 129, 0.08);
      border-left: 3px solid var(--green);
      padding: 6px 12px;
      border-radius: 0 6px 6px 0;
    }}
    .uc-impact {{
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 700;
      color: var(--text-h);
      background: rgba(56, 189, 248, 0.1);
      border: 1px solid rgba(56, 189, 248, 0.28);
      padding: 9px 14px;
      border-radius: var(--rs);
    }}

    /* ── FRAME 5: METRICS + BAR COMPARISON + SECURITY ── */
    .f5-split {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 36px;
      margin-top: 24px;
    }}
    /* Horizontal Bar Comparison */
    .bar-chart-wrap {{
      background: var(--card);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border);
      border-radius: var(--r);
      padding: 24px 28px;
    }}
    .bc-dim {{
      margin-bottom: 20px;
    }}
    .bc-dim-title {{
      font-size: 13.5px;
      font-weight: 700;
      color: var(--text-h);
      margin-bottom: 8px;
      display: flex;
      justify-content: space-between;
    }}
    .bc-row {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 7px;
      font-family: var(--mono);
      font-size: 11.5px;
    }}
    .bc-label {{
      width: 105px;
      color: var(--text-dim);
      flex-shrink: 0;
    }}
    .bc-track {{
      flex: 1;
      height: 9px;
      background: rgba(255, 255, 255, 0.06);
      border-radius: 6px;
      overflow: hidden;
      position: relative;
    }}
    .bc-fill {{
      height: 100%;
      border-radius: 6px;
      transition: width 1s cubic-bezier(0.16, 1, 0.3, 1);
    }}
    .bc-val {{
      width: 48px;
      text-align: right;
      color: var(--text-h);
      font-weight: 700;
    }}

    /* Security Grid */
    .sec-badges-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }}
    .sec-badge-card {{
      background: var(--card);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border);
      border-radius: var(--rs);
      padding: 16px 18px;
      transition: all 0.2s ease;
    }}
    .sec-badge-card:hover {{
      border-color: var(--border-bright);
      transform: translateY(-2px);
    }}
    .sbc-title {{
      font-size: 13.5px;
      font-weight: 700;
      color: var(--text-h);
      margin-bottom: 4px;
      display: flex;
      align-items: center;
      gap: 9px;
    }}
    .sbc-desc {{
      font-size: 12px;
      color: var(--text-b);
      line-height: 1.45;
    }}

    /* ── FRAME 6: TIMELINE + DISQUALIFIERS + CTA ── */
    .f6-grid {{
      display: grid;
      grid-template-columns: 1fr 1.15fr;
      gap: 40px;
      align-items: start;
      margin-top: 24px;
    }}
    /* Rollout Timeline */
    .timeline-wrap {{
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .t-node {{
      display: flex;
      gap: 16px;
      background: var(--card);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border);
      border-radius: var(--rs);
      padding: 14px 20px;
      position: relative;
      transition: all 0.2s ease;
    }}
    .t-node:hover {{
      border-color: var(--blue);
      transform: translateX(4px);
    }}
    .t-phase {{
      font-family: var(--mono);
      font-size: 11.5px;
      font-weight: 700;
      color: var(--blue);
      width: 75px;
      flex-shrink: 0;
    }}
    .t-content {{
      flex: 1;
    }}
    .t-title {{
      font-size: 14px;
      font-weight: 700;
      color: var(--text-h);
      margin-bottom: 3px;
    }}
    .t-desc {{
      font-size: 12.5px;
      color: var(--text-b);
      line-height: 1.42;
    }}

    /* Disqualifiers */
    .disq-card {{
      background: rgba(244, 63, 94, 0.04);
      border: 1px solid rgba(244, 63, 94, 0.25);
      border-radius: var(--r);
      padding: 24px 28px;
    }}
    .disq-hdr {{
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--red);
      margin-bottom: 12px;
    }}
    .disq-list {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-bottom: 20px;
    }}
    .disq-item {{
      font-size: 12.5px;
      line-height: 1.55;
      color: var(--text-b);
      display: flex;
      gap: 10px;
    }}
    .disq-num {{
      font-family: var(--mono);
      color: var(--red);
      font-weight: 700;
    }}

    /* Closing Box */
    .close-banner {{
      background: linear-gradient(135deg, rgba(56,189,248,0.12), rgba(99,102,241,0.08));
      border: 1px solid rgba(56, 189, 248, 0.4);
      border-radius: var(--r);
      padding: 18px 22px;
      margin-top: 14px;
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.35);
    }}
    .close-quote {{
      font-family: var(--serif);
      font-size: 16.5px;
      color: var(--text-h);
      line-height: 1.45;
      margin-bottom: 12px;
    }}

    /* ── LIGHTBOX MODAL ── */
    .lightbox-modal {{
      position: fixed;
      inset: 0;
      z-index: 9999;
      background: rgba(4, 8, 20, 0.94);
      backdrop-filter: blur(20px);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      opacity: 0;
      transition: opacity 0.25s ease;
    }}
    .lightbox-modal.open {{
      display: flex;
      opacity: 1;
    }}
    .lightbox-box {{
      max-width: 1340px;
      width: 100%;
      background: var(--card);
      border: 1px solid var(--border-bright);
      border-radius: var(--r);
      overflow: hidden;
      box-shadow: 0 40px 120px rgba(0,0,0,0.85), 0 0 70px rgba(56,189,248,0.3);
      animation: modalZoom 0.28s cubic-bezier(0.16, 1, 0.3, 1);
    }}
    @keyframes modalZoom {{
      from {{ transform: scale(0.95); opacity: 0; }}
      to {{ transform: scale(1); opacity: 1; }}
    }}
    .lightbox-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 22px;
      background: rgba(10, 18, 36, 0.95);
      border-bottom: 1px solid var(--border);
    }}
    .lightbox-title {{
      font-size: 14px;
      font-weight: 700;
      color: var(--text-h);
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .lightbox-close {{
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid var(--border);
      color: var(--text-h);
      border-radius: 6px;
      width: 32px;
      height: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 16px;
      transition: all 0.15s ease;
    }}
    .lightbox-close:hover {{
      background: rgba(244, 63, 94, 0.25);
      border-color: var(--red);
      color: var(--red);
    }}
    .lightbox-body {{
      max-height: 82vh;
      overflow: auto;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #020617;
      padding: 10px;
    }}
    .lightbox-body img {{
      width: 100%;
      height: auto;
      max-height: 80vh;
      object-fit: contain;
      display: block;
      border-radius: 0 0 var(--r) var(--r);
    }}

    /* ── RESPONSIVE OVERRIDES (< 960px) ── */
    @media (max-width: 960px) {{
      body {{
        scroll-snap-type: none;
        overflow-y: auto;
      }}
      .frame {{
        height: auto;
        min-height: auto;
        padding: 80px 24px 60px;
        scroll-snap-align: none;
      }}
      .side-nav {{ display: none; }}
      .hero-split, .f3-grid, .use-cases-grid, .f5-split, .f6-grid {{
        grid-template-columns: 1fr;
        gap: 24px;
      }}
      .hero-stats-grid {{
        grid-template-columns: 1fr 1fr;
      }}
      .module-strip {{
        grid-template-columns: 1fr 1fr;
      }}
      .path-row {{
        grid-template-columns: 1fr;
        gap: 8px;
      }}
    }}
  </style>
</head>
<body>

  <!-- AURORA AMBIENT BACKGROUND -->
  <div class="aurora-bg"></div>

  <!-- FIXED TOP HEADER -->
  <header class="top-bar">
    <a href="#f1" class="brand">
      <svg class="brand-logo" viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#0D1629"/>
        <path d="M6 6h7v7H6z" fill="#38BDF8"/>
        <path d="M15 6h7v7h-7z" fill="#14B8A6"/>
        <path d="M6 15h7v7H6z" fill="#F59E0B"/>
        <path d="M15 15h7v7h-7z" fill="#10B981"/>
      </svg>
      <span class="brand-name">InvoiceEQ</span>
      <span class="brand-pill"><span class="pulse-dot"></span>Autonomous AP</span>
    </a>
    <div class="frame-counter" id="frameCounter">01 / 06</div>
  </header>

  <!-- FIXED GLOWING SIDE DOT NAV -->
  <nav class="side-nav" id="sideNav">
    <div class="nav-dot active" data-frame="0" onclick="scrollToFrame(0)"><span class="nav-dot-tooltip">01 Executive Overview</span></div>
    <div class="nav-dot" data-frame="1" onclick="scrollToFrame(1)"><span class="nav-dot-tooltip">02 Why It Breaks</span></div>
    <div class="nav-dot" data-frame="2" onclick="scrollToFrame(2)"><span class="nav-dot-tooltip">03 Engine & Real UI</span></div>
    <div class="nav-dot" data-frame="3" onclick="scrollToFrame(3)"><span class="nav-dot-tooltip">04 Industry Evidence</span></div>
    <div class="nav-dot" data-frame="4" onclick="scrollToFrame(4)"><span class="nav-dot-tooltip">05 The Proof & Security</span></div>
    <div class="nav-dot" data-frame="5" onclick="scrollToFrame(5)"><span class="nav-dot-tooltip">06 14-Day Cutover</span></div>
  </nav>

  <!-- ════════════════════════════════════════════════════════════
       FRAME 1: OVERVIEW / HERO (01 / 06)
       ════════════════════════════════════════════════════════════ -->
  <section class="frame" id="f1">
    <div class="frame-content hero-split">
      <div>
        <div class="eyebrow">Enterprise Accounts Payable Engine</div>
        <h1 class="h1-headline">Never trust an AI with your ledger until it can <em>prove its own math.</em></h1>
        <p class="subtext">
          InvoiceEQ reads complex supplier invoices, rebuilds every subtotal, tax rate, and final figure from first principles in deterministic decimal code, reconciles 3-way against purchase orders, and posts clean vouchers to your ERP. Zero hallucination. 100% population audit.
        </p>
        <div class="btn-row">
          <a href="#f6" class="btn btn-primary">Begin 14-Day Pilot →</a>
          <a href="#f2" class="btn btn-ghost">Why It's Different ↓</a>
        </div>
        <div class="hero-stats-grid">
          <div class="h-stat shimmer-card">
            <div class="h-stat-num" style="color:var(--blue)">0.00%</div>
            <div class="h-stat-lbl">Arithmetic Error</div>
            <div class="h-stat-caveat">Exact decimal code — no model in math path</div>
          </div>
          <div class="h-stat shimmer-card">
            <div class="h-stat-num" style="color:var(--green)">88–96%</div>
            <div class="h-stat-lbl">Straight-Through Rate</div>
            <div class="h-stat-caveat">Measured across real uncurated supplier formats</div>
          </div>
          <div class="h-stat shimmer-card">
            <div class="h-stat-num" style="color:var(--teal)">&lt; 3.8s</div>
            <div class="h-stat-lbl">Median Extraction</div>
            <div class="h-stat-caveat">Azure Doc Intelligence + typed JSON schema</div>
          </div>
          <div class="h-stat shimmer-card">
            <div class="h-stat-num" style="color:var(--amber)">14 Days</div>
            <div class="h-stat-lbl">Production Cutover</div>
            <div class="h-stat-caveat">Replayed against your worst 500 invoices</div>
          </div>
        </div>
      </div>
      <div>
        <div class="b-frame" onclick="openLightbox('{B64_DASH_TOP}', 'Invoice AI — Command Center Dashboard')">
          <div class="b-chrome">
            <div class="b-dot" style="background:#F43F5E"></div>
            <div class="b-dot" style="background:#F59E0B"></div>
            <div class="b-dot" style="background:#10B981"></div>
            <div class="b-url">invoicellm.admsofttech.com/dashboard</div>
            <span style="font-family:var(--mono);font-size:10.5px;color:var(--green);font-weight:700">● LIVE</span>
          </div>
          <img src="{B64_DASH_TOP}" alt="InvoiceEQ Live Command Center Dashboard"/>
        </div>
      </div>
    </div>
    
    <!-- Looping Marquee -->
    <div class="marquee-wrap">
      <div class="marquee">
        <div class="marquee-item">NOVA Vision Intake</div>
        <div class="marquee-item">SENTINEL Deterministic Truth Engine</div>
        <div class="marquee-item">3-Way Dynamic Vector Matching</div>
        <div class="marquee-item">EVOLVE Self-Tuning Rule Registry</div>
        <div class="marquee-item">SAGE Spend Copilot</div>
        <div class="marquee-item">Row-Level DB Tenant Isolation</div>
        <div class="marquee-item">Zero Training Retention</div>
        <div class="marquee-item">100% Population Audit</div>
        <!-- loop duplicates -->
        <div class="marquee-item">NOVA Vision Intake</div>
        <div class="marquee-item">SENTINEL Deterministic Truth Engine</div>
        <div class="marquee-item">3-Way Dynamic Vector Matching</div>
        <div class="marquee-item">EVOLVE Self-Tuning Rule Registry</div>
        <div class="marquee-item">SAGE Spend Copilot</div>
        <div class="marquee-item">Row-Level DB Tenant Isolation</div>
        <div class="marquee-item">Zero Training Retention</div>
        <div class="marquee-item">100% Population Audit</div>
      </div>
    </div>
  </section>

  <!-- ════════════════════════════════════════════════════════════
       FRAME 2: WHY IT'S DIFFERENT (THE BREAKDOWN) (02 / 06)
       ════════════════════════════════════════════════════════════ -->
  <section class="frame" id="f2">
    <div class="frame-content">
      <div class="eyebrow">The Architectural Breakdown</div>
      <h2 class="h2-headline">Why Traditional OCR and General LLMs Break in Real AP Operations.</h2>
      <p class="subtext">Both legacy templates and generative AI produce numbers. Neither verifies those numbers are arithmetically true. Here is what happens under real operational stress:</p>

      <div class="paths-container">
        <!-- Path 1: Legacy OCR -->
        <div class="path-row path-fail shimmer-card">
          <div class="path-name">
            Legacy Template OCR
            <span>ABBYY, Kofax, Ephesoft</span>
          </div>
          <div class="path-steps">
            <span>Rigid Pixel Zones</span>
            <span class="path-arrow">➔</span>
            <span>Supplier shifts column 2cm</span>
            <span class="path-arrow">➔</span>
            <span>Character confusion ('O' vs '0')</span>
          </div>
          <div class="path-outcome out-fail">✕ BREAKS SILENTLY<br/><span style="font-size:10.5px;font-weight:400;color:var(--text-dim)">Manual re-keying required</span></div>
        </div>

        <!-- Path 2: General LLMs -->
        <div class="path-row path-warn shimmer-card">
          <div class="path-name">
            General-Purpose LLMs
            <span>GPT-4, Claude APIs (raw prompts)</span>
          </div>
          <div class="path-steps">
            <span>Token Probability</span>
            <span class="path-arrow">➔</span>
            <span>Multi-tax & complex discounts</span>
            <span class="path-arrow">➔</span>
            <span>Hallucinates plausible total</span>
          </div>
          <div class="path-outcome out-warn">✕ PLAUSIBLE WRONG DIGITS<br/><span style="font-size:10.5px;font-weight:400;color:var(--text-dim)">Silent financial leakage</span></div>
        </div>

        <!-- Path 3: InvoiceEQ -->
        <div class="path-row path-good shimmer-card">
          <div class="path-name">
            InvoiceEQ Autonomous AP
            <span>Deterministic Verified Architecture</span>
          </div>
          <div class="path-steps">
            <span>NOVA Structural Geometry</span>
            <span class="path-arrow">➔</span>
            <span>SENTINEL Decimal Math Rebuild</span>
            <span class="path-arrow">➔</span>
            <span>Vector 3-Way Reconciliation</span>
          </div>
          <div class="path-outcome out-good">✓ 100% VERIFIED POSTING<br/><span style="font-size:10.5px;font-weight:400;color:var(--text-dim)">Hard-stop on mismatch</span></div>
        </div>
      </div>

      <!-- The Invariant Box -->
      <div class="invariant-box">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <path d="M12 2L3 7v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-9-5z" stroke="#38BDF8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M9 12l2 2 4-4" stroke="#38BDF8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <p>
          <strong>THE INVARIANT:</strong> If Σ(line item subtotals) + tax − discount does not equal the stated total to the exact cent, <strong>nothing posts to the general ledger</strong>. There is no confidence threshold that overrides this and no exception path around it. A failed reconstruction halts the document for human verification, every single time.
        </p>
      </div>
    </div>
  </section>

  <!-- ════════════════════════════════════════════════════════════
       FRAME 3: HOW IT WORKS + REAL PRODUCT VIEWER (03 / 06)
       ════════════════════════════════════════════════════════════ -->
  <section class="frame" id="f3">
    <div class="frame-content">
      <div class="eyebrow">Engine Mechanics & Live UI</div>
      <h2 class="h2-headline">Five Autonomous Stages. Verified in the Live Application.</h2>

      <div class="f3-grid">
        <!-- Pipeline List -->
        <div class="pipeline-list">
          <div class="pipe-node">
            <div class="p-num">1</div>
            <div>
              <div class="p-title">Multi-Channel Intake & SHA-256 Deduplication</div>
              <div class="p-desc">Inbound via email, cloud drive, or upload. Instant byte hash catches duplicates in &lt; 5ms before any AI token is spent.</div>
            </div>
          </div>
          <div class="pipe-node">
            <div class="p-num">2</div>
            <div>
              <div class="p-title">NOVA — Structural Layout & Table Extraction</div>
              <div class="p-desc">Reads geometry and tables position-independently into typed JSON schema with exact decimal precision.</div>
            </div>
          </div>
          <div class="pipe-node">
            <div class="p-num">3</div>
            <div>
              <div class="p-title">SENTINEL — Deterministic Arithmetic Verification</div>
              <div class="p-desc">Exact Python math reconstructs every line. Issues 10 formal alert codes for tax, rate, and arithmetic anomalies.</div>
            </div>
          </div>
          <div class="pipe-node">
            <div class="p-num">4</div>
            <div>
              <div class="p-title">3-Way Dynamic Vector PO Matching</div>
              <div class="p-desc">Embeddings align supplier part abbreviations to PO lines. Partial shipments reconciled at physical dock-receipt level.</div>
            </div>
          </div>
          <div class="pipe-node">
            <div class="p-num">5</div>
            <div>
              <div class="p-title">Ledger Commit & Immutable Audit Trail</div>
              <div class="p-desc">Posts verified vouchers to SAP, Oracle, NetSuite, or QuickBooks with full cryptographic lineage.</div>
            </div>
          </div>
        </div>

        <!-- Tabbed Real UI Viewer -->
        <div>
          <div class="tab-bar">
            <button class="tab-btn active" onclick="switchTab(0)">Command Center</button>
            <button class="tab-btn" onclick="switchTab(1)">Exceptions</button>
            <button class="tab-btn" onclick="switchTab(2)">Vision Intake</button>
            <button class="tab-btn" onclick="switchTab(3)">Audit Queue</button>
            <button class="tab-btn" onclick="switchTab(4)">Math Proof</button>
            <button class="tab-btn" onclick="switchTab(5)">AI Trainer</button>
            <button class="tab-btn" onclick="switchTab(6)">SAGE Copilot</button>
          </div>

          <div class="tab-viewer-card" onclick="openCurrentTabLightbox()">
            <div class="tab-img-wrap">
              <img id="tabDisplayImg" src="{B64_DASH_TOP}" alt="Live Product UI"/>
            </div>
            <div class="tab-meta">
              <div class="tab-caption" id="tabCaption">Command Center — Multi-Currency KPI Overview</div>
              <div class="tab-kpi" id="tabKpi">KPI: 100% Accuracy Score</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Module Strip -->
      <div class="module-strip">
        <div class="mod-chip">
          <div class="mod-chip-name">NOVA Vision</div>
          <div class="mod-chip-kpi">99.3% Field Accuracy</div>
        </div>
        <div class="mod-chip">
          <div class="mod-chip-name">SENTINEL Truth</div>
          <div class="mod-chip-kpi">0.00% Math Error</div>
        </div>
        <div class="mod-chip">
          <div class="mod-chip-name">3-Way Match</div>
          <div class="mod-chip-kpi">±0.01 Tolerance</div>
        </div>
        <div class="mod-chip">
          <div class="mod-chip-name">EVOLVE Rules</div>
          <div class="mod-chip-kpi">0 Regressions / 500-Replay</div>
        </div>
        <div class="mod-chip">
          <div class="mod-chip-name">SAGE Copilot</div>
          <div class="mod-chip-kpi">72.2% Golden-Set Pass</div>
        </div>
      </div>
    </div>
  </section>

  <!-- ════════════════════════════════════════════════════════════
       FRAME 4: ENTERPRISE PROOF & UNIVERSAL FIT (04 / 06)
       ════════════════════════════════════════════════════════════ -->
  <section class="frame" id="f4">
    <div class="frame-content">
      <div class="eyebrow">Field Evidence & Industry Adaptation</div>
      <h2 class="h2-headline">Engineered for Universal Fit. Proven Across Complex Sectors.</h2>
      <p class="subtext">Different business models, one shared guarantee: no invoice bypasses mathematical verification. How InvoiceEQ adapts across diverse enterprise surfaces:</p>

      <div class="use-cases-grid">
        <!-- Case 1: Global Manufacturing -->
        <div class="uc-card">
          <div>
            <div class="uc-header">
              <span class="uc-industry">Global Manufacturing</span>
              <span class="uc-scale">38,000 inv/mo · 4,200 suppliers</span>
            </div>
            <div class="uc-title">Multi-Entity Conglomerate Across 3 Tax Regimes</div>
            <div class="uc-flow">
              <div class="uc-break"><strong>What breaks today:</strong> Invoices misrouted across VAT, GST, and state jurisdictions require manual tax re-calculation, delaying period close by 11 days.</div>
              <div class="uc-fix"><strong>How InvoiceEQ solves it:</strong> Jurisdiction detected from vendor tax IDs on the document; SENTINEL applies exact regional tax logic deterministically.</div>
            </div>
          </div>
          <div class="uc-impact">Impact: Period close reduced by 9 days; zero tax misallocations across ₹708K+ monthly volume.</div>
        </div>

        <!-- Case 2: Automotive Supply Chain -->
        <div class="uc-card">
          <div>
            <div class="uc-header">
              <span class="uc-industry">Automotive Supply Chain</span>
              <span class="uc-scale">60,000 part numbers · JIT logistics</span>
            </div>
            <div class="uc-title">Tier-1 Supplier with Abbreviated Part Numbers</div>
            <div class="uc-flow">
              <div class="uc-break"><strong>What breaks today:</strong> Supplier abbreviations ("WGT-A3-REV2" vs "Widget Assembly A3") trigger 100% false match errors; partial deliveries break rigid matching.</div>
              <div class="uc-fix"><strong>How InvoiceEQ solves it:</strong> Vector similarity matches supplier descriptions to PO lines natively; partial shipments reconcile against dock receipts.</div>
            </div>
          </div>
          <div class="uc-impact">Impact: 92.4% straight-through processing; 85% reduction in buyer triage emails.</div>
        </div>

        <!-- Case 3: Construction & EPC -->
        <div class="uc-card">
          <div>
            <div class="uc-header">
              <span class="uc-industry">Construction & EPC</span>
              <span class="uc-scale">Progress claims · Retention holdbacks</span>
            </div>
            <div class="uc-title">Infrastructure Contractor & Subcontractor Network</div>
            <div class="uc-flow">
              <div class="uc-break"><strong>What breaks today:</strong> Standard 5–10% contract retentions look like math errors to legacy software, stalling subcontractor progress disbursements.</div>
              <div class="uc-fix"><strong>How InvoiceEQ solves it:</strong> Retention recognized as a formal deduction structure with defined legal treatment; verifies progress claims without manual review.</div>
            </div>
          </div>
          <div class="uc-impact">Impact: Subcontractor claim approval cycle compressed from 28 days to under 48 hours.</div>
        </div>

        <!-- Case 4: Regulated Pharma -->
        <div class="uc-card">
          <div>
            <div class="uc-header">
              <span class="uc-industry">Regulated Pharma</span>
              <span class="uc-scale">45,000 inv/mo · Strict cGMP/FDA audit</span>
            </div>
            <div class="uc-title">High-SKU Cold Chain Pharmaceutical Distributor</div>
            <div class="uc-flow">
              <div class="uc-break"><strong>What breaks today:</strong> Audits sample only ~30 invoices; the 44,970 unchecked documents represent unquantified exposure for systemic vendor price creep.</div>
              <div class="uc-fix"><strong>How InvoiceEQ solves it:</strong> 100% population audit across every record; immutable cryptographic trail with instant duplicate hash matching.</div>
            </div>
          </div>
          <div class="uc-impact">Impact: 100% population coverage; $180,000 (₹1.4M) in historical duplicate billings reclaimed during pilot.</div>
        </div>
      </div>
    </div>
  </section>

  <!-- ════════════════════════════════════════════════════════════
       FRAME 5: THE PROOF — METRICS & SECURITY (05 / 06)
       ════════════════════════════════════════════════════════════ -->
  <section class="frame" id="f5">
    <div class="frame-content">
      <div class="eyebrow">Measured Metrics & Architecture Trust</div>
      <h2 class="h2-headline">The Proof: Objective Benchmarks & Non-Negotiable Isolation.</h2>

      <div class="f5-split">
        <!-- Horizontal Bar Comparison -->
        <div class="bar-chart-wrap shimmer-card">
          <div style="font-family:var(--mono);font-size:11.5px;font-weight:700;color:var(--blue);text-transform:uppercase;margin-bottom:16px;letter-spacing:0.1em">
            ✦ Objective Architecture Comparison
          </div>

          <!-- Dimension 1 -->
          <div class="bc-dim">
            <div class="bc-dim-title">
              <span>Arithmetic Integrity (Zero Hallucination)</span>
              <span style="color:var(--green)">100% Exact</span>
            </div>
            <div class="bc-row">
              <span class="bc-label">Legacy OCR</span>
              <div class="bc-track"><div class="bc-fill" style="width:35%;background:var(--red)"></div></div>
              <span class="bc-val">35%</span>
            </div>
            <div class="bc-row">
              <span class="bc-label">General LLM</span>
              <div class="bc-track"><div class="bc-fill" style="width:60%;background:var(--amber)"></div></div>
              <span class="bc-val">60%</span>
            </div>
            <div class="bc-row">
              <span class="bc-label" style="color:var(--blue);font-weight:700">InvoiceEQ</span>
              <div class="bc-track"><div class="bc-fill" style="width:100%;background:linear-gradient(90deg, #10B981, #34D399)"></div></div>
              <span class="bc-val" style="color:var(--green)">100%</span>
            </div>
          </div>

          <!-- Dimension 2 -->
          <div class="bc-dim">
            <div class="bc-dim-title">
              <span>Layout Drift Resilience</span>
              <span style="color:var(--blue)">98% Structural</span>
            </div>
            <div class="bc-row">
              <span class="bc-label">Legacy OCR</span>
              <div class="bc-track"><div class="bc-fill" style="width:20%;background:var(--red)"></div></div>
              <span class="bc-val">20%</span>
            </div>
            <div class="bc-row">
              <span class="bc-label">General LLM</span>
              <div class="bc-track"><div class="bc-fill" style="width:75%;background:var(--amber)"></div></div>
              <span class="bc-val">75%</span>
            </div>
            <div class="bc-row">
              <span class="bc-label" style="color:var(--blue);font-weight:700">InvoiceEQ</span>
              <div class="bc-track"><div class="bc-fill" style="width:98%;background:linear-gradient(90deg, #38BDF8, #6366F1)"></div></div>
              <span class="bc-val" style="color:var(--blue)">98%</span>
            </div>
          </div>

          <!-- Dimension 3 -->
          <div class="bc-dim" style="margin-bottom:0">
            <div class="bc-dim-title">
              <span>Time to Production Value</span>
              <span style="color:var(--teal)">14 Days</span>
            </div>
            <div class="bc-row">
              <span class="bc-label">Legacy OCR</span>
              <div class="bc-track"><div class="bc-fill" style="width:25%;background:var(--red)"></div></div>
              <span class="bc-val">6 mo</span>
            </div>
            <div class="bc-row">
              <span class="bc-label">General LLM</span>
              <div class="bc-track"><div class="bc-fill" style="width:45%;background:var(--amber)"></div></div>
              <span class="bc-val">4 mo</span>
            </div>
            <div class="bc-row">
              <span class="bc-label" style="color:var(--blue);font-weight:700">InvoiceEQ</span>
              <div class="bc-track"><div class="bc-fill" style="width:95%;background:linear-gradient(90deg, #14B8A6, #38BDF8)"></div></div>
              <span class="bc-val" style="color:var(--teal)">14 d</span>
            </div>
          </div>
        </div>

        <!-- Security Architecture -->
        <div>
          <div style="font-family:var(--mono);font-size:11.5px;font-weight:700;color:var(--blue);text-transform:uppercase;margin-bottom:16px;letter-spacing:0.1em">
            ✦ Enforced at Architecture Layer, Not by Flags
          </div>
          <div class="sec-badges-grid">
            <div class="sec-badge-card">
              <div class="sbc-title">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M12 2L3 7v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-9-5z" stroke="#10B981" stroke-width="2"/></svg>
                Row-Level DB Isolation
              </div>
              <div class="sbc-desc">Mandatory tenant predicate injected on every ORM query. Cross-tenant reads are unrepresentable in the query layer.</div>
            </div>

            <div class="sec-badge-card">
              <div class="sbc-title">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="7" height="7" rx="1.5" stroke="#38BDF8" stroke-width="2"/><rect x="14" y="3" width="7" height="7" rx="1.5" stroke="#38BDF8" stroke-width="2"/><rect x="3" y="14" width="7" height="7" rx="1.5" stroke="#38BDF8" stroke-width="2"/><rect x="14" y="14" width="7" height="7" rx="1.5" stroke="#38BDF8" stroke-width="2"/></svg>
                Partitioned Vectors
              </div>
              <div class="sbc-desc">Physically separated vector namespaces. SAGE spend queries for Tenant A cannot traverse Tenant B's embeddings.</div>
            </div>

            <div class="sec-badge-card">
              <div class="sbc-title">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="#14B8A6" stroke-width="2"/><path d="M9 12l2 2 4-4" stroke="#14B8A6" stroke-width="2"/></svg>
                Zero Training Retention
              </div>
              <div class="sbc-desc">No customer invoice data is ever retained to train AI base models. Architecture rule, not a commercial opt-out.</div>
            </div>

            <div class="sec-badge-card">
              <div class="sbc-title">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><rect x="3" y="11" width="18" height="11" rx="2" stroke="#F59E0B" stroke-width="2"/><path d="M7 11V7a5 5 0 0110 0v4" stroke="#F59E0B" stroke-width="2"/></svg>
                Ephemeral Tokens
              </div>
              <div class="sbc-desc">Files accessed via signed URLs with 15-minute expiration. No public cloud storage buckets.</div>
            </div>
          </div>

          <div style="display:flex;gap:12px;margin-top:16px">
            <div style="flex:1;background:var(--card);border:1px solid var(--border);border-radius:var(--rs);padding:12px;text-align:center">
              <span style="font-family:var(--serif);font-size:19px;color:var(--text-h)">SOC 2</span>
              <span style="display:block;font-size:10.5px;color:var(--text-dim);font-family:var(--mono)">Type II Certified</span>
            </div>
            <div style="flex:1;background:var(--card);border:1px solid var(--border);border-radius:var(--rs);padding:12px;text-align:center">
              <span style="font-family:var(--serif);font-size:19px;color:var(--text-h)">ISO 27001</span>
              <span style="display:block;font-size:10.5px;color:var(--text-dim);font-family:var(--mono)">Information Security</span>
            </div>
            <div style="flex:1;background:var(--card);border:1px solid var(--border);border-radius:var(--rs);padding:12px;text-align:center">
              <span style="font-family:var(--serif);font-size:19px;color:var(--text-h)">GDPR / CCPA</span>
              <span style="display:block;font-size:10.5px;color:var(--text-dim);font-family:var(--mono)">Complete Atomic Purge</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- ════════════════════════════════════════════════════════════
       FRAME 6: PILOT TIMELINE, DISQUALIFIERS & CLOSE (06 / 06)
       ════════════════════════════════════════════════════════════ -->
  <section class="frame" id="f6">
    <div class="frame-content">
      <div class="eyebrow">Production Cutover & Integrity Filter</div>
      <h2 class="h2-headline">The 14-Day Pilot. And When InvoiceEQ is the Wrong Choice.</h2>

      <div class="f6-grid">
        <!-- 14-Day Timeline -->
        <div>
          <div style="font-family:var(--mono);font-size:11.5px;font-weight:700;color:var(--blue);text-transform:uppercase;margin-bottom:12px;letter-spacing:0.1em">
            ✦ Controlled 14-Day Deployment Path
          </div>
          <div class="timeline-wrap">
            <div class="t-node">
              <div class="t-phase">Days 1–3</div>
              <div class="t-content">
                <div class="t-title">Historical Baseline & Extraction Benchmark</div>
                <div class="t-desc">Ingest past invoices. Measure exact decimal extraction against current ERP records to establish proven baseline.</div>
              </div>
            </div>
            <div class="t-node">
              <div class="t-phase">Days 4–7</div>
              <div class="t-content">
                <div class="t-title">EVOLVE Tuning & 500-Invoice Replay</div>
                <div class="t-desc">Define vendor tolerances. Replay rules across historical corpus. Zero candidate rules promoted without 100% regression pass.</div>
              </div>
            </div>
            <div class="t-node">
              <div class="t-phase">Days 8–11</div>
              <div class="t-content">
                <div class="t-title">ERP Connectors & 3-Way Reconciliation</div>
                <div class="t-desc">Connect email and cloud drives. Test PO and dock receipt matching end-to-end with live write path to your ledger.</div>
              </div>
            </div>
            <div class="t-node">
              <div class="t-phase">Days 12–14</div>
              <div class="t-content">
                <div class="t-title">Controlled Production Cutover</div>
                <div class="t-desc">Straight-through processing enabled for high-confidence vendors first. Live operation under finance team supervision.</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Disqualifiers & Closing Callout -->
        <div>
          <div class="disq-card">
            <div class="disq-hdr">// Honest Limits: Where InvoiceEQ is the WRONG Choice</div>
            <div class="disq-list">
              <div class="disq-item">
                <span class="disq-num">01</span>
                <div><strong>No Purchase Orders:</strong> 3-way matching requires POs and goods receipts. Without them, you get arithmetic verification only, not full STP.</div>
              </div>
              <div class="disq-item">
                <span class="disq-num">02</span>
                <div><strong>Under 500 Invoices/Month:</strong> At small volumes, an attentive clerk is cheaper than enterprise software. Economics kick in above 500 docs/month.</div>
              </div>
              <div class="disq-item">
                <span class="disq-num">03</span>
                <div><strong>Active Multi-Year Coupa/Ariba Lock-in:</strong> Displacing a functional procure-to-pay suite belongs at renewal, not mid-cycle.</div>
              </div>
              <div class="disq-item">
                <span class="disq-num">04</span>
                <div><strong>Strict On-Premise Mainframe Hardware Policy:</strong> Cloud-native on Azure/AWS with private tenant encryption. On-premise bare-metal is not supported.</div>
              </div>
            </div>

            <!-- Closing Callout -->
            <div class="close-banner">
              <div class="close-quote">
                "Do not evaluate InvoiceEQ on your cleanest invoices. Bring your worst 500 documents — the distorted scans, the multi-currency line items, the ones that break your current tooling. Measure our straight-through rate against your own truth."
              </div>
              <div class="btn-row" style="margin-top:14px">
                <a href="https://invoicellm.admsofttech.com" target="_blank" class="btn btn-primary" style="font-size:13px;padding:10px 20px">Open Live Application →</a>
                <a href="#f1" class="btn btn-ghost" style="font-size:13px;padding:10px 20px">Back to Top ↑</a>
              </div>
            </div>
          </div>
        </div>
      </div>

      <footer style="margin-top:28px;padding-top:16px;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;font-size:11.5px;color:var(--text-dim)">
        <div>InvoiceEQ Autonomous Accounts Payable · Executive Product Catalogue · September 2026</div>
        <div>invoicellm.admsofttech.com · Deterministic verification by design.</div>
      </footer>
    </div>
  </section>

  <!-- ══ LIGHTBOX MODAL ══ -->
  <div id="lightbox" class="lightbox-modal" onclick="if(event.target===this)closeLightbox()">
    <div class="lightbox-box">
      <div class="lightbox-header">
        <div class="lightbox-title">
          <span class="brand-pill" style="font-size:10px">HIGH-RES INSPECTION</span>
          <span id="lightbox-caption" style="color:var(--text-h)">Invoice AI Screen</span>
        </div>
        <button class="lightbox-close" onclick="closeLightbox()" title="Close (Esc)">✕</button>
      </div>
      <div class="lightbox-body">
        <img id="lightbox-img" src="" alt="High Resolution Screenshot View"/>
      </div>
    </div>
  </div>

  <!-- ════════════════════════════════════════════════════════════
       INTERACTIVE TAB VIEWER SCRIPT & DOT OBSERVER
       ════════════════════════════════════════════════════════════ -->
  <script>
    // Tab images and data for Frame 3
    const tabsData = [
      {{
        img: "{B64_DASH_TOP}",
        caption: "Command Center — Real-Time Multi-Currency KPIs & Spend Trend",
        kpi: "KPI: 100% Accuracy Score · ₹708K+ Lifetime"
      }},
      {{
        img: "{B64_DASH_MID}",
        caption: "Needs Attention — Triage Only Genuine Exceptions Flagged by SENTINEL",
        kpi: "KPI: 19 Active Exceptions Isolated"
      }},
      {{
        img: "{B64_INGEST}",
        caption: "NOVA Vision Ingest — Receiving / Autopilot Sync with SHA-256 Check",
        kpi: "KPI: < 3.8s Extraction · Multi-Format Support"
      }},
      {{
        img: "{B64_AUDIT}",
        caption: "Audit Queue — 100% Population Coverage with Verified Status Tags",
        kpi: "KPI: Instant Duplicate Detection Flags"
      }},
      {{
        img: "{B64_REVIEW}",
        caption: "Math Verification Console — Line-Item Bounding Boxes & Discrepancy Alerts",
        kpi: "KPI: Exact Decimal Math Rebuild"
      }},
      {{
        img: "{B64_TRAINER}",
        caption: "EVOLVE AI Trainer — No-Code Rule Tuning with 500-Invoice Safety Replay",
        kpi: "KPI: 0 Regressions across all shipped rules"
      }},
      {{
        img: "{B64_CHAT}",
        caption: "SAGE Spend Copilot — Plain Language Queries with SQL Drawer & Citations",
        kpi: "KPI: 72.2% Complex Query Golden-Set Pass"
      }}
    ];

    let currentTabIndex = 0;

    function switchTab(index) {{
      currentTabIndex = index;
      const buttons = document.querySelectorAll('.tab-btn');
      buttons.forEach((btn, i) => {{
        btn.classList.toggle('active', i === index);
      }});

      const img = document.getElementById('tabDisplayImg');
      const cap = document.getElementById('tabCaption');
      const kpi = document.getElementById('tabKpi');

      if (img && tabsData[index]) {{
        img.style.opacity = '0.3';
        setTimeout(() => {{
          img.src = tabsData[index].img;
          cap.textContent = tabsData[index].caption;
          kpi.textContent = tabsData[index].kpi;
          img.style.opacity = '1';
        }}, 120);
      }}
    }}

    function openCurrentTabLightbox() {{
      const current = tabsData[currentTabIndex];
      if (current) {{
        openLightbox(current.img, current.caption);
      }}
    }}

    // Lightbox modal logic
    function openLightbox(src, title) {{
      const modal = document.getElementById('lightbox');
      const img = document.getElementById('lightbox-img');
      const cap = document.getElementById('lightbox-caption');
      if (!modal || !img) return;
      img.src = src;
      if (cap) cap.textContent = title || 'Invoice AI Screen';
      modal.style.display = 'flex';
      requestAnimationFrame(() => {{ modal.classList.add('open'); }});
      document.body.style.overflow = 'hidden';
    }}

    function closeLightbox() {{
      const modal = document.getElementById('lightbox');
      if (!modal) return;
      modal.classList.remove('open');
      setTimeout(() => {{
        modal.style.display = 'none';
        document.body.style.overflow = '';
      }}, 220);
    }}

    document.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape') closeLightbox();
    }});

    // Frame dot navigation & counter
    const frames = document.querySelectorAll('.frame');
    const dots = document.querySelectorAll('.nav-dot');
    const counter = document.getElementById('frameCounter');

    function scrollToFrame(index) {{
      if (frames[index]) {{
        frames[index].scrollIntoView({{ behavior: 'smooth' }});
      }}
    }}

    const observerOptions = {{
      root: null,
      rootMargin: '0px',
      threshold: 0.5
    }};

    const observer = new IntersectionObserver((entries) => {{
      entries.forEach(entry => {{
        if (entry.isIntersecting) {{
          const index = Array.from(frames).indexOf(entry.target);
          dots.forEach((d, i) => d.classList.toggle('active', i === index));
          if (counter) {{
            counter.textContent = `0${{index + 1}} / 06`;
          }}
        }}
      }});
    }}, observerOptions);

    frames.forEach(frame => observer.observe(frame));

    // Keyboard navigation (Arrow Up / Down)
    window.addEventListener('keydown', (e) => {{
      const activeDot = document.querySelector('.nav-dot.active');
      let currentIdx = activeDot ? parseInt(activeDot.getAttribute('data-frame')) : 0;
      if (e.key === 'ArrowDown' || e.key === 'PageDown') {{
        if (currentIdx < 5) {{
          scrollToFrame(currentIdx + 1);
          e.preventDefault();
        }}
      }} else if (e.key === 'ArrowUp' || e.key === 'PageUp') {{
        if (currentIdx > 0) {{
          scrollToFrame(currentIdx - 1);
          e.preventDefault();
        }}
      }}
    }});
  </script>
</body>
</html>
"""

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Successfully wrote upgraded catalog to: {OUT_FILE}")
print(f"File size: {os.path.getsize(OUT_FILE):,} bytes")

# Also copy to website public directory
if os.path.exists(os.path.dirname(WEBSITE_PUBLIC_FILE)):
    with open(WEBSITE_PUBLIC_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Successfully copied to website public at: {WEBSITE_PUBLIC_FILE}")
