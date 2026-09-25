/* Front end for the frame extractor.
 *
 * Everything here is presentation and input collection. The analysis lives in
 * Python: this file calls it through `pywebview.api`, which returns a Promise,
 * and Python calls back into `window.appEvents` while a long run is going. */

const el = (id) => document.getElementById(id);

const ui = {
  videoPath: el("videoPath"),
  outputPath: el("outputPath"),
  prefix: el("prefix"),
  removeBg: el("removeBg"),
  bgOptions: el("bgOptions"),
  threshold: el("threshold"),
  samples: el("samples"),
  minArea: el("minArea"),
  fill: el("fill"),
  previewBtn: el("previewBtn"),
  startBtn: el("startBtn"),
  cancelBtn: el("cancelBtn"),
  preview: el("preview"),
  placeholder: el("placeholder"),
  previewFigure: el("previewFigure"),
  previewImage: el("previewImage"),
  bar: el("bar"),
  status: el("status"),
  counter: el("counter"),
  log: el("log"),
};

let apiReady = false;
let running = false;

/* ------------------------------------------------------------------ helpers */

function log(message, kind) {
  const line = document.createElement("div");
  if (kind) line.className = kind;
  line.textContent = message;
  ui.log.appendChild(line);
  ui.log.scrollTop = ui.log.scrollHeight;
}

function setStatus(text) {
  ui.status.textContent = text;
}

function setProgress(done, total) {
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : 0;
  ui.bar.style.width = `${pct}%`;
  ui.counter.textContent = total > 0 ? `${done} / ${total}` : "";
}

function setRunning(isRunning) {
  running = isRunning;
  ui.startBtn.disabled = isRunning;
  ui.previewBtn.disabled = isRunning || !ui.removeBg.checked;
  ui.cancelBtn.hidden = !isRunning;
}

function settings() {
  return {
    video_path: ui.videoPath.value.trim(),
    output_dir: ui.outputPath.value.trim() || null,
    prefix: ui.prefix.value.trim() || "frame",
    remove_bg: ui.removeBg.checked,
    bg_threshold: Number(ui.threshold.value),
    bg_samples: Number(ui.samples.value),
    bg_fill: ui.fill.querySelector(".seg.active").dataset.value,
    min_area_pct: Number(ui.minArea.value),
  };
}

function requireVideo() {
  if (ui.videoPath.value.trim()) return true;
  log("Choose a video file first.", "err");
  setStatus("No video chosen");
  return false;
}

/* Python is unreachable until pywebview has injected its bridge. */
function requireApi() {
  if (apiReady) return true;
  log("The Python side is not ready yet. Give it a moment.", "err");
  return false;
}

/* ------------------------------------------------------------- form wiring */

ui.threshold.addEventListener("input", () => {
  el("thresholdValue").textContent =
    ui.threshold.value === "0" ? "auto" : ui.threshold.value;
});

ui.samples.addEventListener("input", () => {
  el("samplesValue").textContent = ui.samples.value;
});

ui.minArea.addEventListener("input", () => {
  el("minAreaValue").textContent = `${Number(ui.minArea.value).toFixed(1)}%`;
});

ui.fill.addEventListener("click", (event) => {
  const button = event.target.closest(".seg");
  if (!button) return;
  ui.fill.querySelectorAll(".seg").forEach((b) => b.classList.remove("active"));
  button.classList.add("active");
});

ui.removeBg.addEventListener("change", () => {
  const on = ui.removeBg.checked;
  ui.bgOptions.style.opacity = on ? "1" : ".45";
  ui.bgOptions.style.pointerEvents = on ? "" : "none";
  ui.previewBtn.disabled = !on || running;
});

/* ---------------------------------------------------------------- commands */

el("chooseVideo").addEventListener("click", async () => {
  if (!requireApi()) return;
  const result = await window.pywebview.api.choose_video();
  if (result.path) {
    ui.videoPath.value = result.path;
    log(`Video: ${result.path}`);
    setStatus("Ready");
  }
});

el("chooseOutput").addEventListener("click", async () => {
  if (!requireApi()) return;
  const result = await window.pywebview.api.choose_folder();
  if (result.path) ui.outputPath.value = result.path;
});

ui.previewBtn.addEventListener("click", async () => {
  if (!requireApi() || !requireVideo()) return;
  setRunning(true);
  setStatus("Building the preview");
  setProgress(0, 0);
  try {
    const result = await window.pywebview.api.preview(settings());
    if (result.ok) {
      ui.previewImage.src = result.image;
      ui.previewFigure.hidden = false;
      ui.placeholder.hidden = true;
      setStatus("Preview ready");
    } else {
      log(result.error, "err");
      setStatus("Preview failed");
    }
  } finally {
    setRunning(false);
  }
});

ui.startBtn.addEventListener("click", async () => {
  if (!requireApi() || !requireVideo()) return;
  setRunning(true);
  ui.bar.className = "bar";
  setProgress(0, 0);
  setStatus("Extracting");
  const result = await window.pywebview.api.start(settings());
  if (!result.ok) {
    log(result.error, "err");
    setStatus("Could not start");
    setRunning(false);
  }
});

ui.cancelBtn.addEventListener("click", () => {
  if (!requireApi()) return;
  window.pywebview.api.cancel();
  setStatus("Cancelling…");
});

/* ------------------------------------------------- events pushed by Python */

window.appEvents = {
  log(message, kind) {
    log(message, kind);
  },
  progress(done, total) {
    setProgress(done, total);
  },
  status(text) {
    setStatus(text);
  },
  finished(outcome) {
    setRunning(false);
    ui.bar.className = outcome === "ok" ? "bar done" : "bar failed";
    if (outcome === "ok") ui.bar.style.width = "100%";
  },
};

window.addEventListener("pywebviewready", () => {
  apiReady = true;
  log("Ready. Choose a video, preview a frame, then extract.");
});
