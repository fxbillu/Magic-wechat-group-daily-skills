// Public browser route, form, artifact and keyboard flows against contract fixtures.
const task=await taskSpace("wechat-t1-frontend"); const page=task.page("p1");
await page.goto("http://127.0.0.1:8873/search");
await page.waitForSelector("input[type=search]");
const fields=await page.evaluate(()=>[...document.querySelectorAll("form [name]")].map(el=>el.name));
for (const name of ["q","chat","from","to"]) if (!fields.includes(name)) throw new Error(`missing search control ${name}`);
await page.fill("input[name=q]", "合成");
await page.selectOption("select[name=chat]", "fixture-stale");
await page.fill("input[name=from]", "2026-10-25");
await page.fill("input[name=to]", "2026-10-25");
await page.click("button[type=submit]");
await page.waitForSelector(".hit-text");
const url=new URL(await page.url());
for(const [key,value] of Object.entries({q:"合成",chat:"fixture-stale",from:"2026-10-25",to:"2026-10-25"})) {
 if(url.searchParams.get(key)!==value) throw new Error(`route dropped ${key}`);
}
await page.reload(); await page.waitForSelector(".hit-text");
console.log("PASS: combined keyword/group/date search and reload");
await page.click(".item.stack");
await page.waitForSelector("iframe.report");
const link=await page.evaluate(()=>document.querySelector("a[href='/r/synthetic-old.html']")?.href);
if(!link || !(await page.fetch(link)).ok) throw new Error("old report is not readable");
if(!(await page.evaluate(()=>document.body.innerText)).includes("旧稿待更新")) throw new Error("stale state lost");
console.log("PASS: stable identity result route, stale report URL and HTTP artifact");
