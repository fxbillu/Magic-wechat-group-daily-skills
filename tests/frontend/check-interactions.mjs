const task=await taskSpace("wechat-t1-frontend"); const page=task.page("p1");
const assert=(ok,message)=>{if(!ok) throw new Error(message);};
await page.cdp("Page.addScriptToEvaluateOnNewDocument",{source:"window.__readerErrors=[]; addEventListener('error',e=>window.__readerErrors.push(e.message)); addEventListener('unhandledrejection',e=>window.__readerErrors.push(String(e.reason)));"});
for(const width of [1280,390]) {
  await page.cdp("Emulation.setDeviceMetricsOverride",{width,height:844,deviceScaleFactor:1,mobile:false});
  for(const path of ["/","/dates","/chats","/d/2026-10-25","/c/fixture-stale","/c/fixture-stale/2026-10-25","/matrix","/search?q=%E5%90%88%E6%88%90&chat=fixture-stale&from=2026-10-25&to=2026-10-25"]) {
    await page.goto("http://127.0.0.1:8873"+path);
    await page.waitForSelector("h1");
    const result=await page.evaluate(()=>({title:document.querySelector("h1")?.innerText,overflow:document.documentElement.scrollWidth>innerWidth,error:document.querySelector(".banner.err")?.innerText,exceptions:window.__readerErrors}));
    assert(result.title && !result.error && !result.overflow && !result.exceptions.length,JSON.stringify({width,path,...result}));
  }
}
console.log("PASS: eight public reading routes at 1280px/390px");
await page.goto("http://127.0.0.1:8873/d/2026-10-25"); await page.waitForSelector(".card");
await page.keyboard.press("j"); await page.keyboard.press("j");
assert(await page.evaluate(()=>document.querySelectorAll(".kb-cursor").length===1),"old keyboard cursor remains");
await page.keyboard.press("Enter"); await page.waitForSelector("h1");
assert((await page.url()).endsWith("/c/fixture-failed/2026-10-25"),"j/Enter lost stable identity");
await page.keyboard.press("/"); await page.waitForSelector("input[type=search]");
assert(await page.evaluate(()=>document.activeElement.type==="search"),"slash did not focus search");
await page.keyboard.press("Escape");
await page.keyboard.press("?");
await page.waitForSelector("dialog[open]");
await page.keyboard.press("Tab");
assert(await page.evaluate(()=>document.querySelector("dialog").matches(":modal") && (document.activeElement===document.body || !!document.activeElement.closest("dialog"))),"help allowed focus into background page");
await page.keyboard.press("Escape");
assert(await page.evaluate(()=>!document.querySelector("dialog").open),"help did not close");
console.log("PASS: j/Enter, slash focus, Escape and modal Tab containment");
await page.goto("http://127.0.0.1:8873/c/fixture-stale/2026-10-25"); await page.waitForSelector("iframe.report");
await page.click(".workbuddy-action summary");
await page.click(".workbuddy-action button");
await page.waitForFunction(()=>!!document.querySelector(".workbuddy-action[open] .copy-notice")?.textContent);
const notice=await page.evaluate(()=>document.querySelector(".workbuddy-action[open] .copy-notice").textContent);
assert(/已复制|手动复制/.test(notice),"copy command has no terminal state");
assert(await page.evaluate(()=>document.querySelector(".workbuddy-action[open] .setup-request").textContent.includes('"fixture-stale"')),"WorkBuddy instruction lost stable identity");
console.log("PASS: copyable WorkBuddy recovery instruction");
await page.goto("http://127.0.0.1:8873/d/2026-10-24");
await page.waitForSelector(".banner.err");
const before=await page.evaluate(()=>document.body.innerText);
assert(before.includes("合成日期读取失败") && !before.includes("日报可读"),"date failure concealed by stale content");
await page.click(".banner.err button"); await page.waitForSelector(".banner.err");
console.log("PASS: failed date and explicit retry retain accurate error terminal state");
await page.goto("http://127.0.0.1:8873/search"); await page.waitForSelector("input[name=q]");
await page.fill("input[name=q]","不存在"); await page.click("button[type=submit]");
await page.waitForSelector(".emptybox");
assert((await page.evaluate(()=>document.body.innerText)).includes("没有命中"),"no-result empty state missing");
await page.fill("input[name=from]","2026-10-26"); await page.fill("input[name=to]","2026-10-25"); await page.click("button[type=submit]");
assert((await page.evaluate(()=>document.body.innerText)).includes("开始日期不能晚于结束日期"),"invalid range not explained");
console.log("PASS: search empty state and invalid date range");
for(const [port,expected] of [[8874,"从第一份群日报开始"],[8875,"还没有任何归档"],[8876,"合成索引读取失败"]]) {
  await page.goto(`http://127.0.0.1:${port}/`);
  await page.waitForFunction(text=>document.body.innerText.includes(text),expected);
  assert(await page.evaluate(()=>!document.querySelector('[aria-busy="true"]')),"loading never ended");
}
await page.click(".banner.err button");
await page.waitForSelector(".banner.err");
console.log("PASS: unconfigured, no-data and browse-error terminal states/recheck");
