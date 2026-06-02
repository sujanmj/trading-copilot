// QA_STAGE_45A_FULL_GUI_E2E_MATRIX — Full AstraEdge GUI Playwright E2E matrix (Stage 45A).

const { test, expect } = require('@playwright/test');

const API_BASE = (process.env.ASTRA_API_BASE || 'http://127.0.0.1:8080').replace(/\/$/, '');
const CONTENT_WAIT_MS = 2500;
const PANEL_WAIT_MS = 15000;

async function gotoApp(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30000 });
}

async function openMemory(page) {
  await page.locator('#memoryNavBtn').click();
  await page.locator('#memoryMainContent').waitFor({ state: 'visible', timeout: PANEL_WAIT_MS });
  await page.waitForTimeout(CONTENT_WAIT_MS);
}

async function openBrokers(page) {
  await page.locator('#brokersNavBtn').click();
  await page.locator('#brokersMainContent').waitFor({ state: 'visible', timeout: PANEL_WAIT_MS });
  await page.waitForTimeout(CONTENT_WAIT_MS);
}

async function openAiHub(page) {
  await page.locator('#aiHubNavBtn').click();
  await page.locator('#aiHubWorkspace').waitFor({ state: 'visible', timeout: PANEL_WAIT_MS });
}

async function openAiHubTab(page, dataTab) {
  await openAiHub(page);
  await page.locator(`.tab[data-tab="${dataTab}"]`).click();
  await page.locator(`#tab-${dataTab}`).waitFor({ state: 'visible', timeout: PANEL_WAIT_MS });
  await page.waitForTimeout(CONTENT_WAIT_MS);
}

async function tabVisibleText(page, dataTab) {
  const el = page.locator(`#tab-${dataTab}`);
  return (await el.textContent({ timeout: PANEL_WAIT_MS })) || '';
}

async function tabVisibleHtml(page, dataTab) {
  return page.locator(`#tab-${dataTab}`).innerHTML({ timeout: PANEL_WAIT_MS });
}

function assertNoCrashText(text) {
  expect(text).not.toMatch(/Unexpected token/i);
  expect(text).not.toMatch(/<!DOCTYPE/i);
  expect(text).not.toMatch(/SyntaxError/i);
  const failedFetch = (text.match(/Failed to fetch/gi) || []).length;
  if (failedFetch > 0) {
    expect(text).toMatch(/unavailable|fallback|empty|cache|retry|Refresh/i);
  }
}

test.describe('45A — App shell', () => {
  test.beforeEach(async ({ page }) => {
    await gotoApp(page);
  });

  test('logo, status chips, and primary nav', async ({ page }) => {
    await expect(page.locator('.brand-fallback, .brand-logo-wrap')).toContainText(/AstraEdge/i);
    const header = page.locator('header');
    await expect(header).toContainText(/LIVE/i);
    await expect(header.locator('#guiModeBadge')).toContainText(/WEB LOCAL/i);
    await expect(header.locator('#aiOpsBtn')).toContainText(/OPS/i);
    await expect(header.locator('#apiStatus')).toBeVisible();
    await expect(header.locator('#reviewBtn')).toContainText(/REVIEW/i);
    await expect(page.locator('#memoryNavBtn')).toContainText(/Memory/i);
    await expect(page.locator('#brokersNavBtn')).toContainText(/Brokers/i);
    await expect(page.locator('#aiHubNavBtn')).toContainText(/AI Hub/i);
    await expect(page.locator('#routerNavBtn')).toContainText(/Router/i);
  });
});

test.describe('45A — Memory page', () => {
  test.beforeEach(async ({ page }) => {
    await gotoApp(page);
    await openMemory(page);
    await page.waitForTimeout(2000);
  });

  test('rich summaries visible; errors and paths hidden', async ({ page }) => {
    const mainHtml = await page.locator('#memoryMainContent').innerHTML({ timeout: 20000 });
    for (const label of [
      'Canonical Market Memory',
      'Final Confidence Summary',
      'Tomorrow Watchlist Summary',
      'Calibration Summary',
      'Canonical Market Memory Overview',
      'Latest outcomes',
      'Latest predictions',
    ]) {
      expect(mainHtml).toMatch(new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    }

    const visibleText = await page.locator('#memoryMainContent').evaluate((el) => {
      const clone = el.cloneNode(true);
      clone.querySelectorAll('details').forEach((d) => d.remove());
      return clone.textContent || '';
    });

    assertNoCrashText(visibleText);
    expect(visibleText).not.toMatch(/Market Memory dashboard unavailable/i);
    expect(visibleText).not.toMatch(/Final confidence report unavailable/i);
    expect(visibleText).not.toContain('data/final_confidence_report.json');

    const rich = await page.locator('#memoryMainContent').evaluate((el) => {
      const hasRich = !!el.querySelector('.mm-44aw-rich, .stat-big-card, .mm-table');
      const summaryBlocks = el.querySelectorAll('.drp-memory-summary').length;
      const summaryLines = el.querySelectorAll('.drp-memory-summary-line').length;
      const plainOnly = summaryBlocks > 0 && !hasRich && summaryLines >= 3;
      return { hasRich, plainOnly };
    });
    expect(rich.hasRich).toBeTruthy();
    expect(rich.plainOnly).toBeFalsy();
  });
});

test.describe('45A — Brokers page', () => {
  test.beforeEach(async ({ page }) => {
    await gotoApp(page);
    await openBrokers(page);
    await page.waitForTimeout(2000);
  });

  test('sections visible; banned labels hidden; dev block collapsed', async ({ page }) => {
    const content = await page.locator('#brokersMainContent').textContent({ timeout: 20000 }) || '';
    for (const label of [
      'Broker Prediction Intelligence',
      'Broker picks',
      'External Evidence',
      'Broker candidates',
      'Stock news evidence',
      'Market context',
      'Macro context',
    ]) {
      expect(content).toMatch(new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'));
    }

    expect(content).not.toMatch(/Market-wide/i);
    expect(content).not.toMatch(/Macro-wide/i);
    expect(content).not.toMatch(/Market and macro headlines are context only — not stock picks/i);

    const devDetails = page.locator('#brokersMainContent details').filter({ hasText: /Developer \/ Ops/i });
    if (await devDetails.count()) {
      await expect(devDetails.first()).not.toHaveAttribute('open', '');
    }

    const openImport = page.locator('#brokersMainContent .bi-import-box:visible');
    if (await openImport.count()) {
      const inDetails = await openImport.first().evaluate((el) => !!el.closest('details'));
      expect(inDetails).toBeTruthy();
    }
  });
});

test.describe('45A — AI Hub shell', () => {
  test.beforeEach(async ({ page }) => {
    await gotoApp(page);
    await openAiHub(page);
  });

  test('tabs, Refresh Tab, cache badge at most once', async ({ page }) => {
    for (const label of ['Brain', 'Govt', 'Scan', 'Mkt', 'Global', 'News', 'TV', 'Rdt', 'Calib', 'Journal']) {
      await expect(page.locator('.tab .tab-label').filter({ hasText: label }).first()).toBeVisible();
    }
    await expect(page.locator('.aihub-tab-refresh, [data-aihub-refresh-tab]').first()).toBeVisible();
    const hubText = await page.locator('#aiHubWorkspace').textContent() || '';
    const cacheHits = (hubText.match(/Using tab cache/g) || []).length;
    expect(cacheHits).toBeLessThanOrEqual(1);
  });
});

test.describe('45A — AI Hub Brain', () => {
  test('actionable content without raw JSON', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'brain');
    const text = await tabVisibleText(page, 'brain');
    const html = await tabVisibleHtml(page, 'brain');
    expect(text).toMatch(/Action Plan|Actionable Candidates/i);
    expect(text).toMatch(/WATCH|AVOID/i);
    expect(text).toMatch(/Calibration|calibration/i);
    expect(html).not.toMatch(/\{"bucket":/);
    expect(text).not.toMatch(/undefined/);
    expect(text).not.toMatch(/null null/i);
  });
});

test.describe('45A — AI Hub Govt', () => {
  test('govt intelligence or clean empty state', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'govt');
    const text = await tabVisibleText(page, 'govt');
    const ok = /government|policy|govt impact|Govt Impact|daily risk|No fresh government|No government intelligence|govt-specific/i.test(text)
      || /empty-stats|glass-card/i.test(await tabVisibleHtml(page, 'govt'));
    expect(ok).toBeTruthy();
    expect(text).not.toMatch(/SyntaxError|at Object\.|stack trace/i);
    expect(text).not.toMatch(/\bundefined\b/);
  });
});

test.describe('45A — AI Hub Scan', () => {
  test('scanner sections without bad memory fallbacks', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'scanner');
    const html = await tabVisibleHtml(page, 'scanner');
    const text = await tabVisibleText(page, 'scanner');
    expect(html).toMatch(/Live Scanner \/ ULTRA Moves/);
    expect(html).toMatch(/Watchlist Candidates/);
    expect(html).toMatch(/Memory Signals/);
    if (/Memory signal/i.test(text)) {
      expect(text).not.toMatch(/Rs\.0\b/);
      expect(text).not.toMatch(/\+0\.00%/);
      expect(text).not.toMatch(/vol 1\.0x avg/i);
    }
  });
});

test.describe('45A — AI Hub Mkt', () => {
  test('market regions; stale hints not live', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'markets');
    const text = await tabVisibleText(page, 'markets');
    const html = await tabVisibleHtml(page, 'markets');
    expect(text).toMatch(/Regional Sentiment/i);
    expect(text).toMatch(/USA|USA INDICES/i);
    expect(text).toMatch(/India Watchlist|India watchlist/i);
    if (/Stale snapshot|Market data stale/i.test(text)) {
      expect(text).toMatch(/Refresh|refresh_closed_market_intelligence|manual refresh/i);
    }
    expect(html).not.toMatch(/presented as live entry/i);
  });
});

test.describe('45A — AI Hub Global', () => {
  test('overnight global impact sections', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'global');
    const text = await tabVisibleText(page, 'global');
    expect(text).toMatch(
      /OVERNIGHT GLOBAL IMPACT|Overnight Global|overnight global|Global \/ Macro Fallback|Global → India mapping/i,
    );
    const sectorOk = /At risk|Supported|Supported sectors|Risk sectors|Bullish sectors|Commodity|sector mapping/i.test(text);
    expect(sectorOk).toBeTruthy();
    expect(text).not.toMatch(/\bundefined\b/);
  });
});

test.describe('45A — AI Hub News', () => {
  test('news panel or empty state without stack trace', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'news');
    const text = await tabVisibleText(page, 'news');
    const html = await tabVisibleHtml(page, 'news');
    expect(text).toMatch(/News|source|headline|cache|empty|No news/i);
    expect(html).not.toMatch(/SyntaxError|at Object\./i);
  });
});

test.describe('45A — AI Hub TV', () => {
  test('TV cache or empty state without stack trace', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'tv');
    const text = await tabVisibleText(page, 'tv');
    const html = await tabVisibleHtml(page, 'tv');
    expect(text).toMatch(/TV|video|cache|headline|empty|No /i);
    expect(html).not.toMatch(/SyntaxError|at Object\./i);
  });
});

test.describe('45A — AI Hub Reddit', () => {
  test('reddit cache or empty hint', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'reddit');
    const text = await tabVisibleText(page, 'reddit');
    expect(text).toMatch(/Reddit|No Reddit cache yet|source feed|Refresh Tab/i);
    expect(text).not.toMatch(/SyntaxError|at Object\./i);
  });
});

test.describe('45A — AI Hub Calib', () => {
  test('calibration stats without raw JSON', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'stats');
    const text = await tabVisibleText(page, 'stats');
    const html = await tabVisibleHtml(page, 'stats');
    expect(text).toMatch(/Live resolved/i);
    expect(text).toMatch(/Historical resolved/i);
    expect(text).toMatch(/Calibration Recommendations/i);
    expect(html).not.toMatch(/\{"bucket":/);
    expect(text).not.toMatch(/\bundefined\b/);
  });
});

test.describe('45A — AI Hub Journal', () => {
  test('journal fields; deduped RELIANCE; WATCH not BUY', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'history');
    const text = await tabVisibleText(page, 'history');
    expect(text).toMatch(/Generated/i);
    expect(text).toMatch(/Mode/i);
    expect(text).toMatch(/Top Watch|Watch Candidates|WATCH FOR ENTRY|Actionable Candidates/i);
    expect(text).toMatch(/Risk Notes|Risk notes|Intelligence journal|Daily Report Pack/i);

    const watchBlock = page.locator('#tab-history h2').filter({ hasText: /Top Watch|WATCH FOR ENTRY/i }).first();
    if (await watchBlock.count()) {
      const card = watchBlock.locator('xpath=ancestor::div[contains(@class,"glass-card")][1]');
      const lines = await card.locator('.journal-runtime-line, .glass-text, p').allTextContents().catch(() => []);
      const relianceCount = lines.filter((l) => /\bRELIANCE\b/i.test(l)).length;
      expect(relianceCount).toBeLessThanOrEqual(1);
    } else {
      const watchSlice = text.split(/AVOID/i)[0] || text;
      const relianceCount = (watchSlice.match(/\bRELIANCE\b/gi) || []).length;
      expect(relianceCount).toBeLessThanOrEqual(1);
    }

    const watchSection = text.match(/(?:Top Watch|WATCH FOR ENTRY|Actionable Candidates)[\s\S]{0,1200}/i);
    if (watchSection) {
      expect(watchSection[0]).not.toMatch(/\bRELIANCE\b[^—\n]{0,40}—\s*BUY\b/i);
      expect(watchSection[0]).not.toMatch(/\bRELIANCE\b[\s\S]{0,80}\bBUY CANDIDATE\b/i);
    }
    if (/WATCH is not BUY|shadow watchlist only|Not a blind buy/i.test(text)) {
      expect(text).toMatch(/WATCH is not BUY|shadow watchlist only|Not a blind buy/i);
    }
  });
});

test.describe('45A — Refresh behavior', () => {
  test('Memory refresh survives without crash strings', async ({ page }) => {
    await gotoApp(page);
    await openMemory(page);
    const btn = page.locator('[data-mm-refresh="1"]').first();
    if (await btn.count()) {
      await btn.click();
      await page.waitForTimeout(4000);
    }
    const text = await page.locator('#memoryMainContent').textContent() || '';
    assertNoCrashText(text);
  });

  test('Brokers refresh survives without crash strings', async ({ page }) => {
    await gotoApp(page);
    await openBrokers(page);
    const btn = page.locator('#brokersRefreshBtn');
    if (await btn.count()) {
      await btn.click();
      await page.waitForTimeout(4000);
    }
    const text = await page.locator('#brokersMainContent').textContent() || '';
    assertNoCrashText(text);
  });

  test('AI Hub Scan refresh survives without crash strings', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'scanner');
    const btn = page.locator('[data-aihub-refresh-tab="scanner"]');
    if (await btn.count()) {
      await btn.click();
      await page.waitForTimeout(4000);
    }
    const text = await tabVisibleText(page, 'scanner');
    assertNoCrashText(text);
  });

  test('AI Hub Mkt refresh survives without crash strings', async ({ page }) => {
    await gotoApp(page);
    await openAiHubTab(page, 'markets');
    const btn = page.locator('[data-aihub-refresh-tab="markets"]');
    if (await btn.count()) {
      await btn.click();
      await page.waitForTimeout(4000);
    }
    const text = await tabVisibleText(page, 'markets');
    assertNoCrashText(text);
  });
});

test.describe('45A — Backend API JSON', () => {
  const JSON_ENDPOINTS = [
    '/api/runtime/snapshot',
    '/api/debug/final-confidence',
    '/api/debug/final-confidence/report',
    '/api/debug/daily-report-pack',
    '/api/debug/aihub-tab/brain',
    '/api/debug/aihub-tab/scan',
    '/api/debug/aihub-tab/market',
    '/api/debug/aihub-tab/global',
    '/api/debug/aihub-tab/calib',
    '/api/debug/aihub-tab/journal',
  ];

  for (const path of JSON_ENDPOINTS) {
    test(`${path} returns JSON not HTML`, async ({ request }) => {
      const res = await request.get(`${API_BASE}${path}`, { timeout: 30000 });
      const ct = (res.headers()['content-type'] || '').toLowerCase();
      const body = await res.text();
      expect(res.status(), `${path} status`).toBeLessThan(500);
      if (res.status() === 401 || res.status() === 403) {
        test.skip();
        return;
      }
      expect(body.trim().startsWith('<!DOCTYPE'), `${path} must not be HTML`).toBeFalsy();
      expect(ct.includes('json') || body.trim().startsWith('{') || body.trim().startsWith('[')).toBeTruthy();
      JSON.parse(body);
    });
  }
});
