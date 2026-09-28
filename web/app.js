/* Front end for the frame extractor.
 *
 * Everything here is presentation and input collection. The analysis lives in
 * Python: this file calls it through `pywebview.api`, which returns a Promise,
 * and Python calls back into `window.appEvents` while a long run is going. */

const el = (id) => document.getElementById(id);

const ui = {
  videoPath: el("videoPath"),
  outputPath: el("outputPath"),
  removeBg: el("removeBg"),
  bgOptions: el("bgOptions"),
  threshold: el("threshold"),
  samples: el("samples"),
  minArea: el("minArea"),
  prefix: el("prefix"),
  format: el("format"),
  example: el("example"),
  formatHint: el("formatHint"),
  interval: el("interval"),
  frameStep: el("frameStep"),
  stepField: el("stepField"),
  estimate: el("estimate"),
  videoInfo: el("videoInfo"),
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
let video = null;   // what probe() last reported about the chosen file

/* ------------------------------------------------------------------ helpers */

function log(message, kind) {
  const line = document.createElement("div");
  if (kind) line.className = kind;
  line.textContent = message;
  ui.log.appendChild(line);
  ui.log.scrollTop = ui.log.scrollHeight;
}

/* Each run starts with an empty log, so what is on screen always describes
 * the preview or the extraction being looked at, not the ones before it. */
function clearLog() {
  ui.log.textContent = "";
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

/* "every frame" is 0 seconds, "every N frames" is the slider, anything else
 * is a number of seconds. The analysis turns seconds into a frame step once
 * it knows the real frame rate. */
function sampling() {
  const choice = ui.interval.value;
  if (choice === "custom") return { frame_step: Number(ui.frameStep.value), interval_seconds: null };
  if (choice === "0") return { frame_step: 1, interval_seconds: null };
  return { frame_step: 1, interval_seconds: Number(choice) };
}

/* How many images a run would write, given what probe() told us. */
function plannedCount() {
  if (!video || !video.frames) return null;
  const { frame_step, interval_seconds } = sampling();
  let step = frame_step;
  if (interval_seconds) {
    if (!video.fps) return null;
    step = Math.max(1, Math.round(video.fps * interval_seconds));
  }
  return { count: Math.ceil(video.frames / step), step };
}

function updateEstimate() {
  const planned = plannedCount();
  if (!planned) {
    ui.estimate.hidden = true;
    return;
  }
  const { count, step } = planned;
  const every = step === 1 ? "every frame" : `one frame in every ${step}`;
  ui.estimate.innerHTML =
    `This will write <strong>${count.toLocaleString()}</strong> images ` +
    `(${every} of ${video.frames.toLocaleString()}).`;
  ui.estimate.classList.toggle("heavy", count > 2000);
  ui.estimate.hidden = false;
}

function describeVideo() {
  if (!video) {
    ui.videoInfo.hidden = true;
    return;
  }
  const mins = Math.floor(video.duration / 60);
  const secs = Math.round(video.duration % 60);
  const length = video.duration ? ` · ${mins}:${String(secs).padStart(2, "0")}` : "";
  ui.videoInfo.textContent =
    `${video.width}×${video.height} · ${video.fps.toFixed(1)} fps · ` +
    `${video.frames.toLocaleString()} frames${length}`;
  ui.videoInfo.hidden = false;
}

function settings() {
  return {
    ...sampling(),
    video_path: ui.videoPath.value.trim(),
    output_dir: ui.outputPath.value.trim() || null,
    prefix: ui.prefix.value.trim() || "frame",
    image_format: effectiveFormat(),
    remove_bg: ui.removeBg.checked,
    bg_threshold: Number(ui.threshold.value),
    bg_samples: Number(ui.samples.value),
    bg_fill: ui.fill.querySelector(".seg.active").dataset.value,
    min_area_pct: Number(ui.minArea.value),
  };
}

/* JPEG has no alpha channel. The page disables the transparent option while
 * JPEG is chosen, so the combination cannot be made in the first place; this
 * stays as a guard, and Python keeps its own fallback for the command line. */
function effectiveFormat() {
  const chosen = ui.format.value;
  const transparent = ui.fill.querySelector(".seg.active").dataset.value === "alpha";
  return transparent && chosen === "jpg" ? "png" : chosen;
}

/* Disable the choices the chosen format cannot honour, and move off one that
 * is already selected rather than leaving an active button disabled. */
function syncFormatConstraints() {
  const isJpeg = ui.format.value === "jpg";
  const transparent = ui.fill.querySelector('[data-value="alpha"]');

  transparent.disabled = isJpeg;
  transparent.title = isJpeg ? "JPEG cannot store transparency" : "";

  if (isJpeg && transparent.classList.contains("active")) {
    transparent.classList.remove("active");
    ui.fill.querySelector('[data-value="black"]').classList.add("active");
    log("Transparent is not available with JPEG. Switched to black.");
  }
}

const FORMAT_NOTES = {
  png: "PNG is lossless and keeps transparency.",
  jpg: "JPEG files are far smaller, but lossy and cannot hold transparency.",
  webp: "WebP is small like JPEG and can still hold transparency.",
};

/* The digits are padded to the width of the video's frame count, so the
 * example can only be exact once a video has been probed. */
function updateExample() {
  const format = effectiveFormat();
  const overridden = format !== ui.format.value;
  const width = video && video.frames ? String(video.frames).length : 6;
  // Frame 0 is always saved, whatever the interval, so it is a name the
  // user will really see
  const name = `${ui.prefix.value.trim() || "frame"}_${"0".padStart(width, "0")}.${format}`;

  ui.example.innerHTML = `Saved as <code>${name}</code>`;
  ui.example.classList.toggle("warn", overridden);
  ui.formatHint.textContent = overridden
    ? "JPEG cannot store transparency, so PNG will be used instead."
    : FORMAT_NOTES[ui.format.value];
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
  if (!button || button.disabled) return;
  ui.fill.querySelectorAll(".seg").forEach((b) => b.classList.remove("active"));
  button.classList.add("active");
  updateExample();
});

ui.prefix.addEventListener("input", updateExample);
ui.format.addEventListener("change", () => {
  syncFormatConstraints();
  updateExample();
});

ui.interval.addEventListener("change", () => {
  const custom = ui.interval.value === "custom";
  ui.stepField.hidden = !custom;
  updateEstimate();
});

ui.frameStep.addEventListener("input", () => {
  el("stepValue").textContent = ui.frameStep.value;
  updateEstimate();
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

    const info = await window.pywebview.api.probe(result.path);
    video = info.ok ? info : null;
    describeVideo();
    updateEstimate();
    updateExample();
    if (!info.ok) log(info.error, "err");
  }
});

el("chooseOutput").addEventListener("click", async () => {
  if (!requireApi()) return;
  const result = await window.pywebview.api.choose_folder();
  if (result.path) ui.outputPath.value = result.path;
});

ui.previewBtn.addEventListener("click", async () => {
  if (!requireApi() || !requireVideo()) return;
  clearLog();
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
  clearLog();
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
  syncFormatConstraints();
  updateExample();
  log("Ready. Choose a video, preview a frame, then extract.");
});
