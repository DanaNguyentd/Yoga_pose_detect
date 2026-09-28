const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const REPO = path.join(__dirname, "..");
const dom = new JSDOM(fs.readFileSync(`${REPO}/web/index.html`, "utf8"), { runScripts: "outside-only" });
const { window } = dom; const doc = window.document;
window.HTMLMediaElement.prototype.load = function () {};

// the real numbers from test/IMG_8803.MOV
window.pywebview = { api: {
  probe: async () => ({ ok: true, fps: 30.00086212158203, frames: 6964,
                        duration: 232.126, width: 1688, height: 1078 }),
  choose_video: async () => ({ path: "/x/IMG_8803.MOV" }),
  serve_video: async () => ({ ok: true, url: "http://127.0.0.1:9/t" }),
  frame_at: async () => ({ ok: true, image: "x" }),
}};
window.eval(fs.readFileSync(`${REPO}/web/app.js`, "utf8"));

const $ = (id) => doc.getElementById(id);
const click = (e) => e.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
const input = (e, v) => { e.value = v; e.dispatchEvent(new window.Event("input")); };
const wait = (ms = 40) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
const check = (l, got, want) => {
  const ok = String(got) === String(want);
  if (!ok) failures++;
  console.log(`${ok ? "  ok  " : " FAIL "} ${l}: got ${got}, want ${want}`);
};
const text = () => Array.from($("positionInfo").children).map((s) => s.textContent).join(" ");

(async () => {
  window.dispatchEvent(new window.Event("pywebviewready"));
  check("hidden before a video", $("positionInfo").hidden, true);

  click($("chooseVideo"));
  await wait();

  console.log("Scrubbing the bar under the video:");
  $("video").dispatchEvent(new window.Event("error"));   // force the scrubber
  await wait();
  input($("scrub"), 60);
  await wait();
  check("shows time and frame", text(), "1:00.0 of 3:52 frame 1,800 of 6,964");

  input($("scrub"), 120.5);
  await wait();
  check("updates", text(), "2:00.5 of 3:52 frame 3,615 of 6,964");

  console.log("\nMoving a range handle also reports the frame:");
  input($("startTime"), 30);
  await wait();
  check("frame at 0:30", text(), "0:30.0 of 3:52 frame 900 of 6,964");
  check("summary names frames",
        $("rangeSummary").textContent,
        "3:22 of footage, frame 900 to 6,963.");

  console.log("\nPlayback reports it too:");
  const v = $("video");
  Object.defineProperty(v, "currentTime", { value: 45, writable: true });
  v.dispatchEvent(new window.Event("timeupdate"));
  check("from the playhead", text(), "0:45.0 of 3:52 frame 1,350 of 6,964");

  console.log("\nThe frame shown is the one the file will be named after:");
  const shown = 1350, fps = 30.00086212158203;
  check("python floor(45 * fps)", Math.floor(45 * fps), shown);

  console.log(failures ? `\n${failures} FAILURES` : "\nall checks passed");
  process.exit(failures ? 1 : 0);
})();
