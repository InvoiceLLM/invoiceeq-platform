const { chromium } = require('playwright');
const path = require('path');
const INVOICE_ID = '6887353b-4cce-4213-b719-dfa13813ebf4';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push('pageerror: ' + err.message));

  await page.goto(`http://localhost:3000/invoices/review/${INVOICE_ID}`, { waitUntil: 'networkidle' });

  const taxField = page.locator('label:has-text("Tax Amount") + input').first();
  await taxField.click();
  await taxField.fill('1500.00');
  await page.screenshot({ path: path.join(__dirname, 'shots', '25_auditor_field_dirty.png'), fullPage: true });

  const dismissBtn = page.getByRole('button', { name: /Dismiss/i }).first();
  if (await dismissBtn.count() > 0) {
    await dismissBtn.click();
  } else {
    await page.getByRole('button', { name: /Reject Invoice/i }).click();
  }
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(__dirname, 'shots', '26_auditor_after_save.png'), fullPage: true });

  const bodyText = await page.locator('body').innerText();
  console.log('Suggestion banner shown:', bodyText.includes('Want to save this as a rule?'));

  if (bodyText.includes('Want to save this as a rule?')) {
    await page.getByRole('button', { name: /Open Trainer/i }).click();
    await page.waitForURL(/\/trainer\?/, { timeout: 10000 });
    console.log('Navigated to:', page.url());
    await page.waitForTimeout(3000);
    await page.screenshot({ path: path.join(__dirname, 'shots', '27_trainer_preseeded.png'), fullPage: true });
  }

  console.log('--- CONSOLE ERRORS ---', JSON.stringify(consoleErrors));
  await browser.close();
})().catch((e) => { console.error('SCRIPT FAILED:', e); process.exit(1); });
