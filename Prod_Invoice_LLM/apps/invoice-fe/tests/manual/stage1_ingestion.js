const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push('pageerror: ' + err.message));

  await page.goto('http://localhost:3000/ingestion', { waitUntil: 'networkidle' });
  await page.screenshot({ path: path.join(__dirname, 'shots', '1_ingestion_initial.png') });

  const pdfPath = path.join(__dirname, '..', '..', 'invoice-be', 'tests', '_scratch_manual', process.argv[2] || 'ingestion_test.pdf');
  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles(pdfPath);
  await page.screenshot({ path: path.join(__dirname, 'shots', '2_file_selected.png') });

  await page.getByRole('button', { name: /Submit Ingestion Batch/i }).click();
  await page.screenshot({ path: path.join(__dirname, 'shots', '3_uploading.png') });

  // Wait for a terminal status to appear (real Azure calls, be generous)
  await page.waitForSelector('text=/Complete|Audit Required|Failed/', { timeout: 200000 });
  await page.waitForTimeout(1000); // let the row finish re-rendering
  await page.screenshot({ path: path.join(__dirname, 'shots', '4_final_status.png'), fullPage: true });

  const bodyText = await page.locator('body').innerText();
  console.log('--- PAGE TEXT SNAPSHOT ---');
  console.log(bodyText);
  console.log('--- CONSOLE ERRORS ---');
  console.log(JSON.stringify(consoleErrors, null, 2));

  await browser.close();
})().catch((e) => { console.error('SCRIPT FAILED:', e); process.exit(1); });
