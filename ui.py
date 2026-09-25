"""
Tkinter user interface for the frame extraction tool.

This module is the view and nothing else: it builds the window, collects what
the user typed, and calls the handlers the controller installs. It imports no
OpenCV and no extraction code, so the layout can be reworked without touching
the analysis, and the analysis can be run headless without importing tkinter.
"""

import io
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

PREVIEW_MAX_WIDTH = 760
PREVIEW_MAX_HEIGHT = 300


class ExtractorUI:
    """The application window, wired to handlers supplied by the controller."""

    def __init__(self, root):
        self.root = root
        self.root.title("Yoga Pose — Frame Extractor")
        self.root.minsize(820, 720)

        # Handlers are installed later by set_handlers
        self._on_preview = None
        self._on_start = None
        self._on_cancel = None

        # Keeps a reference to the displayed image; tkinter discards it otherwise
        self._preview_image = None

        self._build_widgets()

    # ------------------------------------------------------------------ layout

    def _build_widgets(self):
        """Create every widget, top to bottom."""

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        self._build_input_section(outer)
        self._build_options_section(outer)
        self._build_action_section(outer)
        self._build_preview_section(outer)
        self._build_log_section(outer)

    def _build_input_section(self, parent):
        """Video file, output directory and filename prefix."""

        box = ttk.LabelFrame(parent, text="Input and output", padding=10)
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)

        self.video_var = tk.StringVar()
        ttk.Label(box, text="Video file").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(box, textvariable=self.video_var).grid(
            row=0, column=1, sticky="ew", padx=8
        )
        ttk.Button(box, text="Browse...", command=self._browse_video).grid(row=0, column=2)

        self.output_var = tk.StringVar()
        ttk.Label(box, text="Output folder").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(box, textvariable=self.output_var).grid(
            row=1, column=1, sticky="ew", padx=8
        )
        ttk.Button(box, text="Browse...", command=self._browse_output).grid(row=1, column=2)
        ttk.Label(box, text="Left empty, a timestamped folder is created next to the video",
                  foreground="gray40").grid(row=2, column=1, sticky="w", padx=8)

        self.prefix_var = tk.StringVar(value="frame")
        ttk.Label(box, text="Filename prefix").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(box, textvariable=self.prefix_var, width=18).grid(
            row=3, column=1, sticky="w", padx=8
        )

    def _build_options_section(self, parent):
        """Background removal settings."""

        box = ttk.LabelFrame(parent, text="Background removal", padding=10)
        box.pack(fill="x", pady=(10, 0))

        self.remove_bg_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            box,
            text="Remove the static background",
            variable=self.remove_bg_var,
            command=self._sync_option_state,
        ).grid(row=0, column=0, columnspan=4, sticky="w")

        self.threshold_var = tk.IntVar(value=25)
        self.samples_var = tk.IntVar(value=60)
        self.fill_var = tk.StringVar(value="black")
        self.min_area_var = tk.DoubleVar(value=0.5)

        ttk.Label(box, text="Threshold").grid(row=1, column=0, sticky="w", pady=4)
        self.threshold_spin = ttk.Spinbox(
            box, from_=0, to=255, textvariable=self.threshold_var, width=8
        )
        self.threshold_spin.grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(box, text="0 selects it automatically; lower keeps more of the subject",
                  foreground="gray40").grid(row=1, column=2, columnspan=2, sticky="w")

        ttk.Label(box, text="Background samples").grid(row=2, column=0, sticky="w", pady=4)
        self.samples_spin = ttk.Spinbox(
            box, from_=5, to=500, textvariable=self.samples_var, width=8
        )
        self.samples_spin.grid(row=2, column=1, sticky="w", padx=8)
        ttk.Label(box, text="Frames sampled to reconstruct the empty scene",
                  foreground="gray40").grid(row=2, column=2, columnspan=2, sticky="w")

        ttk.Label(box, text="Replace background with").grid(row=3, column=0, sticky="w", pady=4)
        self.fill_combo = ttk.Combobox(
            box,
            textvariable=self.fill_var,
            values=["black", "white", "alpha"],
            state="readonly",
            width=10,
        )
        self.fill_combo.grid(row=3, column=1, sticky="w", padx=8)

        ttk.Label(box, text="Smallest blob kept (%)").grid(row=4, column=0, sticky="w", pady=4)
        self.min_area_spin = ttk.Spinbox(
            box, from_=0.0, to=50.0, increment=0.1, textvariable=self.min_area_var, width=8
        )
        self.min_area_spin.grid(row=4, column=1, sticky="w", padx=8)
        ttk.Label(box, text="Discards specks of noise below this share of the frame",
                  foreground="gray40").grid(row=4, column=2, columnspan=2, sticky="w")

    def _build_action_section(self, parent):
        """Buttons, progress bar and status line."""

        box = ttk.Frame(parent)
        box.pack(fill="x", pady=(10, 0))

        self.preview_button = ttk.Button(box, text="Preview one frame", command=self._fire_preview)
        self.preview_button.pack(side="left")
        self.start_button = ttk.Button(box, text="Extract all frames", command=self._fire_start)
        self.start_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(
            box, text="Cancel", command=self._fire_cancel, state="disabled"
        )
        self.cancel_button.pack(side="left")

        self.progress = ttk.Progressbar(parent, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(10, 2))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(parent, textvariable=self.status_var, foreground="gray30").pack(anchor="w")

    def _build_preview_section(self, parent):
        """Where a sampled frame is shown before committing to a full run."""

        box = ttk.LabelFrame(parent, text="Preview", padding=10)
        box.pack(fill="x", pady=(10, 0))

        self.preview_label = ttk.Label(
            box,
            text="Preview one frame to check the settings before extracting everything",
            foreground="gray40",
            anchor="center",
        )
        self.preview_label.pack(fill="both")

    def _build_log_section(self, parent):
        """Scrolling message log."""

        box = ttk.LabelFrame(parent, text="Log", padding=10)
        box.pack(fill="both", expand=True, pady=(10, 0))

        self.log_text = tk.Text(box, height=10, wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(box, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    # ---------------------------------------------------------------- handlers

    def set_handlers(self, on_preview=None, on_start=None, on_cancel=None):
        """
        Install the controller's callbacks.

        Args:
            on_preview (callable): Called with a settings dict
            on_start (callable): Called with a settings dict
            on_cancel (callable): Called with no arguments
        """

        self._on_preview = on_preview
        self._on_start = on_start
        self._on_cancel = on_cancel

    def _browse_video(self):
        path = filedialog.askopenfilename(
            title="Choose a video file",
            filetypes=[("Video files", "*.mov *.MOV *.mp4 *.MP4 *.avi *.m4v"),
                       ("All files", "*.*")],
        )
        if path:
            self.video_var.set(path)

    def _browse_output(self):
        path = filedialog.askdirectory(title="Choose an output folder")
        if path:
            self.output_var.set(path)

    def _fire_preview(self):
        self._fire(self._on_preview)

    def _fire_start(self):
        self._fire(self._on_start)

    def _fire_cancel(self):
        if self._on_cancel is not None:
            self._on_cancel()

    def _fire(self, handler):
        """Validate the form, then hand the settings to a handler."""

        if handler is None:
            return
        try:
            settings = self.get_settings()
        except ValueError as error:
            self.show_error(str(error))
            return
        handler(settings)

    # -------------------------------------------------------------- view state

    def get_settings(self):
        """
        Collect the form into a settings dict.

        Returns:
            dict: Keys matching extract_frames' keyword arguments, plus
                  video_path and output_dir

        Raises:
            ValueError: If a field is empty or not a number
        """

        video_path = self.video_var.get().strip()
        if not video_path:
            raise ValueError("Choose a video file first.")

        prefix = self.prefix_var.get().strip()
        if not prefix:
            raise ValueError("The filename prefix cannot be empty.")

        try:
            threshold = int(self.threshold_var.get())
            samples = int(self.samples_var.get())
            min_area = float(self.min_area_var.get())
        except (tk.TclError, ValueError):
            raise ValueError("Threshold, samples and smallest blob must be numbers.")

        if not 0 <= threshold <= 255:
            raise ValueError("Threshold must be between 0 and 255.")
        if samples < 5:
            raise ValueError("Use at least 5 background samples.")
        if not 0 <= min_area <= 50:
            raise ValueError("Smallest blob must be between 0 and 50 percent.")

        return {
            "video_path": video_path,
            "output_dir": self.output_var.get().strip() or None,
            "prefix": prefix,
            "remove_bg": bool(self.remove_bg_var.get()),
            "bg_threshold": threshold,
            "bg_samples": samples,
            "bg_fill": self.fill_var.get(),
            "min_area_pct": min_area,
        }

    def _sync_option_state(self):
        """Grey out the background settings when removal is switched off."""

        state = "normal" if self.remove_bg_var.get() else "disabled"
        for widget in (self.threshold_spin, self.samples_spin, self.min_area_spin):
            widget.configure(state=state)
        self.fill_combo.configure(state="readonly" if state == "normal" else "disabled")
        self.preview_button.configure(state=state)

    def set_running(self, running):
        """Switch the window between idle and working."""

        self.start_button.configure(state="disabled" if running else "normal")
        self.preview_button.configure(
            state="disabled" if running or not self.remove_bg_var.get() else "normal"
        )
        self.cancel_button.configure(state="normal" if running else "disabled")

    def log(self, message):
        """Append a line to the log and scroll to it."""

        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_status(self, message):
        """Replace the one-line status under the progress bar."""

        self.status_var.set(message)

    def set_progress(self, done, total):
        """Move the progress bar; a total of 0 or less means indeterminate."""

        if total and total > 0:
            self.progress.configure(mode="determinate", maximum=total, value=done)
        else:
            self.progress.configure(mode="determinate", maximum=100, value=0)

    def show_preview(self, png_bytes, caption=None):
        """
        Display a PNG, scaled down to fit the preview area.

        Args:
            png_bytes (bytes): Encoded PNG image
            caption (str): Optional line shown instead of the placeholder text
        """

        image = Image.open(io.BytesIO(png_bytes))
        scale = min(
            PREVIEW_MAX_WIDTH / image.width, PREVIEW_MAX_HEIGHT / image.height, 1.0
        )
        if scale < 1.0:
            image = image.resize(
                (int(image.width * scale), int(image.height * scale)), Image.LANCZOS
            )

        self._preview_image = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self._preview_image, text=caption or "",
                                     compound="bottom")

    def show_error(self, message):
        """Report a problem the user needs to fix."""

        messagebox.showerror("Frame Extractor", message)

    def schedule(self, delay_ms, function):
        """Run a function on the tkinter thread after a delay."""

        self.root.after(delay_ms, function)
