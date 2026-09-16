import asyncio
import os
from playwright.async_api import async_playwright

OUT = r"d:\testllm\Invoice-LLM-SOLO-Dev\Prod_Invoice_LLM\docs\product_catalog"
EMAIL = "mbirla@infinevocloud.com"
PASSWORD = "Newpassword#2815"
BASE = "https://invoicellm.admsofttech.com"

async def test_login():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await ctx.new_page()
        
        print("1. Going to dashboard to trigger auth redirect...")
        await page.goto(f"{BASE}/dashboard", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        print(f"Current URL: {page.url}")
        
        # Look for email input
        print("2. Filling email and pressing Enter...")
        email_input = page.locator('input[type="email"], input[name="identifier"], #identifier-field')
        await email_input.first.fill(EMAIL)
        await page.screenshot(path=os.path.join(OUT, "step_02_email.png"))
        await email_input.first.press("Enter")
        print("Pressed Enter on email")
        
        # Wait for password input to appear
        print("3. Waiting for password input...")
        pwd_input = page.locator('input[type="password"], input[name="password"], #password-field')
        await pwd_input.first.wait_for(state="visible", timeout=15000)
        print("Password input visible!")
        await pwd_input.first.fill(PASSWORD)
        await page.screenshot(path=os.path.join(OUT, "step_04_pwd.png"))
        await pwd_input.first.press("Enter")
        print("Pressed Enter on password")
        
        print("4. Waiting for redirect after login...")
        await page.wait_for_timeout(8000)
        await page.screenshot(path=os.path.join(OUT, "step_05_logged_in.png"))
        print(f"Post-login URL: {page.url}")
        print(f"Post-login Title: {await page.title()}")
        
        # If successfully redirected to dashboard or azurecontainerapps:
        if "dashboard" in page.url:
            print("SUCCESS! Authenticated to dashboard!")
            
        await browser.close()

asyncio.run(test_login())
