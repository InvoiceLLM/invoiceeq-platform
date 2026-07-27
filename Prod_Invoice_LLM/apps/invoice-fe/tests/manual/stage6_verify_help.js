const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push('pageerror: ' + err.message));

  await page.goto('http://localhost:3000/help', { waitUntil: 'networkidle' });
  await page.screenshot({ path: path.join(__dirname, 'shots', '21_help_overview.png'), fullPage: true });

  await page.click('text=Walkthrough: training a new vendor');
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(__dirname, 'shots', '22_help_new_vendor_topic.png'), fullPage: true });

  await page.fill('input[placeholder*="Search help"]', 'stuck');
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(__dirname, 'shots', '23_help_search_stuck.png'), fullPage: true });

  console.log('CONSOLE ERRORS:', JSON.stringify(consoleErrors, null, 2));
  await browser.close();
})().catch((e) => { console.error('SCRIPT FAILED:', e); process.exit(1); });
