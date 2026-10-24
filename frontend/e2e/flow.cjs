// Browser flow against a running stack: FAKE_LLM=1 uvicorn on :8000 + `npm run start` on :3000.
// Run: cd frontend && node e2e/flow.cjs   (needs playwright; screenshots go to e2e/shots)
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const out = process.env.SHOTS_DIR || './e2e/shots';
  require('fs').mkdirSync(out, { recursive: true });
  for (const [name, scheme, vp] of [['desktop-light','light',{width:1440,height:900}],['mobile-dark','dark',{width:390,height:844}]]) {
    const ctx = await browser.newContext({ viewport: vp, colorScheme: scheme });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    page.on('console', m => { if (m.type()==='error') errors.push(m.text()); });
    await page.goto('http://localhost:3000/');
    await page.getByRole('button', { name: 'Backend' }).click();
    await page.screenshot({ path: `${out}/${name}-1-level.png` });
    await page.getByRole('button', { name: 'SDE-2/3' }).click();
    await page.getByRole('searchbox').fill('ama');
    await page.getByRole('button', { name: 'Amazon' }).click();
    await page.getByRole('button', { name: 'Start' }).waitFor();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${out}/${name}-2-topic.png` });
    await page.getByRole('searchbox').fill('kaf');
    await page.getByRole('button', { name: 'Kafka' }).click();
    await page.getByRole('button', { name: 'Start' }).click();
    await page.waitForURL(/\/interview\//);
    await page.getByRole('button', { name: 'Hold to answer' }).waitFor();
    await page.screenshot({ path: `${out}/${name}-3-interview.png` });
    const strong = 'I would shard by tenant, add a write-through cache, and monitor replication lag and failure modes carefully.';
    for (let i = 0; i < 12; i++) {
      if (page.url().includes('/report/')) break;
      await page.getByRole('button', { name: 'More' }).click();
      if (i === 0) await page.screenshot({ path: `${out}/${name}-4-menu.png` });
      await page.getByRole('textbox', { name: 'Type your answer' }).fill(i === 0 ? 'dunno' : strong);
      await page.getByRole('button', { name: 'Send' }).click();
      await page.waitForTimeout(500);
    }
    await page.waitForURL(/\/report\//, { timeout: 15000 });
    await page.getByText('Practice again').waitFor();
    await page.screenshot({ path: `${out}/${name}-5-report.png`, fullPage: true });
    console.log(name, 'OK', page.url(), 'errors:', JSON.stringify(errors));
    await ctx.close();
  }
  await browser.close();
})().catch(e => { console.error('FAIL', e); process.exit(1); });
