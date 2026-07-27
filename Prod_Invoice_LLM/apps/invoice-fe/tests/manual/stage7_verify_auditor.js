const { chromium } = require('playwright');
const path = require('path');

const INVOICE_ID = '6887353b-4cce-4213-b719-dfa13813ebf4'; // Summit Office Supply, already at threshold

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push('pageerror: ' + err.message));

  await page.goto(`http://localhost:3000/invoices/review/${INVOICE_ID}`, { waitUntil: 'networkidle' });
  await page.screenshot({ path: path.join(__dirname, 'shots', '24_auditor_initial.png'), fullPage: true });

  // Correct the PO Number field via click-to-edit
  const poInput = page.locator('input').filter({ hasText: '' }).nth(0); // fallback selector below is more reliable
  const fields = await page.locator('label:has-text("PO Number") + input').first();
  await fields.click();
  await fields.fill('PO-CORRECTED-999');
  await page.screenshot({ path: path.join(__dirname, 'shots', '25_auditor_field_dirty.png'), fullPage: true });

  // Dismiss an alert if one exists (this is what actually saves the correction + triggers suggestion check)
  const dismissBtn = page.getByRole('button', { name: /Dismiss/i }).first();
  const hasDismiss = await dismissBtn.count();
  if (hasDismiss > 0) {
    await dismissBtn.click();
  } else {
    // No alerts to dismiss on this invoice right now - use Reject to save the correction instead
    await page.getByRole('button', { name: /Reject Invoice/i }).click();
  }
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(__dirname, 'shots', '26_auditor_after_save.png'), fullPage: true });

  const bodyText = await page.locator('body').innerText();
  const hasSuggestionBanner = bodyText.includes('Want to save this as a rule?');
  console.log('Suggestion banner shown:', hasSuggestionBanner);

  if (hasSuggestionBanner) {
    await page.getByRole('button', { name: /Open Trainer/i }).click();
    await page.waitForURL(/\/trainer\?/, { timeout: 10000 });
    console.log('Navigated to:', page.url());
    await page.waitForTimeout(3000);
    await page.screenshot({ path: path.join(__dirname, 'shots', '27_trainer_preseeded.png'), fullPage: true });
  }

  console.log('--- CONSOLE ERRORS ---');
  console.log(JSON.stringify(consoleErrors, null, 2));
  await browser.close();
})().catch((e) => { console.error('SCRIPT FAILED:', e); process.exit(1); });
