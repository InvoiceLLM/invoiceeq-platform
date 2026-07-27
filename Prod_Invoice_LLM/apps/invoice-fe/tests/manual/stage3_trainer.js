const { chromium } = require('playwright');
const path = require('path');

const shot = (n) => path.join(__dirname, 'shots', n);

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push('pageerror: ' + err.message));

  await page.goto('http://localhost:3000/trainer', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500); // let the default Global session auto-start
  await page.screenshot({ path: shot('7_trainer_initial_global.png') });

  // ─────────────────────────── NEW VENDOR ───────────────────────────
  await page.getByRole('button', { name: /New Vendor/i }).click();
  await page.waitForTimeout(500);
  const pdfPath = path.join(__dirname, '..', '..', 'invoice-be', 'tests', '_scratch_manual', 'trainer_new_vendor_test.pdf');
  await page.locator('input[type="file"]').setInputFiles(pdfPath);
  // Wait for the session to load (variables/file name should appear)
  await page.waitForFunction(() => document.body.innerText.includes('BrightPath') || document.body.innerText.toLowerCase().includes('.pdf'), undefined, { timeout: 150000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: shot('8_new_vendor_loaded.png'), fullPage: true });

  await page.fill('input[placeholder*="Teach a rule"]', 'Read the due date as DD-MM-YYYY, not MM-DD-YYYY.');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(20000); // give the LLM a moment
  await page.screenshot({ path: shot('9_new_vendor_chat.png'), fullPage: true });

  await page.getByRole('button', { name: /Commit to Template Registry/i }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: shot('10_new_vendor_commit_modal.png') });
  await page.getByRole('button', { name: /Commit to Registry/i }).click();
  await page.waitForTimeout(6000);
  await page.screenshot({ path: shot('11_new_vendor_committed.png'), fullPage: true });
  const afterNewVendorCommit = await page.locator('body').innerText();

  // ─────────────────────────── EXISTING VENDOR ───────────────────────────
  await page.getByRole('button', { name: /Existing Vendor/i }).click();
  await page.waitForTimeout(500);
  const vendorSelect = page.locator('select');
  await vendorSelect.selectOption({ label: 'Summit Office Supply' }).catch(async () => {
    // fallback: pick whatever first real option exists if label text differs
    const opts = await vendorSelect.locator('option').allTextContents();
    console.log('Available vendor options:', opts);
    await vendorSelect.selectOption({ index: 1 });
  });
  await page.waitForTimeout(6000);
  await page.screenshot({ path: shot('12_existing_vendor_loaded.png'), fullPage: true });

  await page.fill('input[placeholder*="Teach a rule"]', 'Always sum CGST and SGST into a single tax_amount field.');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(20000);
  await page.screenshot({ path: shot('13_existing_vendor_chat.png'), fullPage: true });

  await page.getByRole('button', { name: /Commit to Template Registry/i }).click();
  await page.waitForTimeout(500);
  await page.getByRole('button', { name: /Commit to Registry/i }).click();
  await page.waitForTimeout(6000);
  await page.screenshot({ path: shot('14_existing_vendor_committed.png'), fullPage: true });
  const afterExistingVendorCommit = await page.locator('body').innerText();

  // ─────────────────────────── GLOBAL ───────────────────────────
  await page.getByRole('button', { name: /Global/i }).click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: shot('15_global_loaded.png') });

  await page.fill('input[placeholder*="Teach a rule"]', 'VAT is always a tax item, applied after discount.');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(20000);
  await page.screenshot({ path: shot('16_global_chat.png'), fullPage: true });

  await page.getByRole('button', { name: /Commit to Template Registry/i }).click();
  await page.waitForTimeout(500);
  await page.getByRole('button', { name: /Commit to Registry/i }).click();
  await page.waitForTimeout(6000);
  await page.screenshot({ path: shot('17_global_committed.png'), fullPage: true });
  const afterGlobalCommit = await page.locator('body').innerText();

  // ─────────────────────────── RULE HISTORY ───────────────────────────
  await page.getByRole('button', { name: /Rule History/i }).click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: shot('18_rule_history_global.png'), fullPage: true });

  console.log('--- AFTER NEW VENDOR COMMIT (toast) ---');
  console.log(afterNewVendorCommit.split('\n').filter(l => l.trim()).slice(-8).join('\n'));
  console.log('--- AFTER EXISTING VENDOR COMMIT (toast) ---');
  console.log(afterExistingVendorCommit.split('\n').filter(l => l.trim()).slice(-8).join('\n'));
  console.log('--- AFTER GLOBAL COMMIT (toast) ---');
  console.log(afterGlobalCommit.split('\n').filter(l => l.trim()).slice(-8).join('\n'));
  console.log('--- CONSOLE ERRORS ---');
  console.log(JSON.stringify(consoleErrors, null, 2));

  await browser.close();
})().catch((e) => { console.error('SCRIPT FAILED:', e); process.exit(1); });
