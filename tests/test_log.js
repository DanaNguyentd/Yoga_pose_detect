const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const REPO = path.join(__dirname, "..");

const dom = new JSDOM(fs.readFileSync(`${REPO}/web/index.html`, "utf8"), { runScripts: "outside-only" });
const { window } = dom;
const doc = window.document;

// A bridge that records calls and answers like Python would
const calls = [];
window.pywebview = { api: {
  probe: async (p) => ({ ok: true, fps: 30, frames: 120, duration: 4, width: 320, height: 240 }),
  preview: async (s) => { calls.push("preview"); return { ok: true, image: "data:image/png;base64,AAAA" }; },
  start: async (s) => { calls.push("start"); return { ok: true }; },
  cancel: async () => ({ ok: true }),
}};
window.eval(fs.readFileSync(`${REPO}/web/app.js`, "utf8"));

const $ = (id) => doc.getElementById(id);
// each log line is its own <div>, so count elements rather than split text
const lines = () => Array.from($("log").children).map((c) => c.textContent);
const click = (e) => e.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
const wait = () => new Promise((r) => setTimeout(r, 30));

let failures = 0;
const check = (label, got, want) => {
  const ok = String(got) === String(want);
  if (!ok) failures++;
  console.log(`${ok ? "  ok  " : " FAIL "} ${label}: got ${got}, want ${want}`);
};

(async () => {
  window.dispatchEvent(new window.Event("pywebviewready"));
  check("ready message present", lines().length, 1);

  $("videoPath").value = "/tmp/fake.MOV";

  // pile up some noise
  window.appEvents.log("old line 1");
  window.appEvents.log("old line 2");
  check("log has grown", lines().length, 3);

  console.log("\nPreview clears the log first:");
  click($("previewBtn"));
  await wait();
  check("preview ran", calls.includes("preview"), true);
  check("old lines gone", lines().some((l) => l.startsWith("old line")), false);

  console.log("\nMessages from the new run still arrive:");
  window.appEvents.log("Preview ready. The subject covers 6.3% of the frame.");
  check("new line present", lines().length, 1);

  console.log("\nExtraction clears it too:");
  window.appEvents.log("more noise");
  click($("startBtn"));
  await wait();
  check("start ran", calls.includes("start"), true);
  check("log emptied", lines().length, 0);

  console.log("\nRefusing to run does NOT wipe the log:");
  $("videoPath").value = "";
  window.appEvents.log("keep me");
  click($("startBtn"));
  await wait();
  check("kept, plus the refusal", lines().includes("keep me"), true);

  console.log(failures ? `\n${failures} FAILURES` : "\nall checks passed");
  process.exit(failures ? 1 : 0);
})();
