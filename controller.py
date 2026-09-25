"""
Connects the frame extraction analysis to the tkinter interface.

Run this file to start the application:

    python controller.py

The analysis in extract_video_frames.py knows nothing about the interface, and
ui.py knows nothing about OpenCV. This module is the only place that imports
both. It also keeps the two apart in time: extraction runs on a worker thread,
posts what it has to say onto a queue, and the tkinter thread drains that queue
on a timer, because tkinter widgets may only be touched from the thread that
created them.
"""

import queue
import threading
import tkinter as tk

import cv2
import numpy as np

import extract_video_frames as analysis
from ui import ExtractorUI

POLL_INTERVAL_MS = 80


class ExtractorController:
    """Owns the window, the worker thread and the queue between them."""

    def __init__(self):
        self.root = tk.Tk()
        self.ui = ExtractorUI(self.root)
        self.ui.set_handlers(
            on_preview=self.handle_preview,
            on_start=self.handle_start,
            on_cancel=self.handle_cancel,
        )

        self.messages = queue.Queue()
        self.worker = None
        self.cancel_requested = threading.Event()

        # Reconstructing the background is the slow part, so remember the last
        # one; the key is what it depends on
        self._background = None
        self._background_key = None

    # ------------------------------------------------------------------ running

    def run(self):
        """Start draining the queue, then hand control to tkinter."""

        self.ui.log("Ready. Choose a video, preview one frame, then extract.")
        self.root.after(POLL_INTERVAL_MS, self._drain_queue)
        self.root.mainloop()

    def _busy(self):
        """True while a worker thread is still running."""

        return self.worker is not None and self.worker.is_alive()

    def _start_worker(self, target, settings):
        """Run target(settings) on a daemon thread, refusing to overlap runs."""

        if self._busy():
            self.ui.show_error("Something is already running. Wait for it to finish.")
            return

        self.cancel_requested.clear()
        self.ui.set_running(True)
        self.worker = threading.Thread(target=target, args=(settings,), daemon=True)
        self.worker.start()

    # ----------------------------------------------------------------- handlers

    def handle_preview(self, settings):
        """Render one frame with the current settings, without writing files."""

        self.ui.log("")
        self.ui.log("Preview: reconstructing the background...")
        self.ui.set_status("Building preview")
        self._start_worker(self._preview_worker, settings)

    def handle_start(self, settings):
        """Extract every frame to disk."""

        self.ui.log("")
        self.ui.log(f"Extracting {settings['video_path']}")
        self.ui.set_status("Extracting")
        self.ui.set_progress(0, 0)
        self._start_worker(self._extract_worker, settings)

    def handle_cancel(self):
        """Ask the worker to stop at the next frame."""

        if not self._busy():
            return
        self.cancel_requested.set()
        self.ui.set_status("Cancelling...")
        self.ui.log("Cancel requested; stopping at the next frame.")

    # ------------------------------------------------------------------ workers

    def _post(self, kind, *payload):
        """Queue a message for the tkinter thread."""

        self.messages.put((kind, payload))

    def _preview_worker(self, settings):
        """Build a before-and-after image for one frame. Runs off the UI thread."""

        try:
            background = self._ensure_background(settings)
            if background is None:
                self._post("error", "Could not read the video to build a background.")
                return

            frame = self._read_middle_frame(settings["video_path"])
            if frame is None:
                self._post("error", "Could not read a frame from the video.")
                return

            gray = analysis.to_grayscale(frame)
            mask = analysis.build_foreground_mask(
                gray, background, settings["bg_threshold"], settings["min_area_pct"]
            )
            result = analysis.apply_mask(gray, mask, settings["bg_fill"])

            covered = mask.astype(bool).mean() * 100
            comparison = self._side_by_side(gray, background, result)

            ok, encoded = cv2.imencode(".png", comparison)
            if not ok:
                self._post("error", "Could not encode the preview image.")
                return

            self._post(
                "preview",
                encoded.tobytes(),
                "original  ·  reconstructed background  ·  result",
            )
            self._post("log", f"Preview ready. The subject covers {covered:.1f}% of the frame.")
            if covered < 0.5:
                self._post("log", "Almost nothing was detected. Try a lower threshold.")
            elif covered > 60:
                self._post("log", "Most of the frame was kept. Try a higher threshold.")
            self._post("status", "Preview ready")

        except Exception as error:  # a worker thread must not die silently
            self._post("error", f"Preview failed: {error}")
        finally:
            self._post("finished")

    def _extract_worker(self, settings):
        """Run the full extraction, reporting progress. Runs off the UI thread."""

        try:
            succeeded = analysis.extract_frames(
                settings["video_path"],
                settings["output_dir"],
                settings["prefix"],
                remove_bg=settings["remove_bg"],
                bg_threshold=settings["bg_threshold"],
                bg_samples=settings["bg_samples"],
                bg_fill=settings["bg_fill"],
                min_area_pct=settings["min_area_pct"],
                log=lambda message: self._post("log", message),
                progress_callback=lambda done, total: self._post("progress", done, total),
                should_cancel=self.cancel_requested.is_set,
            )

            if self.cancel_requested.is_set():
                self._post("status", "Cancelled")
            elif succeeded:
                self._post("status", "Finished")
            else:
                self._post("status", "Failed, see the log")

        except Exception as error:
            self._post("error", f"Extraction failed: {error}")
        finally:
            self._post("finished")

    # -------------------------------------------------------------- frame tools

    def _ensure_background(self, settings):
        """Reuse the cached background when the video and sample count match."""

        key = (settings["video_path"], settings["bg_samples"])
        if self._background is None or self._background_key != key:
            self._background = analysis.compute_background(
                settings["video_path"],
                settings["bg_samples"],
                log=lambda message: self._post("log", message),
            )
            self._background_key = key if self._background is not None else None
        return self._background

    @staticmethod
    def _read_middle_frame(video_path):
        """Read a frame from the middle of the video, where the subject is present."""

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
        """Join three images into one strip, as 3-channel BGR for display."""

        def as_bgr(image):
            if image.ndim == 2:
                return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            if image.shape[2] == 4:  # alpha fill: show it over black
                return image[:, :, :3]
            return image

        panels = [as_bgr(original), as_bgr(background), as_bgr(result)]
        divider = np.full((panels[0].shape[0], 4, 3), 255, dtype=panels[0].dtype)
        joined = panels[0]
        for panel in panels[1:]:
            joined = cv2.hconcat([joined, divider, panel])
        return joined

    # ----------------------------------------------------------- queue draining

    def _drain_queue(self):
        """Apply queued messages to the widgets. Runs on the tkinter thread."""

        try:
            while True:
                kind, payload = self.messages.get_nowait()
                self._apply(kind, payload)
        except queue.Empty:
            pass

        self.root.after(POLL_INTERVAL_MS, self._drain_queue)

    def _apply(self, kind, payload):
        """Dispatch one queued message to the view."""

        if kind == "log":
            self.ui.log(payload[0])
        elif kind == "status":
            self.ui.set_status(payload[0])
        elif kind == "progress":
            self.ui.set_progress(payload[0], payload[1])
        elif kind == "preview":
            self.ui.show_preview(payload[0], payload[1])
        elif kind == "error":
            self.ui.log(payload[0])
            self.ui.set_status("Failed")
            self.ui.show_error(payload[0])
        elif kind == "finished":
            self.ui.set_running(False)


def main():
    """Entry point."""

    ExtractorController().run()


if __name__ == "__main__":
    main()
