const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const REPO = path.join(__dirname, "..");

const dom = new JSDOM(fs.readFileSync(`${REPO}/web/index.html`, "utf8"),
                      { runScripts: "outside-only" });
const { window } = dom;
const doc = window.document;

const asked = [];   // frame_at positions
const runs = [];    // settings handed to start()

// jsdom has no media pipeline; the real web view does
window.HTMLMediaElement.prototype.load = function () {};
window.pywebview = { api: {
  probe: async () => ({ ok: true, fps: 30, frames: 7200, duration: 240,
                        width: 1920, height: 1080 }),
  choose_video: async () => ({ path: "/Users/me/My Videos/yoga class.MOV" }),
  choose_folder: async () => ({ path: null }),
  frame_at: async (p, s) => { asked.push(s); return { ok: true, image: "data:image/jpeg;base64,X" }; },
  serve_video: async () => ({ ok: true, url: "http://127.0.0.1:9/abc" }),
  preview: async () => ({ ok: true, image: "x" }),
  start: async (s) => { runs.push(s); return { ok: true }; },
}};
window.eval(fs.readFileSync(`${REPO}/web/app.js`, "utf8"));

const $ = (id) => doc.getElementById(id);
const click = (e) => e.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
const input = (e, v) => { e.value = v; e.dispatchEvent(new window.Event("input")); };
const wait = (ms = 40) => new Promise((r) => setTimeout(r, ms));

let failures = 0;
const check = (label, got, want) => {
  const ok = String(got) === String(want);
  if (!ok) failures++;
  console.log(`${ok ? "  ok  " : " FAIL "} ${label}: got ${got}, want ${want}`);
};

(async () => {
  window.dispatchEvent(new window.Event("pywebviewready"));
  check("range bar hidden before a video", $("rangebar").hidden, true);

  click($("chooseVideo"));
  await wait();

  console.log("A 4 minute video is chosen:");
  check("range bar shown", $("rangebar").hidden, false);
  check("start at 0:00", $("startLabel").textContent, "0:00");
  check("end at 4:00", $("endLabel").textContent, "4:00");
  check("summary says whole video", $("rangeSummary").textContent, "The whole video.");
  check("player got the served URL", $("video").src, "http://127.0.0.1:9/abc");
  check("estimate is the whole video", /240 images/.test($("estimate").textContent), true);

  console.log("\nTrimming to 1:00 - 2:00:");
  input($("startTime"), 60);
  input($("endTime"), 120);
  check("start label", $("startLabel").textContent, "1:00");
  check("end label", $("endLabel").textContent, "2:00");
  check("summary", $("rangeSummary").textContent, "1:00 of footage, frame 1,800 to 3,600.");
  check("estimate follows the range", /60 images/.test($("estimate").textContent), true);

  console.log("\nHandles cannot cross:");
  $("startTime").focus();
  input($("startTime"), 200);
  check("start pushed below end", Number($("startTime").value) < Number($("endTime").value), true);

  console.log("\nReset:");
  click($("rangeReset"));
  check("back to whole video", $("rangeSummary").textContent, "The whole video.");
  check("estimate back", /240 images/.test($("estimate").textContent), true);

  console.log("\nUnplayable video falls back to the scrubber:");
  $("video").dispatchEvent(new window.Event("error"));
  await wait();
  check("scrubber shown", $("scrubber").hidden, false);
  check("video hidden", $("video").hidden, true);
  check("a frame was requested", asked.length > 0, true);

  console.log("\nScrubbing asks Python for frames, one at a time:");
  const before = asked.length;
  input($("scrub"), 30);
  input($("scrub"), 90);
  input($("scrub"), 150);
  await wait(80);
  check("frames fetched", asked.length > before, true);
  check("last position wins", asked[asked.length - 1], 150);

  console.log("\n'use current' takes the scrubber position:");
  input($("scrub"), 90);
  await wait();
  click($("startHere"));
  check("start moved to 1:30", $("startLabel").textContent, "1:30");

  console.log("\nWhat gets sent to Python:");
  input($("startTime"), 30);
  input($("endTime"), 90);
  $("videoPath").value = "/Users/me/My Videos/yoga class.MOV";
  click($("startBtn"));
  await wait();
  const sent = runs[runs.length - 1];
  check("start_seconds", sent.start_seconds, 30);
  check("end_seconds", sent.end_seconds, 90);

  console.log("\nWhole video sends nulls, not numbers:");
  click($("rangeReset"));
  click($("startBtn"));
  await wait();
  const full = runs[runs.length - 1];
  check("start_seconds", full.start_seconds, null);
  check("end_seconds", full.end_seconds, null);

  console.log(failures ? `\n${failures} FAILURES` : "\nall checks passed");
  process.exit(failures ? 1 : 0);
})();
