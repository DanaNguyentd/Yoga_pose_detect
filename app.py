"""
Desktop application: an HTML interface over the Python frame extractor.

Run it during development with:

    python app.py

The window is the operating system's own web view, so nothing here bundles a
browser. Everything the interface can ask for is a method on Api below: the
page calls `pywebview.api.<method>(...)` and receives a Promise. While a long
run is going the traffic reverses, and Python pushes progress into the page
through `window.appEvents`.

Layers stay as they were: extract_video_frames.py knows nothing about any
interface, web/ knows nothing about OpenCV, and this module is the seam.
"""

import base64
import json
import os
import sys
import threading

import cv2
import webview

import extract_video_frames as analysis

WINDOW_TITLE = "Yoga Pose — Frame Extractor"
WINDOW_SIZE = (1120, 860)
WINDOW_MIN_SIZE = (900, 680)

VIDEO_TYPES = ("Video files (*.mov;*.MOV;*.mp4;*.MP4;*.avi;*.m4v;*.mkv)", "All files (*.*)")


def resource_path(*parts):
    """
    Locate a bundled file whether running from source or from a frozen build.

    PyInstaller unpacks data files into a temporary directory and records it in
    sys._MEIPASS; from source the files sit next to this module.

    Returns:
        str: Absolute path to the requested resource
    """

    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


class Api:
    """Every operation the page is allowed to trigger."""

    def __init__(self):
        self.window = None
        self.cancel_requested = threading.Event()
        self.worker = None

        # Rebuilding the background is the slow step, so hold on to the last one
        self._background = None
        self._background_key = None

    # --------------------------------------------------------- page messaging

    def _emit(self, method, *args):
        """Call a window.appEvents method inside the page, from any thread."""

        if self.window is None:
            return
        payload = ", ".join(json.dumps(arg) for arg in args)
        self.window.evaluate_js(f"window.appEvents.{method}({payload})")

    def _log(self, message, kind=None):
        self._emit("log", str(message), kind)

    def _busy(self):
        return self.worker is not None and self.worker.is_alive()

    # ------------------------------------------------------------ file pickers

    def choose_video(self):
        """Open the operating system's file dialog. Returns the real path."""

        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False, file_types=VIDEO_TYPES
        )
        return {"path": result[0] if result else None}

    def choose_folder(self):
        """Open the operating system's folder dialog."""

        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return {"path": result[0] if result else None}

    # ---------------------------------------------------------------- preview

    def preview(self, settings):
        """
        Render one mid-video frame with the current settings.

        Args:
            settings (dict): The form, as sent by the page

        Returns:
            dict: {"ok": True, "image": "<data URI>"} or {"ok": False, "error": ...}
        """

        try:
            video_path = settings.get("video_path")
            if not video_path or not os.path.exists(video_path):
                return {"ok": False, "error": "That video file does not exist."}

            background = self._ensure_background(settings)
            if background is None:
                return {"ok": False, "error": "Could not read the video to rebuild the background."}

            frame = self._read_middle_frame(video_path)
            if frame is None:
                return {"ok": False, "error": "Could not read a frame from the video."}

            gray = analysis.to_grayscale(frame)
            mask = analysis.build_foreground_mask(
                gray, background, int(settings["bg_threshold"]), float(settings["min_area_pct"])
            )
            result = analysis.apply_mask(gray, mask, settings["bg_fill"])

            covered = float(mask.astype(bool).mean() * 100)
            strip = self._side_by_side(gray, background, result)

            ok, encoded = cv2.imencode(".png", strip)
            if not ok:
                return {"ok": False, "error": "Could not encode the preview image."}

            self._log(f"Preview ready. The subject covers {covered:.1f}% of the frame.")
            if covered < 0.5:
                self._log("Almost nothing was detected. Try a lower threshold.", "err")
            elif covered > 60:
                self._log("Most of the frame was kept. Try a higher threshold.", "err")

            data_uri = "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode()
            return {"ok": True, "image": data_uri, "coverage": covered}

        except Exception as error:
            return {"ok": False, "error": f"Preview failed: {error}"}

    # ------------------------------------------------------------- extraction

    def start(self, settings):
        """
        Begin a full extraction on a worker thread.

        Returning at once keeps the interface responsive; progress arrives
        later through window.appEvents.
        """

        if self._busy():
            return {"ok": False, "error": "Something is already running."}

        video_path = settings.get("video_path")
        if not video_path or not os.path.exists(video_path):
            return {"ok": False, "error": "That video file does not exist."}

        self.cancel_requested.clear()
        self.worker = threading.Thread(target=self._extract, args=(settings,), daemon=True)
        self.worker.start()
        return {"ok": True}

    def cancel(self):
        """Ask the running extraction to stop at the next frame."""

        self.cancel_requested.set()
        self._log("Cancel requested; stopping at the next frame.")
        return {"ok": True}

    def _extract(self, settings):
        """The worker body. Runs off the thread that serves the page."""

        try:
            succeeded = analysis.extract_frames(
                settings["video_path"],
                settings.get("output_dir") or None,
                settings.get("prefix") or "frame",
                remove_bg=bool(settings["remove_bg"]),
                bg_threshold=int(settings["bg_threshold"]),
                bg_samples=int(settings["bg_samples"]),
                bg_fill=settings["bg_fill"],
                min_area_pct=float(settings["min_area_pct"]),
                log=self._log,
                progress_callback=lambda done, total: self._emit("progress", done, total),
                should_cancel=self.cancel_requested.is_set,
            )

            if self.cancel_requested.is_set():
                self._emit("status", "Cancelled")
                self._emit("finished", "cancelled")
            elif succeeded:
                self._emit("status", "Finished")
                self._emit("finished", "ok")
            else:
                self._emit("status", "Failed, see the log")
                self._emit("finished", "failed")

        except Exception as error:
            self._log(f"Extraction failed: {error}", "err")
            self._emit("status", "Failed")
            self._emit("finished", "failed")

    # ----------------------------------------------------------- frame tools

    def _ensure_background(self, settings):
        """Reuse the cached background while the video and sample count hold."""

        key = (settings["video_path"], int(settings["bg_samples"]))
        if self._background is None or self._background_key != key:
            self._background = analysis.compute_background(
                settings["video_path"], int(settings["bg_samples"]), log=self._log
            )
            self._background_key = key if self._background is not None else None
        return self._background

    @staticmethod
    def _read_middle_frame(video_path):
        """Read from the middle of the video, where the subject is present."""

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        try:
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
            ret, frame = cap.read()
            return frame if ret else None
        finally:
            cap.release()

    @staticmethod
    def _side_by_side(original, background, result):
        """Join the three images into one strip for the preview."""

        import numpy as np

        def as_bgr(image):
            if image.ndim == 2:
                return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            if image.shape[2] == 4:  # transparent fill, shown over black
                return image[:, :, :3]
            return image

        panels = [as_bgr(original), as_bgr(background), as_bgr(result)]
        divider = np.full((panels[0].shape[0], 4, 3), 255, dtype=panels[0].dtype)

        joined = panels[0]
        for panel in panels[1:]:
            joined = cv2.hconcat([joined, divider, panel])
        return joined


def main():
    """Create the window and hand control to the web view."""

    api = Api()
    window = webview.create_window(
        WINDOW_TITLE,
        resource_path("web", "index.html"),
        js_api=api,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=WINDOW_MIN_SIZE,
    )
    api.window = window
    webview.start()


if __name__ == "__main__":
    main()
