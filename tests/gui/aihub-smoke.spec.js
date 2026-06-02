// @ts-check
// 44AU removed visible copy: Market and macro headlines are context only — not stock picks.
// 44AW: Report file paths must stay inside collapsed details only.

const { test, expect } = require('@playwright/test');

async function openMemory(page) {
  await page.locator('#memoryNavBtn').click();
  await page.locator('#memoryMainContent').waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForTimeout(1500);
}

async function openBrokers(page) {
  await page.locator('#brokersNavBtn').click();
  await page.locator('#brokersMainContent').waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForTimeout(2000);
}

async function openAiHubTab(page, dataTab) {
  await page.locator('#aiHubNavBtn').click();
  await page.locator('#aiHubWorkspace').waitFor({ state: 'visible', timeout: 10000 });
  await page.locator(`.tab[data-tab="${dataTab}"]`).click();
  await page.locator(`#tab-${dataTab}`).waitFor({ state: 'visible', timeout: 10000 });
  await page.waitForTimeout(1500);
}

test.describe('AstraEdge AI Hub smoke', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  });

  test('AstraEdge header loads', async ({ page }) => {
    await expect(page.locator('.brand-fallback, .brand-logo-wrap')).toContainText(/AstraEdge/i);
  });

  test('Memory — readable summaries, paths collapsed', async ({ page }) => {
    await openMemory(page);
    await page.waitForTimeout(3000);

    const mainHtml = await page.locator('#memoryMainContent').innerHTML({ timeout: 20000 });
    expect(mainHtml).toMatch(/Final Confidence Summary/);
    expect(mainHtml).toMatch(/Tomorrow Watchlist Summary/);
    expect(mainHtml).toMatch(/Calibration Summary/);
    expect(mainHtml).toMatch(/Canonical Market Memory Overview/);
    expect(mainHtml).toMatch(/Latest outcomes/);
    expect(mainHtml).toMatch(/Latest predictions/);

    const visibleText = await page.locator('#memoryMainContent').evaluate((el) => {
      const clone = el.cloneNode(true);
      clone.querySelectorAll('details').forEach((d) => d.remove());
      return clone.textContent || '';
    });

    expect(visibleText).not.toContain('data/final_confidence_report.json');
    expect(visibleText).not.toMatch(/Unexpected token/i);
    expect(visibleText).not.toMatch(/<!DOCTYPE/i);

    const hasSummaries = /Final Confidence Summary/.test(visibleText)
      && /Tomorrow Watchlist Summary/.test(visibleText)
      && /Calibration Summary/.test(visibleText);
    if (hasSummaries) {
      expect(visibleText).not.toContain('Market Memory dashboard unavailable');
    }

    const richOnlyFallback = await page.locator('#memoryMainContent').evaluate((el) => {
      const hasRich = !!el.querySelector('.mm-44aw-rich, .stat-big-card, .mm-table');
      const summaryLines = el.querySelectorAll('.drp-memory-summary-line').length;
      const summaryBlocks = el.querySelectorAll('.drp-memory-summary').length;
      const plainOnly = summaryBlocks > 0 && !hasRich && summaryLines >= 3;
      return { hasRich, plainOnly };
    });
    expect(richOnlyFallback.hasRich).toBeTruthy();
    expect(richOnlyFallback.plainOnly).toBeFalsy();
  });

  test('Broker — context cards, no Market-wide/Macro-wide', async ({ page }) => {
    await openBrokers(page);

    const content = await page.locator('#brokersMainContent').textContent({ timeout: 20000 }) || '';
    expect(content).not.toMatch(/Market and macro headlines are context only — not stock picks/i);
    expect(content).not.toMatch(/Market-wide/);
    expect(content).not.toMatch(/Macro-wide/);

    for (const sectionLabel of ['Market context', 'Macro context']) {
      const section = page.locator('.bi-section-subtitle').filter({ hasText: new RegExp(sectionLabel, 'i') });
      if (!(await section.count())) continue;

      const cards = section.first().locator('xpath=following-sibling::div[contains(@class,"bi-context-cards")][1]');
      if (await cards.count()) {
        expect(await cards.locator('.bi-context-card').count()).toBeGreaterThan(0);
        continue;
      }

      const table = section.first().locator('xpath=following-sibling::table[1]');
      const tickers = await table.locator('.bi-col-ticker').allTextContents().catch(() => []);
      for (const t of tickers) {
        expect(t.trim()).not.toBe('—');
        expect(t.trim()).not.toMatch(/Market-wide|Macro-wide/i);
      }
    }
  });

  test('Market — snapshot timestamps or refresh metadata', async ({ page }) => {
    await openAiHubTab(page, 'markets');
    const html = await page.locator('#tab-markets').innerHTML();
    const hasSnapshotTs = html.includes('Snapshot refreshed at');
    const hasRefreshMeta = html.includes('Refresh attempted') && html.includes('refresh_closed_market_intelligence');
    const hasStaleFlow = html.includes('Last available snapshot') || html.includes('Stale snapshot');
    expect(hasSnapshotTs || hasRefreshMeta || hasStaleFlow).toBeTruthy();
  });

  test('Scan — live, watchlist, memory sections', async ({ page }) => {
    await openAiHubTab(page, 'scanner');
    const html = await page.locator('#tab-scanner').innerHTML({ timeout: 15000 });
    expect(html).toMatch(/Live Scanner \/ ULTRA Moves/);
    expect(html).toMatch(/Watchlist Candidates/);
    expect(html).toMatch(/Memory Signals/);

    const text = await page.locator('#tab-scanner').textContent({ timeout: 15000 });
    if (text && text.includes('Memory signal')) {
      expect(text).not.toMatch(/Rs\.0\b/);
    }
  });

  test('Calib — no raw JSON rec strings', async ({ page }) => {
    await openAiHubTab(page, 'stats');
    const html = await page.locator('#tab-stats').innerHTML({ timeout: 15000 });
    expect(html).not.toMatch(/\{"bucket":/);
    expect(html).not.toMatch(/calib-insufficient.*\{.*"type"/);
  });

  test('Journal — no duplicate RELIANCE in top watch', async ({ page }) => {
    await openAiHubTab(page, 'history');
    const watchBlock = page.locator('#tab-history h2').filter({ hasText: /Top Watch/i }).first();
    if (await watchBlock.count()) {
      const card = watchBlock.locator('xpath=ancestor::div[contains(@class,"glass-card")][1]');
      const lines = await card.locator('.journal-runtime-line').allTextContents().catch(() => []);
      const relianceCount = lines.filter((l) => /\bRELIANCE\b/i.test(l)).length;
      expect(relianceCount).toBeLessThanOrEqual(1);
    }
  });
});
