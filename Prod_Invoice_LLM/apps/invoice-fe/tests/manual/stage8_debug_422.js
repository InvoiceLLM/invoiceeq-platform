const { chromium } = require('playwright');
const INVOICE_ID = '6887353b-4cce-4213-b719-dfa13813ebf4';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();

  page.on('request', (req) => {
    if (req.url().includes('/audit/resolve/') && req.method() === 'PUT') {
      console.log('REQUEST BODY:', req.postData());
    }
  });
  page.on('response', async (res) => {
    if (res.url().includes('/audit/resolve/') && res.request().method() === 'PUT') {
      console.log('RESPONSE STATUS:', res.status());
      console.log('RESPONSE BODY:', await res.text());
    }
  });

  await page.goto(`http://localhost:3000/invoices/review/${INVOICE_ID}`, { waitUntil: 'networkidle' });

  const poField = page.locator('label:has-text("PO Number") + input').first();
  await poField.click();
  await poField.fill('PO-DEBUG-1');

  const dismissBtn = page.getByRole('button', { name: /Dismiss/i }).first();
  if (await dismissBtn.count() > 0) {
    await dismissBtn.click();
  } else {
    await page.getByRole('button', { name: /Reject Invoice/i }).click();
  }
  await page.waitForTimeout(2000);

  await browser.close();
})().catch((e) => { console.error('SCRIPT FAILED:', e); process.exit(1); });
