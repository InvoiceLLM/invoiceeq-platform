const { chromium } = require('playwright');
const path = require('path');

const QUESTIONS = [
  'Who is the vendor on invoice US-99003-001?',
  'What is the grand total for that invoice?',
  'Is that invoice flagged for audit?',
];

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push('pageerror: ' + err.message));

  await page.goto('http://localhost:3000/chat', { waitUntil: 'networkidle' });
  await page.screenshot({ path: path.join(__dirname, 'shots', '5_chat_initial.png') });

  // Start a new chat session (button text is "New Chat" or "Start New Chat" depending on empty state)
  const newChatBtn = page.getByRole('button', { name: /New Chat/i }).first();
  await newChatBtn.click();
  await page.waitForSelector('#chat-input-textarea:not([disabled])', { timeout: 15000 });

  for (let i = 0; i < QUESTIONS.length; i++) {
    const q = QUESTIONS[i];
    await page.fill('#chat-input-textarea', q);
    await page.click('#chat-send-btn');
    // Wait for the send button to become disabled (sending) then re-enabled (response landed)
    await page.waitForFunction(() => {
      const btn = document.querySelector('#chat-send-btn');
      const ta = document.querySelector('#chat-input-textarea');
      return btn && ta && !ta.disabled && !btn.disabled === false ? true : (ta && ta.value === '');
    }, { timeout: 60000 }).catch(() => {});
    // Simpler robust wait: poll until textarea is empty AND not disabled AND no spinner
    await page.waitForFunction(() => {
      const ta = document.querySelector('#chat-input-textarea');
      const spinner = document.querySelector('.animate-spin');
      return ta && ta.value === '' && !ta.disabled;
    }, { timeout: 60000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(__dirname, 'shots', `6_chat_q${i + 1}.png`), fullPage: true });
  }

  const bodyText = await page.locator('body').innerText();
  console.log('--- PAGE TEXT SNAPSHOT ---');
  console.log(bodyText);
  console.log('--- CONSOLE ERRORS ---');
  console.log(JSON.stringify(consoleErrors, null, 2));

  await browser.close();
})().catch((e) => { console.error('SCRIPT FAILED:', e); process.exit(1); });
