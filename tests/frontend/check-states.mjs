// Run with ego-browser nodejs < tests/frontend/check-states.mjs.
// A synthetic contract peer must be listening on 8873. Public rendered DOM only.
const task = await taskSpace("wechat-t1-frontend");
const page = task.page("p1");
await page.goto("http://127.0.0.1:8873/d/2026-10-25");
await page.waitForSelector(".card");
const cards = await page.evaluate(() => [...document.querySelectorAll(".card")].map(el => ({
  href:el.querySelector(".card-link").getAttribute("href"), text:el.innerText
})));
const expected = {missing:"未采集", failed:"采集失败", empty:"成功零消息", short:"素材不足", pending:"待产稿", ready:"可读", stale:"旧稿待更新", running:"采集中", unknown:"未核验", broken:"未核验", "invalid-empty":"未核验"};
for (const [id, label] of Object.entries(expected)) {
  const card=cards.find(c=>c.href===`/c/fixture-${id}/2026-10-25`);
  if (!card?.text.includes(label)) throw new Error(`${id}: expected ${label}, got ${card?.text}`);
}
const body=await page.evaluate(()=>document.body.innerText);
if (!body.includes("6 个群采集成功")) throw new Error("successful collection count must be 6 including zero-message collection");
if (body.includes("无对话")) throw new Error("missing must not mean no conversation");
console.log("PASS: independent collection/report states, unknown values, archive counts");

if (cards.find(c=>c.href.includes("fixture-invalid-empty/")).text.includes("成功零消息")) throw new Error("unknown message count became successful zero");
