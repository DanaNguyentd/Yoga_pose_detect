/* The player's clock and the range handles must agree.
 *
 * A range input snaps its value to min + n * step. With a step of half a
 * second a handle could not land on the moment the video was paused at, and
 * the grid stopped short of the end of the video unless its length happened
 * to be a multiple of the step. These check that neither can come back. */

const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const REPO = path.join(__dirname, "..");

const dom = new JSDOM(fs.readFileSync(`${REPO}/web/index.html`, "utf8"),
                      { runScripts: "outside-only" });
const { window } = dom;
const doc = window.document;
window.HTMLMediaElement.prototype.load = function () {};

// the real numbers OpenCV reports for a 3:52 iPhone clip
const DURATION = 232.12666261981303;
const runs = [];
window.pywebview = { api: {
  probe: async () => ({ ok: true, fps: 30.00086212158203, frames: 6964,
                        duration: DURATION, width: 1688, height: 1078 }),
  choose_video: async () => ({ path: "/x/IMG_8803.MOV" }),
  serve_video: async () => ({ ok: true, url: "http://127.0.0.1:9/t" }),
  frame_at: async () => ({ ok: true, image: "x" }),
  start: async (s) => { runs.push(s); return { ok: true }; },
}};
window.eval(fs.readFileSync(`${REPO}/web/app.js`, "utf8"));

const $ = (id) => doc.getElementById(id);
const click = (e) => e.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
const wait = (ms = 40) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
const check = (label, got, want) => {
  const ok = String(got) === String(want);
  if (!ok) failures++;
  console.log(`${ok ? "  ok  " : " FAIL "} ${label}: got ${got}, want ${want}`);
};

(async () => {
  window.dispatchEvent(new window.Event("pywebviewready"));
  click($("chooseVideo"));
  await wait();

  console.log("No step grid for the handles to snap to:");
  check("start handle", $("startTime").step, "any");
  check("end handle", $("endTime").step, "any");
  check("scrubber", $("scrub").step, "any");

  console.log("\nThe handles reach the real end of the video:");
  check("end handle max", $("endTime").max, String(DURATION));
  check("reset puts it at the end", Number($("endTime").value), DURATION);
  check("and that counts as the whole video", $("rangeSummary").textContent, "The whole video.");

  console.log("\nA position from the player is kept exactly:");
  const v = $("video");
  Object.defineProperty(v, "currentTime", { value: 83.7, writable: true });
  v.dispatchEvent(new window.Event("loadedmetadata"));   // canPlay
  click($("startHere"));
  check("handle took the playhead", Number($("startTime").value), 83.7);
  check("label agrees with the player", $("startLabel").textContent, "1:23.7");

  console.log("\nThe readout under the player says the same thing:");
  v.dispatchEvent(new window.Event("timeupdate"));
  const readout = Array.from($("positionInfo").children).map((s) => s.textContent);
  check("same time", readout[0].startsWith("1:23.7"), true);

  console.log("\nWhat Python is told matches what is on screen:");
  $("videoPath").value = "/x/IMG_8803.MOV";
  click($("startBtn"));
  await wait();
  check("start_seconds is the exact position", runs[runs.length - 1].start_seconds, 83.7);
  check("end_seconds is null for the untouched end", runs[runs.length - 1].end_seconds, null);

  console.log("\nHandles still cannot cross:");
  $("startTime").focus();
  $("startTime").value = 300;
  $("startTime").dispatchEvent(new window.Event("input"));
  check("start stays below end", Number($("startTime").value) < Number($("endTime").value), true);

  console.log(failures ? `\n${failures} FAILURES` : "\nall checks passed");
  process.exit(failures ? 1 : 0);
})();
