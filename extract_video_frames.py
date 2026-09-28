"""
Extract all frames from a .MOV video file and save them as images.
Handles black and white (grayscale) video files.

For footage shot with a fixed camera against an unchanging background, the
static background can be removed before each frame is saved: a median
background is built from frames sampled across the whole video, then every
frame is compared against it and only the moving subject is kept.
"""

import cv2
import math
import numpy as np
import os
import argparse
from datetime import datetime


def compute_background(video_path, sample_count=60, log=None):
    """
    Build a static background image by taking the per-pixel median of frames
    sampled evenly across the video.

    The subject moves between samples while the background does not, so the
    median of enough samples is the empty scene with the subject removed.

    Args:
        video_path (str): Path to the input video file
        sample_count (int): How many frames to sample (default: 60)
        log (callable): Where messages go, defaults to print

    Returns:
        numpy.ndarray: Grayscale background image, or None on failure
    """

    emit = log if log is not None else print
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        emit(f"Error: Could not open video file {video_path}")
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    samples = []

    if total_frames > 0:
        # Seek to evenly spaced positions so samples span the whole video
        indices = np.linspace(0, total_frames - 1, min(sample_count, total_frames))
        for index in indices.astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
            ret, frame = cap.read()
            if ret:
                samples.append(to_grayscale(frame))
    else:
        # Frame count unavailable (some containers): just read from the start
        while len(samples) < sample_count:
            ret, frame = cap.read()
            if not ret:
                break
            samples.append(to_grayscale(frame))

    cap.release()

    if not samples:
        emit("Error: Could not read any frames to build the background")
        return None

    emit(f"  Background built from {len(samples)} sampled frames")
    return np.median(np.stack(samples), axis=0).astype(np.uint8)


def to_grayscale(frame):
    """Convert a frame to single-channel grayscale, leaving it alone if already so."""

    if len(frame.shape) == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame


# Leading part of the folder frames go to when none is chosen
DEFAULT_OUTPUT_PREFIX = "frame_result"


def default_output_dir(video_path):
    """
    Where frames go when no folder was chosen.

    Beside the video, in a folder naming the video and the moment of the run,
    so extracting a second video, or the same one again with other settings,
    never mixes its images in with an earlier batch.

    Args:
        video_path (str): The video being read

    Returns:
        str: An absolute path, for example
             /Users/me/clips/frame_result_IMG_8803_20260928_143015
    """

    folder = os.path.dirname(os.path.abspath(video_path))
    name = os.path.splitext(os.path.basename(video_path))[0]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(folder, f"{DEFAULT_OUTPUT_PREFIX}_{name}_{stamp}")

# The image formats the tool writes. PNG is lossless and keeps transparency;
# JPEG is much smaller but lossy and flattens any alpha; WebP is small and
# still carries alpha.
IMAGE_FORMATS = {
    "png": (".png", []),
    "jpg": (".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95]),
    "webp": (".webp", [cv2.IMWRITE_WEBP_QUALITY, 95]),
}

FORMATS_WITHOUT_ALPHA = ("jpg",)


def resolve_image_format(image_format="png", fill="black", log=None):
    """
    Choose the file extension and the encoder settings to save with.

    Args:
        image_format (str): One of the keys of IMAGE_FORMATS
        fill (str): The background fill, because "alpha" needs a format that
                    can carry transparency
        log (callable): Where messages go, defaults to print

    Returns:
        tuple: (extension including the dot, list of cv2.imwrite parameters)
    """

    emit = log if log is not None else print
    chosen = (image_format or "png").lower().lstrip(".")
    if chosen == "jpeg":
        chosen = "jpg"

    if chosen not in IMAGE_FORMATS:
        emit(f"  Warning: unknown image format '{image_format}'. Using PNG.")
        chosen = "png"

    # A transparent background cannot survive a format with no alpha channel
    if fill == "alpha" and chosen in FORMATS_WITHOUT_ALPHA:
        emit(f"  Warning: {chosen.upper()} cannot store transparency. "
             f"Using PNG instead.")
        chosen = "png"

    return IMAGE_FORMATS[chosen]


def resolve_frame_range(fps, total_frames, start_seconds=None,
                        end_seconds=None, log=None):
    """
    Turn a span of the video, in seconds, into the frames it covers.

    Args:
        fps (float): Frames per second reported by the video
        total_frames (int): Frames in the whole video
        start_seconds (float): Where to begin, None for the beginning
        end_seconds (float): Where to stop, None for the end
        log (callable): Where messages go, defaults to print

    Returns:
        tuple: (first frame to read, one past the last frame to read)
    """

    emit = log if log is not None else print
    last = total_frames if total_frames and total_frames > 0 else 0

    if start_seconds is None and end_seconds is None:
        return 0, last

    if not fps or fps <= 0 or last <= 0:
        emit("  Warning: the video reports no frame rate or length, so the "
             "chosen range cannot be applied. Using the whole video.")
        return 0, last

    start_frame = max(0, int(math.floor(float(start_seconds or 0) * fps)))
    end_frame = last if end_seconds is None else min(
        last, int(math.ceil(float(end_seconds) * fps))
    )

    if end_frame <= start_frame:
        emit("  Warning: the end of the range is not after its start. "
             "Using the whole video.")
        return 0, last

    emit(f"  Range: {start_frame / fps:.2f}s to {end_frame / fps:.2f}s "
         f"(frames {start_frame} to {end_frame - 1})")
    return start_frame, end_frame


def resolve_frame_step(fps, frame_step=1, interval_seconds=None, log=None):
    """
    Work out how many frames to advance between saved images.

    Saving every frame of a long video produces tens of thousands of files for
    very little extra information, so a frame can be taken at a time interval
    instead.

    Args:
        fps (float): Frames per second reported by the video
        frame_step (int): Save one frame out of this many (1 saves all)
        interval_seconds (float): Save one frame per this many seconds. Takes
                                  precedence over frame_step when given.
        log (callable): Where messages go, defaults to print

    Returns:
        int: How many frames to advance between saves, never less than 1
    """

    emit = log if log is not None else print

    if interval_seconds:
        if fps and fps > 0:
            # floor(x + 0.5) rather than round(): Python breaks ties to even
            # while the interface's JavaScript rounds halves up, and the two
            # must agree or the predicted image count is wrong
            step = max(1, int(math.floor(fps * float(interval_seconds) + 0.5)))
            emit(f"  Saving one frame every {interval_seconds}s "
                 f"({step} frames at {fps:.2f} fps)")
            return step
        emit("  Warning: the video reports no frame rate, so the time interval "
             "cannot be used. Saving every frame.")
        return 1

    step = max(1, int(frame_step or 1))
    if step > 1:
        emit(f"  Saving one frame out of every {step}")
    return step


def build_foreground_mask(gray_frame, background, threshold=25, min_area_pct=0.5):
    """
    Produce a binary mask of the moving subject by differencing a frame
    against the static background.

    Args:
        gray_frame (numpy.ndarray): Grayscale frame
        background (numpy.ndarray): Grayscale background from compute_background
        threshold (int): Brightness difference counted as foreground.
                         0 selects a per-frame automatic threshold (Otsu).
        min_area_pct (float): Discard blobs smaller than this percentage of the
                              frame area, which clears compression noise

    Returns:
        numpy.ndarray: Mask, 255 where the subject is and 0 elsewhere
    """

    diff = cv2.absdiff(gray_frame, background)
    diff = cv2.GaussianBlur(diff, (5, 5), 0)

    if threshold > 0:
        _, mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
    else:
        _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Open to drop speckle, close to fill gaps inside the subject
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)

    # Keep only blobs large enough to be a person
    if min_area_pct > 0:
        min_area = mask.size * min_area_pct / 100.0
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        cleaned = np.zeros_like(mask)
        for label in range(1, count):  # label 0 is the background
            if stats[label, cv2.CC_STAT_AREA] >= min_area:
                cleaned[labels == label] = 255
        mask = cleaned

    # Grow slightly so the subject's outline is not clipped
    return cv2.dilate(mask, kernel, iterations=1)


def apply_mask(gray_frame, mask, fill="black"):
    """
    Keep the masked subject and replace the background.

    Args:
        gray_frame (numpy.ndarray): Grayscale frame
        mask (numpy.ndarray): Mask from build_foreground_mask
        fill (str): "black" or "white" for a flat background, or "alpha" for a
                    transparent PNG (4-channel output)

    Returns:
        numpy.ndarray: The frame with its background removed
    """

    if fill == "alpha":
        return cv2.merge([gray_frame, gray_frame, gray_frame, mask])

    output = np.full_like(gray_frame, 255 if fill == "white" else 0)
    np.copyto(output, gray_frame, where=mask.astype(bool))
    return output


def extract_frames(video_path, output_dir=None, prefix="frame", remove_bg=True,
                   bg_threshold=25, bg_samples=60, bg_fill="black", min_area_pct=0.5,
                   frame_step=1, interval_seconds=None, image_format="png",
                   start_seconds=None, end_seconds=None, save_background=False,
                   log=None, progress_callback=None, should_cancel=None):
    """
    Extract all frames from a video file and save them as images.

    Args:
        video_path (str): Path to the input .MOV video file
        output_dir (str): Directory to save extracted frames. If None, a
                         frame_result_<video>_<date>_<time> folder beside the
                         video is used
        prefix (str): Prefix for output image filenames (default: "frame")
        remove_bg (bool): Remove the static background before saving
        bg_threshold (int): Foreground difference threshold, 0 for automatic
        bg_samples (int): Frames sampled to build the background
        bg_fill (str): "black", "white" or "alpha" for the removed background
        min_area_pct (float): Smallest kept blob, as a percentage of frame area
        frame_step (int): Save one frame out of this many (1 saves all)
        interval_seconds (float): Save one frame per this many seconds,
                                  which overrides frame_step
        image_format (str): "png", "jpg" or "webp" (default: "png")
        start_seconds (float): Where in the video to begin, None for the start
        end_seconds (float): Where to stop, None for the end
        save_background (bool): Also write the reconstructed empty scene, as
                                background.<ext> in the output folder
        log (callable): Where messages go, defaults to print
        progress_callback (callable): Called as (frames_done, frames_total)
        should_cancel (callable): Polled each frame; extraction stops when True

    Returns:
        bool: True if successful, False otherwise
    """

    emit = log if log is not None else print

    # Validate input file
    if not os.path.exists(video_path):
        emit(f"Error: Video file not found at {video_path}")
        return False

    if not video_path.lower().endswith('.mov'):
        emit(f"Warning: File does not have .MOV extension. Proceeding anyway...")

    # Create output directory. With nowhere given, save beside the video
    # rather than in whatever folder the program happens to be running from,
    # which is not somewhere anyone would think to look.
    if output_dir is None:
        output_dir = default_output_dir(video_path)

    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    emit(f"Output directory: {output_dir}")

    # Build the static background first, before the extraction pass
    background = None
    if remove_bg:
        emit("Building static background...")
        background = compute_background(video_path, bg_samples, log=emit)
        if background is None:
            emit("Error: Background removal requested but background failed")
            return False

    # Open video file
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        emit(f"Error: Could not open video file {video_path}")
        return False

    # Get video properties
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    emit(f"Video Properties:")
    emit(f"  Total frames: {total_frames}")
    emit(f"  FPS: {fps}")
    emit(f"  Resolution: {width}x{height}")
    emit(f"  Background removal: {'on' if remove_bg else 'off'}")

    extension, encoder_params = resolve_image_format(image_format, bg_fill, log=emit)
    emit(f"  Saving as: {extension.lstrip('.').upper()}")

    start_frame, end_frame = resolve_frame_range(
        fps, total_frames, start_seconds, end_seconds, log=emit
    )
    frames_in_range = max(0, end_frame - start_frame)

    # The reconstructed scene is worth keeping when the masking looks wrong:
    # a background with a ghost of the subject in it explains most bad results
    if save_background and background is not None:
        background_path = os.path.join(output_dir, f"background{extension}")
        if cv2.imwrite(background_path, background, encoder_params):
            emit(f"  Background saved: {os.path.basename(background_path)}")
        else:
            emit("  Warning: could not save the background image")

    step = resolve_frame_step(fps, frame_step, interval_seconds, log=emit)
    if frames_in_range > 0:
        expected = (frames_in_range + step - 1) // step
        emit(f"  Images to be written: {expected} of {frames_in_range} frames")

    # Jumping straight to the start beats decoding everything before it
    if start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    frame_count = start_frame
    successful_extractions = 0
    empty_masks = 0

    try:
        while True:
            if end_frame and frame_count >= end_frame:
                break

            ret, frame = cap.read()

            if not ret:
                break

            if should_cancel is not None and should_cancel():
                emit(f"\nCancelled after {frame_count - start_frame} frames")
                return False

            # Frames between saves cost only their decode: no mask, no file.
            # Counting from the start of the range keeps its first frame.
            if (frame_count - start_frame) % step != 0:
                frame_count += 1
                if progress_callback is not None and frame_count % 5 == 0:
                    progress_callback(frame_count - start_frame, frames_in_range)
                continue

            # Convert to grayscale if not already (for consistent handling of BW video)
            gray_frame = to_grayscale(frame)

            if remove_bg:
                mask = build_foreground_mask(
                    gray_frame, background, bg_threshold, min_area_pct
                )
                if not mask.any():
                    empty_masks += 1
                output_frame = apply_mask(gray_frame, mask, bg_fill)
            else:
                output_frame = gray_frame

            # Generate output filename with zero-padded frame number
            num_digits = len(str(total_frames))
            output_filename = f"{prefix}_{frame_count:0{num_digits}d}{extension}"
            output_path = os.path.join(output_dir, output_filename)

            # Save frame as image
            if cv2.imwrite(output_path, output_frame, encoder_params):
                successful_extractions += 1
            else:
                emit(f"Warning: Failed to save frame {frame_count}")

            frame_count += 1

            # Print progress every 100 frames
            if frame_count % 100 == 0:
                emit(f"  Processed {frame_count}/{total_frames} frames...")

            # Report progress more often than that, for a UI progress bar
            if progress_callback is not None and frame_count % 5 == 0:
                progress_callback(frame_count - start_frame, frames_in_range)

        read_count = frame_count - start_frame

        emit(f"\nExtraction Complete!")
        if step > 1:
            emit(f"Images written: {successful_extractions} "
                 f"(from {read_count} frames, one in every {step})")
        else:
            emit(f"Total frames extracted: {successful_extractions}/{read_count}")
        if remove_bg and empty_masks:
            emit(f"Frames where nothing was detected: {empty_masks} "
                  f"(lower --bg-threshold if that seems wrong)")
        emit(f"Frames saved to: {output_dir}")

        if progress_callback is not None:
            progress_callback(read_count, read_count)

        return True

    except Exception as e:
        emit(f"Error during extraction: {e}")
        return False

    finally:
        cap.release()


def main():
    """Main function with command-line argument parsing."""

    parser = argparse.ArgumentParser(
        description="Extract all frames from a .MOV video file to images, "
                    "removing the static background by default"
    )
    parser.add_argument(
        "video_path",
        help="Path to the input .MOV video file"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output directory for extracted frames (optional)",
        default=None
    )
    parser.add_argument(
        "-p", "--prefix",
        help="Prefix for output image filenames (default: 'frame')",
        default="frame"
    )
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument(
        "--every-seconds",
        type=float,
        default=None,
        help="Save one frame per this many seconds, for example 1 or 0.5, "
             "instead of saving every frame"
    )
    sampling.add_argument(
        "--every-frames",
        type=int,
        default=1,
        help="Save one frame out of this many (default: 1, every frame)"
    )
    parser.add_argument(
        "--start",
        type=float,
        default=None,
        help="Begin at this many seconds into the video (default: the start)"
    )
    parser.add_argument(
        "--end",
        type=float,
        default=None,
        help="Stop at this many seconds into the video (default: the end)"
    )
    parser.add_argument(
        "-f", "--format",
        choices=sorted(IMAGE_FORMATS),
        default="png",
        help="Image format to save (default: png). jpg is far smaller but "
             "lossy and cannot hold transparency; webp is small and can"
    )
    parser.add_argument(
        "--save-background",
        action="store_true",
        help="Also write the reconstructed empty scene as background.<ext>, "
             "which shows what the frames were compared against"
    )
    parser.add_argument(
        "--keep-background",
        action="store_true",
        help="Save whole frames without removing the background"
    )
    parser.add_argument(
        "--bg-threshold",
        type=int,
        default=25,
        help="Brightness difference counted as subject, 0 for automatic "
             "(default: 25; lower keeps more, higher keeps less)"
    )
    parser.add_argument(
        "--bg-samples",
        type=int,
        default=60,
        help="Frames sampled to build the static background (default: 60)"
    )
    parser.add_argument(
        "--bg-fill",
        choices=["black", "white", "alpha"],
        default="black",
        help="What replaces the background: flat black, flat white, or alpha "
             "transparency (default: black)"
    )
    parser.add_argument(
        "--min-area",
        type=float,
        default=0.5,
        help="Discard detected blobs smaller than this percent of the frame, "
             "which clears noise (default: 0.5)"
    )

    args = parser.parse_args()

    success = extract_frames(
        args.video_path,
        args.output,
        args.prefix,
        remove_bg=not args.keep_background,
        bg_threshold=args.bg_threshold,
        bg_samples=args.bg_samples,
        bg_fill=args.bg_fill,
        min_area_pct=args.min_area,
        frame_step=args.every_frames,
        interval_seconds=args.every_seconds,
        image_format=args.format,
        start_seconds=args.start,
        end_seconds=args.end,
        save_background=args.save_background,
    )

    if not success:
        exit(1)


if __name__ == "__main__":
    main()
