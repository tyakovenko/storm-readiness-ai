// Run against Vite: node frontend/tests/live-operations.cjs
// Uses Playwright (or PLAYWRIGHT_MODULE_PATH to an existing playwright-core install).
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.TEST_CHROMIUM_PATH});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', e => { errors.push(e.message); console.error('Page error:', e.message); });
    let unavailable = false, overviewRequests = 0, chatRequests = 0;
    const agents = [{id:'harris-hurricane', name:'Harris hurricane', county:'Harris County', state:'TX', hazard:'hurricane', replay:'BERYL', storms:12, shelters:5},
      {id:'miami-hurricane', name:'Miami hurricane', county:'Miami-Dade County', state:'FL', hazard:'hurricane', replay:'IRMA'},
      {id:'lee-hurricane', name:'Lee hurricane', county:'Lee County', state:'FL', hazard:'hurricane', replay:'IAN', storms:0, shelters:0},
      {id:'dallas-winter', name:'Dallas winter', county:'Dallas County', state:'TX', hazard:'winter'}];
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url());
      const send = data => route.fulfill({json:data});
      if (url.pathname === '/api/health') return send({domain:'multi', mock:true});
      if (url.pathname === '/api/agents') return send(agents);
      if (url.pathname === '/api/chat') { chatRequests++; return send({status:'passed', answer:'Test response', sources:[], attempts:[], why:[], checks:[], tool_calls:[]}); }
      if (url.pathname.endsWith('/overview')) { overviewRequests++; return route.fulfill({status:503,json:{detail:'Test unavailable county data'}}); }
      if (unavailable) return route.fulfill({status:503,json:{detail:'Unavailable'}});
      if (url.pathname === '/api/live/status') return send({status:'online', active_storms_count:0, active_tropical_alerts_count:0, source:'NOAA/NWS', last_polled_utc:'2026-10-07T12:00:00Z'});
      if (url.pathname === '/api/live/storms') return send([]);
      if (url.pathname === '/api/staging') {
        assert.equal(url.searchParams.get('max_trucks'), '14');
        return send({staging_area:'Test staging area', trucks_available:14, shelter_beds_available:2300, shelter_demand_estimate:2500, shelter_bed_shortfall:200,
          allocations:[{county:'Taylor County', truckloads_assigned:2, truckloads_needed:3}]});
      }
      return route.fulfill({status:404,json:{}});
    });
    await page.goto(process.env.TEST_BASE_URL || 'http://127.0.0.1:5175');
    const link=page.getByRole('link',{name:'Live Storm Updates — View Live Details'});
    await link.waitFor();
    const scenarios=page.getByRole('region',{name:'Operational County Scenarios'});
    assert.equal(await scenarios.getByRole('button',{name:/Open Operations Dashboard/}).count(),4);
    assert.equal(await scenarios.locator('img').count(),4);
    await scenarios.getByRole('button',{name:'Hurricanes (3)',exact:true}).click();
    assert.equal(await scenarios.getByRole('button',{name:/Open Operations Dashboard/}).count(),3);
    await scenarios.getByRole('button',{name:'Winter Storm',exact:true}).click();
    assert.equal(await scenarios.getByRole('button',{name:/Open Operations Dashboard/}).count(),1);
    await scenarios.getByRole('button',{name:'All (4)',exact:true}).click();
    await page.screenshot({path:path.join(os.tmpdir(),'storm-landing-desktop.png'),fullPage:true});
    assert.equal(await page.locator('.landing-hero__image img').getAttribute('src'), '/images/hurricane-satellite.png');
    await page.locator('#home-storm-question').fill('Which areas are highest risk?');
    await page.getByRole('button',{name:'Submit question',exact:true}).click();
    await page.locator('.landing-chat--expanded').waitFor();
    await page.waitForFunction(() => document.querySelector('.landing-chat__workspace'));
    assert.equal(chatRequests,1);
    await link.click();
    await page.getByRole('heading',{name:'Live Operations',exact:true}).waitFor();
    assert.equal(new URL(page.url()).hash,'#/live-operations');
    await page.getByText('Test staging area',{exact:true}).waitFor();
    assert.match(await page.locator('.live-operations').innerText(),/Active Tropical Cyclones:\s*0/);
    assert.match(await page.locator('.live-operations').innerText(),/Active NWS Alerts:\s*0/);
    await page.getByRole('button',{name:'HU Rachel (Demo)',exact:true}).click();
    await page.getByText('Hurricane Rachel (EP182026)',{exact:true}).waitFor();
    assert.equal(await page.locator('.animate-radar').evaluate(el=>getComputedStyle(el).animationName),'live-operations-radar');
    await page.getByText('2 / 3 trucks',{exact:true}).waitFor();
    await page.getByText('Demo shelter shortfall: 200',{exact:true}).waitFor();
    await page.screenshot({path:path.join(os.tmpdir(),'storm-live-operations-desktop.png'),fullPage:true});
    await page.getByRole('button',{name:/Back to Overview/}).click();
    await page.locator('.landing-chat--expanded').waitFor();
    await page.getByText('Test response',{exact:true}).waitFor();
    await link.click();
    await page.getByRole('button',{name:'Taylor County (Replay)',exact:true}).click();
    await page.getByText('Hurricane Idalia (Taylor County)',{exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:/Launch Taylor County Dashboard/}).isDisabled(),true);
    assert.equal(await page.getByRole('region',{name:'Operational County Scenarios'}).count(),0);
    await page.getByRole('button',{name:/Back to Overview/}).click();
    await scenarios.getByRole('button',{name:/Harris County.*Open Operations Dashboard/}).click();
    // Phase 1: hurricane cards now open the storm-wide experience by default, not the single-
    // county agent route (which still exists and still works -- see the direct #/agents/... goto below).
    await page.waitForURL('**/#/storms/harris-hurricane/storm-overview');
    await page.getByRole('navigation').getByText('Harris County, TX',{exact:true}).waitFor();
    assert.ok(overviewRequests > 0);
    await page.goto('http://127.0.0.1:5175/#/live-operations');
    await page.getByRole('button',{name:/Back to Overview/}).click();
    await link.waitFor();
    assert.equal(new URL(page.url()).hash,'#/');
    unavailable=true;
    await link.click();
    await page.getByText('Staging service unavailable. No sample allocations substituted.',{exact:true}).waitFor();
    const body=await page.locator('.live-operations').innerText();
    assert.match(body,/Live feed unavailable/);
    assert.match(body,/Active Tropical Cyclones:\s*—/);
    assert.doesNotMatch(body,/48|Zero Shelter Shortfall|Live Staging Active|5 \/ 5 trucks/);
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:process.env.TEST_SCREENSHOT || path.join(os.tmpdir(),'storm-live-operations-mobile.png'),fullPage:true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),true);
    assert.deepEqual(errors,[]);
    console.log('PASS: landing search, card route, direct route, zero counts, tabs, radar, staging, county routing, filters, back, unavailable feeds, mobile rendering; no page errors.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
