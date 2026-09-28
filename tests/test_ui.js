/* Loads the real index.html and app.js in a DOM and drives the controls. */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const REPO = path.join(__dirname, "..");

const html = fs.readFileSync(`${REPO}/web/index.html`, "utf8");
const dom = new JSDOM(html, { runScripts: "outside-only" });
const { window } = dom;
window.pywebview = { api: {} };           // the bridge, unused in these checks
window.eval(fs.readFileSync(`${REPO}/web/app.js`, "utf8"));

const doc = window.document;
const $ = (id) => doc.getElementById(id);
const fill = (v) => doc.querySelector(`.seg[data-value="${v}"]`);
const active = () => doc.querySelector(".seg.active").dataset.value;
const change = (elm, value) => {
  elm.value = value;
  elm.dispatchEvent(new window.Event("change"));
};
const click = (elm) => elm.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));

let failures = 0;
const check = (label, got, want) => {
  const ok = String(got) === String(want);
  if (!ok) failures++;
  console.log(`${ok ? "  ok  " : " FAIL "} ${label}: got ${got}, want ${want}`);
};

window.dispatchEvent(new window.Event("pywebviewready"));

console.log("Starting state (PNG):");
check("transparent enabled", fill("alpha").disabled, false);
check("example filename", $("example").textContent.trim(), "Saved as frame_000000.png");

console.log("\nChoose JPEG:");
change($("format"), "jpg");
check("transparent disabled", fill("alpha").disabled, true);
check("tooltip explains why", fill("alpha").title, "JPEG cannot store transparency");
check("example extension", $("example").textContent.trim(), "Saved as frame_000000.jpg");
check("hint mentions lossy", /lossy/.test($("formatHint").textContent), true);

console.log("\nClicking the disabled option does nothing:");
click(fill("alpha"));
check("still on black", active(), "black");

console.log("\nBack to PNG:");
change($("format"), "png");
check("transparent enabled again", fill("alpha").disabled, false);

console.log("\nTransparent selected, then JPEG chosen:");
click(fill("alpha"));
check("transparent is active", active(), "alpha");
change($("format"), "jpg");
check("moved off transparent", active(), "black");
check("no active button left disabled", doc.querySelector(".seg.active").disabled, false);
check("told the user in the log", /Transparent is not available/.test($("log").textContent), true);

console.log("\nWebP keeps transparency:");
change($("format"), "webp");
check("transparent enabled", fill("alpha").disabled, false);
click(fill("alpha"));
check("transparent selectable", active(), "alpha");
check("example extension", $("example").textContent.trim(), "Saved as frame_000000.webp");

console.log("\nPrefix feeds the example:");
$("prefix").value = "yoga";
$("prefix").dispatchEvent(new window.Event("input"));
check("example uses it", $("example").textContent.trim(), "Saved as yoga_000000.webp");
$("prefix").value = "";
$("prefix").dispatchEvent(new window.Event("input"));
check("empty falls back to frame", $("example").textContent.trim(), "Saved as frame_000000.webp");

console.log(failures ? `\n${failures} FAILURES` : "\nall checks passed");
process.exit(failures ? 1 : 0);
