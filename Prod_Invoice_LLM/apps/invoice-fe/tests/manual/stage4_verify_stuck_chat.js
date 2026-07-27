const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

  let chatResponseBody = null;
  let chatResponseStatus = null;
  page.on('response', async (res) => {
    if (res.url().includes('/chat') && res.request().method() === 'POST' && res.url().includes('/trainer/')) {
      chatResponseStatus = res.status();
      try { chatResponseBody = await res.text(); } catch (e) { chatResponseBody = 'READ_FAILED: ' + e.message; }
    }
  });

  await page.goto('http://localhost:3000/trainer', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  await page.getByRole('button', { name: /New Vendor/i }).click();
  await page.waitForTimeout(500);
  const pdfPath = path.join(__dirname, '..', '..', 'invoice-be', 'tests', '_scratch_manual', 'ingestion_test2.pdf');
  await page.locator('input[type="file"]').setInputFiles(pdfPath);
  await page.waitForFunction(
    () => document.body.innerText.toLowerCase().includes('sandbox ready'),
    undefined,
    { timeout: 150000 }
  );
  await page.waitForTimeout(1000);

  const before = Date.now();
  await page.fill('input[placeholder*="Teach a rule"]', 'Read the invoice number without leading zeros.');
  await page.click('button[type="submit"]');

  // Poll every 2s for up to 60s, logging whether the DOM still shows the loading indicator
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(2000);
    const stillRefining = await page.locator('text=/Refining rules/i').count();
    const elapsed = ((Date.now() - before) / 1000).toFixed(1);
    console.log(`t+${elapsed}s: stillShowingRefiningIndicator=${stillRefining > 0}, networkResponseArrived=${chatResponseStatus !== null}`);
    if (stillRefining === 0 && chatResponseStatus !== null) break;
  }

  console.log('--- NETWORK RESPONSE ---');
  console.log('status:', chatResponseStatus);
  console.log('body:', chatResponseBody);

  await page.screenshot({ path: path.join(__dirname, 'shots', '19_stuck_chat_check.png'), fullPage: true });

  await browser.close();
})().catch((e) => { console.error('SCRIPT FAILED:', e); process.exit(1); });
