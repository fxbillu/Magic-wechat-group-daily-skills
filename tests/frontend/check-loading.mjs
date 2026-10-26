const task=await taskSpace("wechat-t1-frontend");const page=task.page("p1");
for(const path of ["/d/2026-10-23","/c/fixture-delayed","/c/fixture-delayed/2026-10-23"]) {
  await page.goto("http://127.0.0.1:8873"+path);
  await page.waitForSelector('.banner[aria-live="polite"]');
  const state=await page.evaluate(()=>({waiting:document.querySelector('.banner[aria-live="polite"]')?.textContent,empty:document.querySelector(".emptybox")?.textContent}));
  if(state.empty) throw new Error(`${path}: loading and no-data both visible: ${JSON.stringify(state)}`);
  await page.waitForFunction(()=>!document.querySelector('.banner[aria-live="polite"]'));
}
console.log("PASS: slow date, chat and entry never claim absence while loading");
