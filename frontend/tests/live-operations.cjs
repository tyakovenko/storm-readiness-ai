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
      if (url.pathname === '/api/live/storms') return send([
        {storm_id:'AL092026', name:'Isaias', classification:'HU', intensity_kt:105, pressure_mb:959, lat:29.0, lon:-87.1, movement_dir_deg:10, movement_speed_mph:17, last_update_utc:'2026-10-09T20:00:00Z', advisory_num:'012a'},
        {storm_id:'EP182026', name:'Rachel', classification:'TS', intensity_kt:45, pressure_mb:994, lat:23.1, lon:-124.5, movement_dir_deg:55, movement_speed_mph:5, last_update_utc:'2026-10-09T18:00:00Z'}]);
      if (url.pathname === '/api/live/storms/AL092026/track') return send({storm_id:'AL092026', cycle_utc:'2026-10-09T12:00:00+00:00', source:'NHC',
        points:[{tau_h:12, valid_utc:'2026-10-10T00:00:00+00:00', lat:29.7, lon:-86.8, vmax_kt:100}, {tau_h:24, valid_utc:'2026-10-10T12:00:00+00:00', lat:32.1, lon:-87.1, vmax_kt:55}]});
      if (url.pathname === '/api/live/storms/EP182026/track') return route.fulfill({status:503,json:{detail:'no track'}});
      if (url.pathname === '/api/live/storms/AL092026/risk') return send({storm_id:'AL092026', storm_name:'Isaias', forecast_cycle_utc:'2026-10-09T18:00:00+00:00',
        risk_radius_nm:120, counties_evaluated:5, skipped:[], caveats:[], assumptions:['ASSUMPTION: 1 utility truck per 2,000 predicted customers out.'],
        sources:['Test source'], model_source:'Test model', trucks_needed_total:{low:20, median:38, high:70},
        staging:{fips:'12073', name:'Leon County, FL staging area', county:'Leon County', state:'FL', lat:30.46, lon:-84.28, clearance_from_track_nm:136, avg_distance_to_counties_nm:110, method:'Test method'},
        counties:[{fips:'01003', name:'Baldwin County', state:'AL', lat:30.66, lon:-87.75, risk_tier:'orange', pct_customers_out:{low:20, median:38.9, high:60},
          customers_served:195253, customers_out:{low:39000, median:75953, high:117000}, why:['Strong winds'], distance_to_track_nm:48,
          closest_forecast_utc:'2026-10-10T06:00:00+00:00', forecast_wind_kt_at_closest:75, trucks_needed:{low:20, median:38, high:59},
          shelters:{count:15, evacuation_capacity:4846, with_generator:6, in_surge_zone:2, top:[{name:'Test Shelter', city:'Foley', evacuation_capacity:900, generator:true, in_surge_zone:false, lat:30.4, lon:-87.7}]},
          hospitals:{count:4, with_emergency_dept:4, top:[{name:'Baldwin Health', city:'Foley', type:'Acute Care Hospitals', emergency_services:true}]},
          fire:{departments:26, stations:49, career_firefighters:229, volunteer_firefighters:567, paid_per_call_firefighters:0, top:[]},
          history:{storms_with_outages:6, worst:[{storm:'Sally', year:2020, peak_customers_out:126286, pct_customers_out:80.1}], fema_declarations:23, recent_declarations:[{title:'Hurricane Sally', year:'2020'}]},
          pack_slug:null}]});
      if (url.pathname === '/api/live/storms/EP182026/risk') return send({storm_id:'EP182026', storm_name:'Rachel', counties:[], staging:null, skipped:[], caveats:[], assumptions:[],
        note:'No US county lies within 120 nm of the forecast track while it is at tropical-storm force.'});
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
    assert.match(await page.locator('.live-operations').innerText(),/Active Tropical Cyclones:\s*2/);
    assert.match(await page.locator('.live-operations').innerText(),/Active NWS Alerts:\s*0/);
    // Every live storm gets a card and a map marker; no hardcoded storms.
    await page.getByText('Hurricane Isaias',{exact:true}).waitFor();
    await page.getByText('Tropical Storm Rachel',{exact:true}).waitFor();
    await page.getByText(/Forecast peak 105 kt/).waitFor();
    await page.getByText(/NHC forecast track unavailable/).waitFor();
    assert.equal(await page.locator('.live-storm-icon').count(),2);
    assert.equal(await page.locator('.live-storm-icon__spin').first().evaluate(el=>getComputedStyle(el).animationName),'live-ops-spin');
    await page.getByRole('group',{name:'Map focus'}).getByRole('button',{name:'Rachel'}).click();
    assert.equal(await page.getByRole('group',{name:'Map focus'}).getByRole('button',{name:'Rachel'}).getAttribute('aria-pressed'),'true');
    // Each storm has its own plan: Rachel's forecast reaches no US county, Isaias stages from Leon County.
    await page.getByText(/No US county lies within 120 nm/).first().waitFor();
    await page.getByRole('group',{name:'Plan for storm'}).getByRole('button',{name:'Isaias'}).click();
    await page.getByText('Leon County, FL staging area',{exact:true}).waitFor();
    const counties=page.getByRole('region',{name:'Counties at risk from active storms'});
    await counties.getByRole('heading',{name:/Baldwin County/}).waitFor();
    assert.match(await counties.innerText(),/Sally 2020/);
    assert.match(await counties.innerText(),/229 career \/ 567 vol\./);
    await page.screenshot({path:path.join(os.tmpdir(),'storm-live-operations-desktop.png'),fullPage:true});
    await page.getByRole('button',{name:/Back to Overview/}).click();
    await page.locator('.landing-chat--expanded').waitFor();
    await page.getByText('Test response',{exact:true}).waitFor();
    await link.click();
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
    await page.getByText('Live storm feed unavailable',{exact:true}).waitFor();
    const body=await page.locator('.live-operations').innerText();
    assert.match(body,/Live feed unavailable/);
    assert.match(body,/Active Tropical Cyclones:\s*—/);
    assert.doesNotMatch(body,/48|Zero Shelter Shortfall|Live Staging Active|5 \/ 5 trucks/);
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:process.env.TEST_SCREENSHOT || path.join(os.tmpdir(),'storm-live-operations-mobile.png'),fullPage:true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),true);
    assert.deepEqual(errors,[]);
    console.log('PASS: landing search, card route, direct route, zero counts, live storms, per-storm staging, at-risk counties, county routing, filters, back, unavailable feeds, mobile rendering; no page errors.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
