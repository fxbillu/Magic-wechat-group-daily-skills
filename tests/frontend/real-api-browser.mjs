// `input` is supplied by test_real_api.py. This script never patches fetch or API data.
const task = await taskSpace(input.space);
const page = task.page("p1");
const assert = (ok, message) => { if (!ok) throw new Error(message); };
const goto = async path => {
  await page.goto(input.base + path);
  await page.waitForFunction(() => !document.querySelector('[aria-busy="true"]') && !!document.querySelector("h1"));
};
const detail = (username, date = input.day) => `/c/${encodeURIComponent(username)}/${date}`;
const text = () => page.evaluate(() => document.body.innerText);
const screen = async name => {
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "document overflow: " + name);
  await page.screenshot({path:input.evidence + "/" + name + ".png"});
};
await page.cdp("Page.addScriptToEvaluateOnNewDocument", {source:"window.__qaErrors=[];addEventListener('error',e=>window.__qaErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__qaErrors.push(String(e.reason)));"});
if (input.phase === "initial") {
  for (const width of [1280, 390]) {
    await page.cdp("Emulation.setDeviceMetricsOverride", {width,height:844,deviceScaleFactor:1,mobile:false});
    await goto("/d/" + input.day);
    await page.waitForSelector(".card");
    const rows = await page.evaluate(() => [...document.querySelectorAll(".card")].map(e => ({href:e.querySelector(".card-link").getAttribute("href"),text:e.innerText})));
    assert(rows.length === 2, "same-name groups collapsed");
    for (const id of input.groups) {
      const row = rows.find(e => e.href === detail(id));
      assert(row?.text.includes(id) && row.text.includes("采集成功"), "same-name identity/status missing " + id);
    }
    assert((await text()).includes("2 个群采集成功"), "incorrect collected-group count");
    await screen("live-day-" + width);
    await page.keyboard.press("j"); await page.keyboard.press("Enter");
    await page.waitForSelector(".msg");
    assert((await page.url()).endsWith(detail(input.groups[0])), "keyboard lost stable group identity");
    assert((await text()).includes("成员甲") && (await text()).includes("甲的合成消息"), "actual message source not readable");
    await goto("/c/" + encodeURIComponent(input.groups[1]));
    await page.waitForSelector(".list .item");
    assert((await text()).includes(input.groups[1]), "group history lost stable identity");
    await goto("/dates"); await page.waitForSelector(".list .item");
    await goto("/matrix"); await page.waitForSelector("table.mx");
    assert((await text()).includes("成功零消息"), "matrix lost successful empty collection");
    await goto(detail(input.groups[0], "2026-10-24"));
    assert((await text()).includes("成功零消息") && !(await text()).includes("采集失败"), "zero-message day misrepresented");
    await goto(detail(input.groups[0], "2026-10-23"));
    assert((await text()).includes("未采集") && !(await text()).includes("成功零消息"), "uncollected day became empty");
    await screen("live-not-collected-" + width);
    assert(await page.evaluate(() => !window.__qaErrors.length), "browser runtime exception");
  }
} else if (["ready", "stale", "failed", "reindexed"].includes(input.phase)) {
  await page.cdp("Emulation.setDeviceMetricsOverride", {width:390,height:844,deviceScaleFactor:1,mobile:false});
  await goto(detail(input.groups[0]));
  await page.waitForSelector("iframe.report");
  const label = input.phase === "ready" ? "可读" : "旧稿待更新";
  assert((await text()).includes(label), "report status missing " + label);
  const artifact = await page.evaluate(() => document.querySelector("iframe.report").getAttribute("src"));
  assert(artifact === input.html_url, "front-end changed artifact URL");
  const response = await page.fetch(artifact);
  assert(response.ok && response.body.includes("合成联调日报甲"), "actual rendered artifact not readable");
  const name = await page.evaluate(() => document.querySelector("h1").innerText);
  assert(name === input.name, "renamed group routed to wrong identity");
  if (["failed", "reindexed"].includes(input.phase)) {
    assert((await text()).includes("采集失败"), "latest failure hidden by old report");
    assert(!(await text()).includes("成功零消息"), "failed collection became empty");
    await screen("live-" + input.phase + "-390");
    await goto(detail(input.groups[1])); await page.waitForSelector(".msg");
    assert((await text()).includes("采集失败") && (await text()).includes("乙的合成消息"), "failed retry lost previous successful material");
  } else { await screen("live-" + input.phase + "-390"); }
  assert(await page.evaluate(() => !window.__qaErrors.length), "browser runtime exception");
} else if (input.phase === "first-failure" || input.phase === "timezone") {
  await page.cdp("Emulation.setDeviceMetricsOverride", {width:390,height:844,deviceScaleFactor:1,mobile:false});
  await goto(detail(input.groups[0]));
  await page.waitForSelector(".banner.err");
  await page.waitForFunction(() => !document.querySelector(".skeleton"));
  const body = await text();
  assert(body.includes("采集失败") && !body.includes("成功零消息"), "first failure is not visible");
  assert(body.includes("原始记录取不到"), "409 failed-source terminal state missing");
  if (input.phase === "timezone") assert(body.includes("TIMEZONE_UNAVAILABLE") && /请先.*修复上述问题/.test(body), "non-retryable timezone failure lacks repair guidance");
  const metrics = await page.evaluate(() => [...document.querySelectorAll(".kv > div")].slice(0,3).map(e=>e.innerText));
  assert(metrics.every(value=>value.includes("—")), "first failure without successful material claims zero metrics: " + JSON.stringify(metrics));
  await screen("live-" + input.phase + "-390");
}
console.log("PASS real Python API + browser: " + input.phase);
