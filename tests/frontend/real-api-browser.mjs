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
    assert((await text()).includes("关注范围未知") && !(await text()).includes("成功零消息"), "unknown historical range became an empty day or collection debt");
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
if (input.phase === "search-filter") {
  for (const width of [1280,390]) {
    await page.cdp("Emulation.setDeviceMetricsOverride", {width,height:844,deviceScaleFactor:1,mobile:false});
    await goto("/search");
    for (let index=0;index<input.groups.length;index++) {
      await page.fill("input[name=q]","合成消息");
      await page.selectOption("select[name=chat]",input.groups[index]);
      await page.fill("input[name=from]",input.day); await page.fill("input[name=to]",input.day);
      await page.click("button[type=submit]"); await page.waitForSelector(".hit-text");
      const url=new URL(await page.url());
      for(const [key,value] of Object.entries({q:"合成消息",chat:input.groups[index],from:input.day,to:input.day})) assert(url.searchParams.get(key)===value,"search route lost "+key);
      await page.reload(); await page.waitForSelector(".hit-text");
      const matches=await page.evaluate(()=>[...document.querySelectorAll(".item.stack")].map(e=>({href:e.getAttribute("href"),text:e.innerText})));
      assert(matches.length===1 && matches[0].href===detail(input.groups[index]),"same-name group filter broadened");
      assert(matches[0].text.includes(index===0?"甲的合成消息":"乙的合成消息"),"wrong same-name group result");
      const values=await page.evaluate(()=>Object.fromEntries([...document.querySelectorAll("form [name]")].map(e=>[e.name,e.value])));
      assert(values.chat===input.groups[index] && values.from===input.day && values.to===input.day,"reload dropped filters");
    }
    await screen("t3-search-"+width);
    await page.keyboard.press("j"); await page.keyboard.press("Enter"); await page.waitForSelector(".msg");
    assert((await page.url()).endsWith(detail(input.groups[1])),"search keyboard opened wrong group");
    assert((await text()).includes("乙的合成消息"),"search navigation lost source");
  }
} else if (input.phase === "scope") {
  for (const width of [1280,390]) {
    await page.cdp("Emulation.setDeviceMetricsOverride", {width,height:844,deviceScaleFactor:1,mobile:false});
    await goto("/d/"+input.day); await page.waitForSelector(".card");
    assert(await page.evaluate(()=>document.querySelectorAll(".card").length===2),"new follow created historical debt");
    await goto("/matrix"); await page.waitForSelector("table.mx");
    const rows=await page.evaluate(()=>[...document.querySelectorAll("table.mx tbody tr")].map(e=>({id:decodeURIComponent(e.querySelector("th a").getAttribute("href").slice(3)),cells:[...e.querySelectorAll("td")].map(c=>c.innerText)})));
    const known=rows.find(r=>r.id===input.known), unknown=rows.find(r=>r.id===input.unknown);
    assert(known && known.cells.filter(v=>v.includes("当前关注范围外")).length===2 && known.cells.filter(v=>v.includes("未采集")).length===1,"effective date did not separate past/current scope: "+JSON.stringify(known));
    assert(unknown && unknown.cells.every(v=>v.includes("关注范围未知")),"unknown range became missing: "+JSON.stringify(unknown));
    await screen("t3-matrix-"+width);
    await goto(detail(input.known));
    assert((await text()).includes("当前关注范围外") && !(await text()).includes("待产稿"),"out-of-scope detail implies debt");
    await goto(detail(input.unknown));
    assert((await text()).includes("关注范围未知") && !(await text()).includes("待产稿"),"unknown scope detail implies debt");
    await screen("t3-unknown-"+width);
    await goto("/d/2026-10-26"); await page.waitForSelector(".card");
    const summary=await page.evaluate(()=>document.querySelector(".hd .sub").innerText);
    assert(summary.includes("1 个群采集成功") && /可读\s*0\s*\/ 2/.test(summary) && summary.includes("未采集 1"),"scope denominator wrong: "+summary);
  }
} else if (input.phase === "unfollowed") {
  await page.cdp("Emulation.setDeviceMetricsOverride", {width:390,height:844,deviceScaleFactor:1,mobile:false});
  await goto("/chats"); await page.waitForSelector(".list .item");
  for(const username of input.groups) {
    await goto("/c/"+encodeURIComponent(username)); await page.waitForSelector(".list .item");
    assert((await text()).includes(username),"unfollowed or removed group lost history");
  }
  await goto(detail(input.groups[0])); await page.waitForSelector("iframe.report");
  assert((await text()).includes("可读"),"unfollowing removed report state");
  const response=await page.fetch(input.html_url);
  assert(response.ok && response.body.includes("合成联调日报甲"),"unfollowing removed actual report");
  await screen("t3-unfollowed-390");
}
assert(await page.evaluate(()=>!window.__qaErrors.length),"browser runtime exception in "+input.phase);
console.log("PASS real Python API + browser: " + input.phase);
