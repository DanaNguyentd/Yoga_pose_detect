"""
Tests for the analysis, run with:

    python3 tests/test_analysis.py

Nothing here needs a video file: the decisions worth testing are about numbers
and names, and the masking works on arrays that can be built by hand. Point
the optional environment variable TEST_VIDEO at a real file to also run the
end to end extraction:

    TEST_VIDEO=test/IMG_8803.MOV python3 tests/test_analysis.py
"""

import os
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extract_video_frames as analysis

FAILURES = []
QUIET = lambda message: None


def check(label, got, want):
    """Compare and record, so one failure does not hide the rest."""

    if got == want:
        print(f"  ok   {label}")
    else:
        FAILURES.append(label)
        print(f" FAIL  {label}: got {got!r}, want {want!r}")


def section(title):
    print(f"\n{title}")


# --------------------------------------------------------------- file formats

section("Image formats")

check("png", analysis.resolve_image_format("png", "black", QUIET)[0], ".png")
check("jpg", analysis.resolve_image_format("jpg", "black", QUIET)[0], ".jpg")
check("webp", analysis.resolve_image_format("webp", "black", QUIET)[0], ".webp")
check("jpeg is an alias for jpg",
      analysis.resolve_image_format("JPEG", "black", QUIET)[0], ".jpg")
check("a leading dot is tolerated",
      analysis.resolve_image_format(".PNG", "black", QUIET)[0], ".png")
check("an unknown format falls back to png",
      analysis.resolve_image_format("gif", "black", QUIET)[0], ".png")
check("transparency forces png over jpg",
      analysis.resolve_image_format("jpg", "alpha", QUIET)[0], ".png")
check("transparency leaves webp alone",
      analysis.resolve_image_format("webp", "alpha", QUIET)[0], ".webp")
check("jpg carries its quality setting",
      analysis.resolve_image_format("jpg", "black", QUIET)[1][1], 95)


# ---------------------------------------------------------------- frame steps

section("How often a frame is kept")

check("every frame by default", analysis.resolve_frame_step(30, 1, None, QUIET), 1)
check("one per second at 30 fps", analysis.resolve_frame_step(30, 1, 1, QUIET), 30)
check("one per half second", analysis.resolve_frame_step(30, 1, 0.5, QUIET), 15)
check("a frame step is taken as given", analysis.resolve_frame_step(30, 10, None, QUIET), 10)
check("seconds win over a frame step", analysis.resolve_frame_step(30, 10, 1, QUIET), 30)
check("no frame rate means every frame", analysis.resolve_frame_step(0, 1, 1, QUIET), 1)
check("never less than one frame", analysis.resolve_frame_step(30, 1, 0.001, QUIET), 1)

# Python rounds halves to even and JavaScript rounds them up. The interface
# predicts how many images a run will write, so the two must agree.
check("a half is rounded up, as the interface does",
      analysis.resolve_frame_step(25, 1, 0.5, QUIET), 13)


# --------------------------------------------------------------- frame ranges

section("Which part of the video is read")

check("the whole video by default",
      analysis.resolve_frame_range(30, 120, None, None, QUIET), (0, 120))
check("a span in the middle",
      analysis.resolve_frame_range(30, 120, 1, 3, QUIET), (30, 90))
check("a start with no end runs to the end",
      analysis.resolve_frame_range(30, 120, 2, None, QUIET), (60, 120))
check("an end with no start begins at the beginning",
      analysis.resolve_frame_range(30, 120, None, 1, QUIET), (0, 30))
check("an end past the video is clamped",
      analysis.resolve_frame_range(30, 120, 1, 999, QUIET), (30, 120))
check("an end before its start falls back to everything",
      analysis.resolve_frame_range(30, 120, 3, 1, QUIET), (0, 120))
check("no frame rate falls back to everything",
      analysis.resolve_frame_range(0, 120, 1, 3, QUIET), (0, 120))


# -------------------------------------------------------------- output folder

section("Where frames are written")

folder = analysis.default_output_dir("/videos/IMG_8803.MOV")
check("beside the video", os.path.dirname(folder), "/videos")
check("named after it", os.path.basename(folder).startswith("frame_result_IMG_8803_"), True)
check("always absolute", os.path.isabs(analysis.default_output_dir("clip.MOV")), True)


# --------------------------------------------------------------- the masking

section("Separating the subject from the background")

# A background with some texture, and a subject standing in front of it
background = np.tile(np.linspace(40, 120, 200, dtype=np.uint8), (150, 1))
frame = background.copy()
frame[40:110, 80:120] = 240                      # the subject
frame[0, 0] = min(255, int(background[0, 0]) + 40)   # one stray bright pixel

mask = analysis.build_foreground_mask(frame, background, threshold=25, min_area_pct=0.5)

check("the subject is found", bool(mask[70, 100]), True)
check("the background is not", bool(mask[10, 180]), False)
check("a single stray pixel is discarded as noise", bool(mask[0, 0]), False)

covered = mask.astype(bool).mean() * 100
check("roughly the right area is covered", 8 < covered < 16, True)

on_black = analysis.apply_mask(frame, mask, "black")
check("black fill empties the background", int(on_black[10, 180]), 0)
check("black fill keeps the subject", int(on_black[70, 100]), 240)

on_white = analysis.apply_mask(frame, mask, "white")
check("white fill fills with white", int(on_white[10, 180]), 255)

transparent = analysis.apply_mask(frame, mask, "alpha")
check("alpha fill has four channels", transparent.shape[2], 4)
check("alpha is clear where the background was", int(transparent[10, 180, 3]), 0)
check("alpha is solid on the subject", int(transparent[70, 100, 3]), 255)

# An automatic threshold should reach the same conclusion on an easy frame
auto = analysis.build_foreground_mask(frame, background, threshold=0, min_area_pct=0.5)
check("an automatic threshold finds it too", bool(auto[70, 100]), True)

check("grayscale input is passed through unchanged",
      analysis.to_grayscale(frame).shape, frame.shape)
check("colour input becomes one channel",
      analysis.to_grayscale(np.zeros((10, 10, 3), np.uint8)).shape, (10, 10))


# ------------------------------------------------- the whole thing, if we can

video = os.environ.get("TEST_VIDEO")
if video and os.path.exists(video):
    section(f"End to end, on {video}")
    out = tempfile.mkdtemp(prefix="frame_test_")
    try:
        ok = analysis.extract_frames(
            video, out, "frame", bg_samples=15, interval_seconds=1,
            start_seconds=0, end_seconds=3, save_background=True, log=QUIET,
        )
        written = sorted(os.listdir(out))
        check("it ran", ok, True)
        check("the background was kept", "background.png" in written, True)
        check("some frames were written", len(written) > 1, True)
        check("they are named after their frame",
              all(f.startswith(("frame_", "background")) for f in written), True)
    finally:
        shutil.rmtree(out, ignore_errors=True)
else:
    section("End to end")
    print("  skipped, set TEST_VIDEO to a video file to include it")


print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all checks passed")
