const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

  await page.goto('http://localhost:3000/trainer', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  await page.getByRole('button', { name: /Existing Vendor/i }).click();
  console.log('Clicked Existing Vendor tab, waiting for Northwind Manufacturing to appear...');

  await page.waitForFunction(
    () => document.body.innerText.includes('Northwind Manufacturing'),
    undefined,
    { timeout: 60000 }
  );
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(__dirname, 'shots', '20_existing_vendor_correct_data.png'), fullPage: true });
  console.log('Confirmed: real vendor data appeared.');

  await browser.close();
})().catch((e) => { console.error('SCRIPT FAILED:', e); process.exit(1); });
