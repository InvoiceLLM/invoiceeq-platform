"""
InvoiceEQ Live Screenshot Capturer
Logs into https://invoicellm.admsofttech.com and captures all pages
"""
import asyncio
import os
from playwright.async_api import async_playwright

OUT = r"d:\testllm\Invoice-LLM-SOLO-Dev\Prod_Invoice_LLM\docs\product_catalog"
EMAIL = "mbirla@infinevocloud.com"
PASSWORD = "Newpassword#2815"
BASE = "https://invoicellm.admsofttech.com"

PAGES = [
    ("dashboard", "/dashboard"),
    ("ingest",    "/ingest"),
    ("audit",     "/audit"),
    ("history",   "/history"),
    ("trainer",   "/trainer"),
    ("chat",      "/chat"),
    ("settings",  "/settings"),
    ("subs",      "/subscriptions"),
]

async def capture():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = await ctx.new_page()

        # ── 1. Navigate to sign-in ──────────────────────────────────
        print("Navigating to sign-in page...")
        await page.goto(f"{BASE}/sign-in", wait_until="networkidle", timeout=30000)
        await page.screenshot(path=os.path.join(OUT, "step_01_signin.png"))
        print("Sign-in page loaded")

        # ── 2. Enter email ──────────────────────────────────────────
        await page.wait_for_timeout(2000)
        
        # Clerk sign-in form - look for email/identifier input
        email_selectors = [
            'input[name="identifier"]',
            'input[type="email"]',
            'input[name="email"]',
            '#identifier-field',
            'input[placeholder*="mail"]',
            'input[placeholder*="Email"]',
        ]
        for sel in email_selectors:
            try:
                el = page.locator(sel)
                if await el.count() > 0:
                    await el.fill(EMAIL)
                    print(f"  Typed email in: {sel}")
                    break
            except:
                continue
        
        await page.screenshot(path=os.path.join(OUT, "step_02_email.png"))

        # Click Continue
        continue_btns = ['button[type="submit"]', 'button:has-text("Continue")', 'button:has-text("Sign in")']
        for sel in continue_btns:
            try:
                btn = page.locator(sel)
                if await btn.count() > 0:
                    await btn.first.click()
                    print(f"  Clicked: {sel}")
                    break
            except:
                continue
        
        await page.wait_for_timeout(3000)
        await page.screenshot(path=os.path.join(OUT, "step_03_after_email.png"))

        # ── 3. Enter password ───────────────────────────────────────
        pwd_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            '#password-field',
        ]
        for sel in pwd_selectors:
            try:
                el = page.locator(sel)
                if await el.count() > 0:
                    await el.fill(PASSWORD)
                    print(f"  Typed password in: {sel}")
                    break
            except:
                continue

        # Click Sign In / Continue
        for sel in continue_btns:
            try:
                btn = page.locator(sel)
                if await btn.count() > 0:
                    await btn.first.click()
                    print(f"  Clicked sign-in: {sel}")
                    break
            except:
                continue

        print("Waiting for login to complete...")
        await page.wait_for_timeout(6000)
        await page.screenshot(path=os.path.join(OUT, "step_04_logged_in.png"))
        print(f"Current URL: {page.url}")

        # ── 4. Capture all pages ────────────────────────────────────
        for name, path in PAGES:
            try:
                print(f"\nCapturing {name}: {BASE}{path}")
                await page.goto(f"{BASE}{path}", wait_until="networkidle", timeout=20000)
                await page.wait_for_timeout(2500)
                
                # scroll to top
                await page.evaluate("window.scrollTo(0,0)")
                await page.wait_for_timeout(500)
                
                fname = os.path.join(OUT, f"live_{name}_top.png")
                await page.screenshot(path=fname, full_page=False)
                print(f"  Saved: {fname}")

                # scroll down half page
                await page.evaluate("window.scrollBy(0, 650)")
                await page.wait_for_timeout(600)
                fname2 = os.path.join(OUT, f"live_{name}_mid.png")
                await page.screenshot(path=fname2, full_page=False)
                print(f"  Saved: {fname2}")

            except Exception as e:
                print(f"  ERROR on {name}: {e}")
                await page.screenshot(path=os.path.join(OUT, f"live_{name}_error.png"))

        await browser.close()
        print("\n✅ All screenshots done!")

asyncio.run(capture())
