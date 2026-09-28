"""
Desktop application: an HTML interface over the Python frame extractor.

Run it during development with:

    python app.py            normal run
    python app.py --debug    adds developer tools for working on web/

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
import mimetypes
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import webview

import extract_video_frames as analysis

WINDOW_TITLE = "Yoga Pose — Frame Extractor"
WINDOW_SIZE = (1120, 860)
WINDOW_MIN_SIZE = (900, 680)

VIDEO_TYPES = ("Video files (*.mov;*.MOV;*.mp4;*.MP4;*.avi;*.m4v;*.mkv)", "All files (*.*)")


class _MediaHandler(BaseHTTPRequestHandler):
    """Serves one video file, with the byte ranges a player needs to seek."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        """Keep the server out of the console."""

    def _reject(self, code=404):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self._respond(body=False)

    def do_GET(self):
        self._respond(body=True)

    def _respond(self, body):
        path = self.server.media_path
        if self.path != self.server.media_route or not path or not os.path.exists(path):
            self._reject()
            return

        size = os.path.getsize(path)
        content_type = (mimetypes.guess_type(path)[0] or "video/mp4")
        start, end = 0, size - 1
        partial = False

        # "Range: bytes=start-end" is how a player seeks without fetching all
        header = self.headers.get("Range")
        if header and header.startswith("bytes="):
            first, _, last = header[len("bytes="):].partition("-")
            try:
                if first:
                    start = int(first)
                    end = int(last) if last else size - 1
                else:  # a suffix range, "the last N bytes"
                    start = max(0, size - int(last))
                partial = True
            except ValueError:
                partial = False
            if start >= size or end >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

        if not body:
            return

        remaining = length
        with open(path, "rb") as handle:
            handle.seek(start)
            while remaining > 0:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return  # the player moved on, which is normal while seeking
                remaining -= len(chunk)


class MediaServer:
    """
    A loopback web server that hands the page the chosen video.

    The window loads its own files from disk, and a web view will not let a
    page opened that way fetch other local files, so a <video> pointed at the
    video's path stays blank. Serving it over the loopback interface solves
    that and brings byte ranges with it, which is what makes seeking work.

    It listens on 127.0.0.1 only, on a port the system picks, and answers on
    one unguessable path that changes with every video.
    """

    def __init__(self):
        self._server = None
        self._thread = None

    def serve(self, path):
        """Start serving a file, replacing whatever was being served. Returns a URL."""

        if self._server is None:
            self._server = ThreadingHTTPServer(("127.0.0.1", 0), _MediaHandler)
            self._server.daemon_threads = True
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()

        self._server.media_path = path
        self._server.media_route = f"/{secrets.token_urlsafe(16)}"
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}{self._server.media_route}"

    def stop(self):
        """Shut the server down, if one was ever started."""

        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


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
        self.media = MediaServer()

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

    def probe(self, video_path):
        """
        Report a video's shape so the page can show what a run would produce.

        Returns:
            dict: {"ok": True, "fps", "frames", "duration", "width", "height"}
                  or {"ok": False, "error": ...}
        """

        if not video_path or not os.path.exists(video_path):
            return {"ok": False, "error": "That video file does not exist."}

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {"ok": False, "error": "Could not open that video."}
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
            frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            return {
                "ok": True,
                "fps": fps,
                "frames": frames,
                "duration": frames / fps if fps > 0 and frames > 0 else 0.0,
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            }
        finally:
            cap.release()

    def serve_video(self, video_path):
        """
        Publish a video on the loopback interface so the page can play it.

        Returns:
            dict: {"ok": True, "url": ...} or {"ok": False, "error": ...}
        """

        if not video_path or not os.path.exists(video_path):
            return {"ok": False, "error": "That video file does not exist."}
        try:
            return {"ok": True, "url": self.media.serve(video_path)}
        except Exception as error:
            return {"ok": False, "error": f"Could not serve the video: {error}"}

    def frame_at(self, video_path, seconds):
        """
        Return one untouched frame from a moment in the video.

        The page uses this to show where the chosen range starts and ends, and
        as a scrubber when the web view cannot play the file itself, which
        happens with codecs it does not know. OpenCV decodes it either way.

        Returns:
            dict: {"ok": True, "image": "<data URI>"} or {"ok": False, ...}
        """

        if not video_path or not os.path.exists(video_path):
            return {"ok": False, "error": "That video file does not exist."}

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {"ok": False, "error": "Could not open that video."}
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
            if fps > 0:
                # Seeking alone lands on the keyframe before the moment asked
                # for, which on phone footage can be many seconds early
                analysis.seek_to_frame(cap, max(0, int(float(seconds) * fps)),
                                       log=lambda message: None)
            ret, frame = cap.read()
            if not ret:
                return {"ok": False, "error": "Could not read a frame there."}

            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                return {"ok": False, "error": "Could not encode that frame."}
            return {
                "ok": True,
                "image": "data:image/jpeg;base64,"
                         + base64.b64encode(encoded.tobytes()).decode(),
            }
        finally:
            cap.release()

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
                frame_step=int(settings.get("frame_step") or 1),
                interval_seconds=settings.get("interval_seconds") or None,
                image_format=settings.get("image_format") or "png",
                start_seconds=settings.get("start_seconds"),
                end_seconds=settings.get("end_seconds"),
                save_background=bool(settings.get("save_background")),
                log=self._log,
                progress_callback=lambda done, total: self._emit("progress", done, total),
                should_cancel=self.cancel_requested.is_set,
            )

            if self.cancel_requested.is_set():
                self._emit("status", "Cancelled", "")
                self._emit("finished", "cancelled")
            elif succeeded:
                self._emit("status", "Finished", "done")
                self._emit("finished", "ok")
            else:
                self._emit("status", "Failed, see the log", "failed")
                self._emit("finished", "failed")

        except Exception as error:
            self._log(f"Extraction failed: {error}", "err")
            self._emit("status", "Failed", "failed")
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
                analysis.seek_to_frame(cap, total // 2, log=lambda message: None)
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
    """
    Create the window and hand control to the web view.

    Passing --debug turns on the platform inspector, so the interface can be
    reloaded and its styles poked at without restarting anything.
    """

    debug = "--debug" in sys.argv

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
    webview.start(debug=debug)


if __name__ == "__main__":
    main()
