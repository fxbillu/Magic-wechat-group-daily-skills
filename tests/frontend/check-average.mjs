const task=await taskSpace("wechat-t1-frontend");const page=task.page("p1");
await page.goto("http://127.0.0.1:8873/c/fixture-average");
await page.waitForSelector(".list .item");
const summary=await page.evaluate(()=>document.querySelector(".hd .sub").innerText);
if (!/归档\s*2\s*天/.test(summary) || !/平均\s*1\s*条\/天/.test(summary)) throw new Error(`two successful days (2 and 0 messages) must average 1: ${summary}`);
console.log("PASS: successful zero-message days remain in daily average");
