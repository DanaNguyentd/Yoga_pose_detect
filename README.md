# Yoga_pose_detect

Turns yoga videos into still frames with the background removed, ready for pose
detection.

Footage is shot with a fixed camera against a background that never changes. To
train or test a pose detector, that video has to become images, and the
unchanging room behind the person is noise. This tool does both: it pulls frames
out of a video and keeps only the person in them.

Pose detection itself is not built yet. This is the data preparation stage.

---

## Quick start

```sh
python3 -m pip install -r requirements.txt
python3 app.py
```

A window opens. Choose a video, preview one frame, then extract.

Use `python3 -m pip`, not `pip3`. On some machines `pip3` belongs to a
different Python than `python3`, and the packages land where `python3` cannot
see them.

---

## Using the application

1. **Choose a video.** The file dialog is the operating system's own, so it
   reads the file where it sits: nothing is copied or uploaded.
2. **Pick the part you want.** The video appears with two handles under it for
   where detection should start and stop. Both default to the whole video.
   *use current* takes the position from the playhead.
3. **Say how many frames.** One per second is the default. Every frame is
   almost never what you want: a four minute clip at 30 fps is 7200 images, and
   two frames 33 milliseconds apart teach a detector nothing new.
4. **Preview one frame.** Three panels appear: the original, the rebuilt empty
   room, and the result. This is where the threshold is judged.
5. **Extract.** Progress and messages appear as it runs, and it can be
   cancelled part way.

With no output folder chosen, frames go beside the video, in a folder named
after it and the time of the run:

```
frame_result_IMG_8803_20260928_143015/
├── background.png       (only if asked for)
├── frame_001800.png
├── frame_001830.png
└── ...
```

Filenames carry the **source frame number**, so an image always says where in
the video it came from, whatever interval was used.

### When the result looks wrong

| What you see | What to change |
|---|---|
| The body is patchy or hollow | Lower the threshold, try 15 |
| The background bleeds through | Raise the threshold, try 35 |
| Specks of noise survive | Raise *smallest blob kept* |
| A hand or foot disappears | Lower *smallest blob kept* |
| Nothing is detected at all | Turn on *save the rebuilt background* and look at it |

That last one is the useful trick. The rebuilt background is the empty scene
every frame was compared against. If you can see a ghost of yourself in it, you
held still for too much of the video for it to be erased, and the fix is a video
with more movement rather than a different threshold.

---

## Running from the command line

The analysis runs on its own, with no window, which is faster when you are
comparing settings:

```sh
python3 extract_video_frames.py video.MOV
python3 extract_video_frames.py video.MOV -o frames/ --every-seconds 1
python3 extract_video_frames.py video.MOV --start 60 --end 120
python3 extract_video_frames.py video.MOV -f jpg --save-background
python3 extract_video_frames.py video.MOV --keep-background
```

`python3 extract_video_frames.py --help` lists everything.

| Option | Does |
|---|---|
| `-o`, `--output` | Where to write. Defaults to a dated folder beside the video |
| `-p`, `--prefix` | Filename prefix, default `frame` |
| `-f`, `--format` | `png`, `jpg` or `webp`, default `png` |
| `--every-seconds` | Save one frame per this many seconds |
| `--every-frames` | Save one frame out of this many |
| `--start`, `--end` | The span of the video to read, in seconds |
| `--bg-threshold` | How different a pixel must be to count as body. 0 is automatic |
| `--bg-samples` | Frames used to rebuild the empty room |
| `--bg-fill` | `black`, `white` or `alpha` |
| `--min-area` | Smallest blob kept, as a percentage of the frame |
| `--save-background` | Also write the rebuilt empty room |
| `--keep-background` | Do not remove the background at all |

---

## Testing a change

**Nothing needs building in order to be tested.** Python is not compiled, so
`app.py` reads the `.py`, `.html`, `.css` and `.js` files straight from disk,
exactly as you last saved them.

```sh
python3 app.py --debug
```

`--debug` adds the platform's web inspector: right-click in the window and
choose *Inspect Element*. From there **Cmd+R reloads the page**, so edits to
anything under `web/` show up without restarting. Only changes to `app.py` or
`extract_video_frames.py` need a quit and restart, because Python cannot reload
its own imports.

| You changed | What to do |
|---|---|
| `web/*.html`, `*.css`, `*.js` | Cmd+R in the window |
| `app.py`, `extract_video_frames.py` | Quit, run `python3 app.py` again |
| Anything at all | Never rebuild |

### Automated tests

The analysis tests need nothing but the runtime dependencies:

```sh
python3 tests/test_analysis.py
```

They cover the decisions worth getting wrong: which file extension a format and
a fill imply, how a time interval becomes a frame step, which frames a time
range covers, where output lands, and whether the masking actually separates a
subject from a background. The masking is checked against arrays built by hand,
so no video file is needed.

Add a video to also run the whole pipeline end to end:

```sh
TEST_VIDEO=test/IMG_8803.MOV python3 tests/test_analysis.py
```

The interface tests load the real `web/index.html` and `web/app.js` in a
headless DOM and drive the controls, with Python replaced by stubs. They need
Node:

```sh
npm install jsdom
sh tests/run_ui_tests.sh
```

They check that choosing JPEG greys out transparency and moves the selection
off it, that the example filename matches what Python will really write, that
the log clears when a run starts, that the range handles cannot cross, that an
unplayable video falls back to the frame scrubber, and that the image count the
page predicts agrees with the number of files that appear.

---

## Building an application to give someone

Only needed to hand the tool to someone who has no Python. The result is a
single application they double-click.

```sh
python3 -m pip install -r requirements-build.txt
pyinstaller --clean --noconfirm build.spec
```

The build lands in `dist/`. On macOS that is `dist/YogaPoseExtractor.app`.

PyInstaller cannot cross-compile, so each operating system has to be built on
itself. The repository does all three on GitHub's machines instead: go to
**Actions → Build application → Run workflow**, then download the artifacts
when it finishes.

| Platform | What the recipient does | Notes |
|---|---|---|
| Windows | Unzip, run the `.exe` | SmartScreen: *More info → Run anyway* |
| macOS | Unzip, **right-click → Open** the first time | Unsigned; signing needs an Apple developer account |
| Linux | Unzip and run | Needs `sudo apt install gir1.2-webkit2-4.1` |

Building on macOS needs the Command Line Tools, because PyInstaller calls
`lipo`:

```sh
xcode-select --install
```

---

## How it works

The background is rebuilt rather than filmed. Frames are sampled across the
whole video and the **per-pixel median** is taken: at any given pixel the person
covers it in only a few of the samples, so the median keeps whatever was there
most consistently, which is the wall, the floor, the mat. That gives a
photograph of the empty room with the person erased, and no empty-room footage
to shoot.

Each frame is then compared against it, and what differs is the person.

```
video ──> median of sampled frames ──> the empty room
                                            │
each frame ──────── difference ─────────────┘──> mask ──> masked image
```

### Layout

```
app.py                    the application; run this
extract_video_frames.py   all the image processing; imports no interface
web/index.html            the interface: structure
web/style.css             the interface: appearance, light and dark
web/app.js                the interface: behaviour
tests/                    the tests described above
build.spec                how the standalone application is packaged
PROJECT_NOTES.txt         every function, and how the pieces connect
```

The analysis never imports an interface and the interface never imports OpenCV.
Only `app.py` imports both. That is why the command line still works on a
machine with no screen, and why the window can be rewritten without touching a
line of the image processing.

`PROJECT_NOTES.txt` has the detail: every function, the path a click takes from
the page down to OpenCV and back, and why particular decisions were made.

---

## Requirements

Python 3.8 or newer, with `opencv-python`, `numpy` and `pywebview`, all in
`requirements.txt`. Node and `jsdom` are needed only to run the interface
tests; the application itself never uses them.
