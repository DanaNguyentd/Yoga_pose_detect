"""
Extract all frames from a .MOV video file and save them as images.
Handles black and white (grayscale) video files.
"""

import cv2
import os
from pathlib import Path
import argparse
from datetime import datetime


def extract_frames(video_path, output_dir=None, prefix="frame"):
    """
    Extract all frames from a video file and save them as images.

    Args:
        video_path (str): Path to the input .MOV video file
        output_dir (str): Directory to save extracted frames.
                         If None, creates a folder in the same directory as video
        prefix (str): Prefix for output image filenames (default: "frame")

    Returns:
        bool: True if successful, False otherwise
    """

    # Validate input file
    if not os.path.exists(video_path):
        print(f"Error: Video file not found at {video_path}")
        return False

    if not video_path.lower().endswith('.mov'):
        print(f"Warning: File does not have .MOV extension. Proceeding anyway...")

    # Create output directory
    if output_dir is None:
        video_name = Path(video_path).stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = f"{video_name}_frames_{timestamp}"

    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {output_dir}")

    # Open video file
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print(f"Error: Could not open video file {video_path}")
        return False

    # Get video properties
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"Video Properties:")
    print(f"  Total frames: {total_frames}")
    print(f"  FPS: {fps}")
    print(f"  Resolution: {width}x{height}")

    frame_count = 0
    successful_extractions = 0

    try:
        while True:
            ret, frame = cap.read()

            if not ret:
                break

            # Convert to grayscale if not already (for consistent handling of BW video)
            if len(frame.shape) == 3:
                gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                gray_frame = frame

            # Generate output filename with zero-padded frame number
            num_digits = len(str(total_frames))
            output_filename = f"{prefix}_{frame_count:0{num_digits}d}.png"
            output_path = os.path.join(output_dir, output_filename)

            # Save frame as image
            if cv2.imwrite(output_path, gray_frame):
                successful_extractions += 1
            else:
                print(f"Warning: Failed to save frame {frame_count}")

            frame_count += 1

            # Print progress every 100 frames
            if frame_count % 100 == 0:
                print(f"  Processed {frame_count}/{total_frames} frames...")

        cap.release()

        print(f"\nExtraction Complete!")
        print(f"Total frames extracted: {successful_extractions}/{frame_count}")
        print(f"Frames saved to: {output_dir}")

        return True

    except Exception as e:
        print(f"Error during extraction: {e}")
        cap.release()
        return False


def main():
    """Main function with command-line argument parsing."""

    parser = argparse.ArgumentParser(
        description="Extract all frames from a .MOV video file to images"
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

    args = parser.parse_args()

    success = extract_frames(args.video_path, args.output, args.prefix)

    if not success:
        exit(1)


if __name__ == "__main__":
    main()
