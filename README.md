# hls-converter-cli

> **⚠️ BETA RELEASE — v0.9.0**
>
> This project is currently in **Beta**. The public API, command-line flags,
> and output folder layout may still change between 0.x releases. Please
> report bugs and feedback at:
>
> **https://github.com/devdasher/hls-converter-cli/issues**

A general-purpose **HLS media converter** built on top of FFmpeg, by [@devdasher](https://github.com/devdasher).

Turns any MKV / MP4 / MOV / TS / WEBM / AVI file into an HLS stream folder
with a ready-to-serve `master.m3u8` playlist — including adaptive bitrate
video renditions, per-track audio profiles, and WebVTT subtitles — all from
a single command.

Comes with a **Python library API** so you can embed the converter in your
own scripts and applications.

---

## 🔗 Related project — [Desktop GUI](https://github.com/devdasher/hls-converter-gui)

Prefer a graphical interface? A companion desktop app is available:

**HLS Converter GUI** — a PySide6 frontend with the same conversion engine,
plus a built-in HLS preview player, drag & drop, per-track audio overrides,
and one-click track merging.

- Download prebuilt executables for **Windows, Linux, macOS** from the
  Releases page:
  **https://github.com/devdasher/hls-converter-gui/releases**
- Or install from PyPI:
  ```
  pip install hls-converter-gui
  ```

The GUI automatically installs the CLI package as a dependency, so you get
both in one command.

---

## Table of contents

- [hls-converter-cli](#hls-converter-cli)
  - [🔗 Related project — Desktop GUI](#-related-project--desktop-gui)
  - [Table of contents](#table-of-contents)
  - [Installation](#installation)
    - [From PyPI (recommended)](#from-pypi-recommended)
    - [From source](#from-source)
    - [Verify installation](#verify-installation)
  - [Requirements](#requirements)
  - [Quick start](#quick-start)
  - [Command-line reference](#command-line-reference)
    - [General](#general)
    - [Add-to-stream mode](#add-to-stream-mode)
  - [Video options](#video-options)
  - [Audio options](#audio-options)
  - [Subtitle options](#subtitle-options)
  - [Add tracks to an existing stream](#add-tracks-to-an-existing-stream)
  - [HLS tuning](#hls-tuning)
  - [Library API](#library-api)
    - [Exported symbols](#exported-symbols)
  - [Output layout](#output-layout)
  - [How it works](#how-it-works)
  - [FAQ and troubleshooting](#faq-and-troubleshooting)
  - [Beta notes](#beta-notes)
  - [License](#license)

---

## Installation

### From PyPI (recommended)

```
pip install hls-converter-cli
```

This installs the `hls-converter` command on your PATH.

### From source

```
git clone https://github.com/devdasher/hls-converter-cli.git
cd hls-converter-cli
pip install -e .
```

### Verify installation

```
hls-converter --version
hls-converter --about
```

---

## Requirements

- **Python 3.10 or newer**
- **FFmpeg** and **ffprobe** must be installed and available either on your
  `PATH`, or passed explicitly with `--ffmpeg` and `--ffprobe`.

How to install FFmpeg:

| OS      | Command / source |
| ------- | ---------------- |
| Windows | Download from https://www.gyan.dev/ffmpeg/builds/ (essentials build is fine) and add the `bin` folder to your PATH |
| macOS   | `brew install ffmpeg` |
| Linux   | `sudo apt install ffmpeg` (Debian/Ubuntu) or `sudo dnf install ffmpeg` (Fedora) |

To confirm FFmpeg is visible:

```
ffmpeg -version
ffprobe -version
```

---

## Quick start

Convert a single file using the default settings (video is stream-copied,
every audio track is stream-copied, all text subtitles are extracted):

```
hls-converter "movie.mkv"
```

Output goes into a `movie-stream/` folder next to the input file, containing
a `master.m3u8` you can serve directly from any HTTP server.

Choose a custom output directory:

```
hls-converter "movie.mkv" --output "D:\streams\movie"
```

Re-encode the video to multiple resolutions with a compatible audio set:

```
hls-converter "movie.mkv" --video-mode encode --video-profiles 720,1080
```

Add a subtitle file to an existing stream:

```
hls-converter "persian.srt" --add-to-stream "D:\streams\movie" --language fa
```

Preview everything without actually running FFmpeg:

```
hls-converter "movie.mkv" --dry-run
```

---

## Command-line reference

Run `hls-converter --help` for the full flag list. The most important ones
are summarised below.

### General

| Flag | Description |
| ---- | ----------- |
| `--output PATH` | Output stream folder. Default: `<input_stem>-stream` next to the input file. |
| `--clean` | Delete the entire output folder before starting. Useful when re-running with different settings. |
| `--skip-master` | Do not regenerate `master.m3u8`. Useful when merging multiple conversions into one folder. |
| `--dry-run` | Print every FFmpeg command without executing it. |
| `--ffmpeg PATH` | Path to the `ffmpeg` binary (default: search PATH). |
| `--ffprobe PATH` | Path to the `ffprobe` binary (default: search PATH). |
| `--default-audio-track N` | Force audio track N to be marked `DEFAULT=YES` in the master playlist. |
| `--default-subtitle-track N` | Force subtitle track N to be marked `DEFAULT=YES`. |
| `--version` | Show version and exit. |
| `--about` | Show author, license, and project links. |

### Add-to-stream mode

| Flag | Description |
| ---- | ----------- |
| `--add-to-stream PATH` | Add the input file (audio or subtitle) to this existing stream folder. |
| `--track N` | Assign the new track to number N. Default: next available. |
| `--language LANG` | ISO 639-1 language tag for the new track (e.g. `fa`, `en`, `de`). |
| `--title TEXT` | Human-readable title for the new track. |
| `--audio-add-mode MODE` | `auto` (default), `copy`, or `encode`. |
| `--audio-level LEVEL` | `data-saver`, `small`, `balanced`, `high`, `source`. |
| `--audio-codec CODEC` | Target codec when re-encoding: `aac`, `libopus`, `libmp3lame`, `ac3`, `eac3`. |
| `--audio-profile PROFILE` | AAC encoder profile (e.g. `aac_low`, `aac_he`). |
| `--subtitle-offset-ms N or TRACK=N,...` | Shift subtitle timings in milliseconds. |
| `--subtitle-time-scale NUM/DEN` | Scale subtitle timestamps (e.g. `25/23.976`). |

---

## Video options

| Flag | Description |
| ---- | ----------- |
| `--video-mode MODE` | `copy` (default), `encode`, or `none`. |
| `--video-label LABEL` | Folder name for copy mode. Default: source height (e.g. `1080p`). |
| `--video-profiles LIST` | Comma-separated target heights for encode mode, e.g. `480,720,1080`. |
| `--video-level LEVEL` | Auto-bitrate preset: `data-saver`, `small`, `balanced` (default), `high`, `source`. |
| `--video-rate-mode MODE` | `auto` (default), `crf`, `abr`, or `2pass`. |
| `--video-bitrate LIST` | Per-quality bitrate overrides in kbps, e.g. `480=850,720=1300,1080=2800`. |
| `--video-crf LIST` | Per-quality CRF overrides, e.g. `480=24,720=20,1080=18`. |
| `--video-codec CODEC` | FFmpeg encoder. Default: `libx264`. Try `libx265` or `h264_nvenc`. |
| `--video-preset PRESET` | x264/x265 preset. Default: `medium`. Try `fast` or `slow`. |

**Supported heights:** 144, 240, 360, 480, 540, 720, 1080, 1440, 2160.

**Bitrate level multipliers** (applied to the built-in default bitrates):

| Level        | Multiplier |
| ------------ | ---------- |
| `data-saver` | 0.55× |
| `small`      | 0.75× |
| `balanced`   | 1.00× |
| `high`       | 1.50× |
| `source`     | Uses ~90% of the source bitrate, capped per resolution |

**Rate modes:**

- `auto` — Uses CRF if a `--video-crf` override is present, otherwise ABR.
- `crf` — Constant Rate Factor. Quality-driven, ignores bitrate.
- `abr` — Average bitrate. Uses `--video-bitrate` overrides when present.
- `2pass` — Two-pass ABR. Best quality per byte but runs FFmpeg twice.

---

## Audio options

By default, every audio track is **stream-copied** into HLS, preserving the
original codec whenever it is HLS-compatible (AAC, MP3, AC-3, E-AC-3).

| Flag | Description |
| ---- | ----------- |
| `--audio MODE` | `encode`, `none`, or `TRACK:encode`. Repeatable. |
| `--audio-profiles LIST` | Encoded profiles. Format: `BITRATE` or `BITRATE:CHANNELS`, e.g. `128:2,224:6`. |
| `--audio-bitrate LIST` | Per-track bitrate override, e.g. `2=128,4=224`. |
| `--audio-channels LIST` | Per-track channel count override, e.g. `2=2,4=6`. |
| `--audio-codec CODEC` | Target codec: `aac` (default), `libopus`, `libmp3lame`, `ac3`, `eac3`. |
| `--audio-profile PROFILE` | AAC encoder profile. Default: `aac_low`. |
| `--audio-level LEVEL` | `data-saver`, `small`, `balanced` (default), `high`, `source`. |

**Examples:**

Copy all audio (default):

```
hls-converter "movie.mkv"
```

Encode every audio track to the default profile set:

```
hls-converter "movie.mkv" --audio encode
```

Encode only tracks 1 and 3, with custom profiles:

```
hls-converter "movie.mkv" --audio 1:encode,3:encode --audio-profiles 128:2,224:6
```

Per-track bitrate and channel overrides:

```
hls-converter "movie.mkv" --audio encode --audio-bitrate 1=128,2=224 --audio-channels 2=6
```

Skip all audio:

```
hls-converter "movie.mkv" --audio none
```

---

## Subtitle options

Text-based subtitles are extracted to **WebVTT** with an injected
`X-TIMESTAMP-MAP` header so they stay in sync with HLS video segments.

| Flag | Description |
| ---- | ----------- |
| `--subtitles MODE` | `auto` (default) or `none`. |
| `--subtitle-offset-ms N` | Global shift in milliseconds (positive = delay). |
| `--subtitle-offset-ms TRACK=N,...` | Per-track offset, e.g. `1=500,2=-200`. |
| `--subtitle-time-scale NUM/DEN` | Scale timestamps for drift correction, e.g. `25/23.976`. |

**Supported input codecs:** `subrip`, `srt`, `ass`, `ssa`, `webvtt`,
`mov_text`. Bitmap subtitles (PGS, VobSub) are skipped with a warning.

**When to use `--subtitle-time-scale`:** when the subtitles were timed for a
different frame rate than the video. The most common case is subtitles timed
for 25 fps PAL but the video is 23.976 fps — use `25/23.976`. The inverse
case (23.976 → 25) uses `23.976/25`.

---

## Add tracks to an existing stream

You can attach an external audio file or subtitle file to an already-built
stream folder and regenerate `master.m3u8`:

```
hls-converter "commentary.m4a" --add-to-stream "D:\streams\movie" --language en --title "Director's Commentary"
```

```
hls-converter "persian.srt" --add-to-stream "D:\streams\movie" --language fa
```

The new track receives the next available number by default. Assign a
specific number with `--track N`.

**Conflict protection:** if a track already exists at that number and was
generated from a *different* source file, the tool refuses to overwrite it.
Use a different `--track` value or `--clean` on the original stream.

**Audio add modes:**

| Mode | Behavior |
| ---- | -------- |
| `auto` (default) | Copy if the source codec is HLS-compatible, otherwise encode. |
| `copy` | Always copy. Fails if the codec is incompatible. |
| `encode` | Always re-encode to `--audio-codec`. |

**Supported external audio inputs:** `.m4a`, `.aac`, `.mp3`, `.ac3`,
`.eac3`, `.opus`, `.flac`, `.wav`, `.ogg`, `.mka`.

**Supported external subtitle inputs:** `.srt`, `.ass`, `.ssa`, `.vtt`,
`.sub`, `.sbv`.

---

## HLS tuning

| Flag | Description |
| ---- | ----------- |
| `--segment-time SEC` | HLS segment length. Default: 6 seconds. |
| `--keyframe-interval SEC` | Force a keyframe every N seconds. Default: 6. |
| `--threads N` | Encoder thread count. Default: 12. |

**Recommended combinations:**

- **Fast start / low-latency:** `--segment-time 4 --keyframe-interval 4`
- **General purpose:** `--segment-time 6 --keyframe-interval 6` (default)
- **Slow network / better cache:** `--segment-time 10 --keyframe-interval 10`

The keyframe interval should be **equal to or less than** the segment time,
otherwise segments will not start on clean keyframes and players may stutter.

---

## Library API

The CLI is also a reusable Python library. Every public class and function
is exported from the top-level module.

```python
from pathlib import Path
from hls_converter_cli import (
    HLSConverter, AppConfig, VideoRequest, VideoProfile,
    AudioConfig, SubtitleConfig,
    CancellationToken, ProgressEvent,
)

# Build an AppConfig however you like — you can reuse build_config(args)
# from CLI parsing, or construct one manually.
config = AppConfig(
    ffmpeg="ffmpeg",
    ffprobe="ffprobe",
    output=None,
    clean=False,
    skip_master=False,
    video=VideoRequest(
        mode="encode",
        profiles=[
            VideoProfile(quality="720p", height=720),
            VideoProfile(quality="1080p", height=1080),
        ],
    ),
    video_level="balanced",
    video_rate_mode="auto",
    video_codec="libx264",
    video_preset="medium",
    threads=8,
    audio=AudioConfig(),
    audio_codec="aac",
    audio_profile="aac_low",
    subtitles=SubtitleConfig(mode="auto"),
    keyframe_interval=6.0,
    segment_time=6,
    default_audio_track=None,
    default_subtitle_track=None,
)

converter = HLSConverter(config)
token = CancellationToken()

result = converter.convert(
    input_file=Path("movie.mkv"),
    output_dir=Path("movie-stream"),
    on_log=lambda level, msg: print(f"[{level}] {msg}"),
    on_progress=lambda ev: print(f"{ev.stage} {ev.label} {ev.percent:.1f}%"),
    cancel_token=token,
)

if result.success:
    print("Master playlist:", result.master_playlist)
else:
    print("Failed:", result.error)
```

**Cancelling from another thread:**

```python
token.cancel()          # terminates any running FFmpeg process
```

**Adding an external track programmatically:**

```python
from hls_converter_cli import AddToStreamOptions

result = converter.add_to_stream(
    input_file=Path("persian.srt"),
    stream_dir=Path("movie-stream"),
    options=AddToStreamOptions(language="fa", track=3),
)
```

### Exported symbols

- **Classes:** `HLSConverter`, `CancellationToken`, `ProgressEvent`,
  `ConversionResult`
- **Config models:** `AppConfig`, `VideoRequest`, `VideoProfile`,
  `AudioConfig`, `AudioRequest`, `AudioProfile`, `SubtitleConfig`,
  `AddToStreamOptions`
- **Media info:** `MediaInfo`, `VideoStream`, `AudioStream`,
  `SubtitleStream`
- **Parsing helpers:** `build_parser`, `build_config`
- **Errors:** `ConverterError`
- **Metadata:** `__version__`, `__status__`, `__author__`, `__license__`,
  `APP_NAME`, `AUTHOR`, `GITHUB_URL`, `PYPI_URL`

---

## Output layout

For an input file `movie.mkv` you will get:

```
movie-stream/
├── master.m3u8                    ← entry point for players
├── .converter.json                ← source fingerprint and stream info
├── video/
│   ├── 480p/
│   │   ├── playlist.m3u8
│   │   ├── 00000.ts
│   │   ├── 00001.ts
│   │   └── ...
│   ├── 720p/
│   │   └── ...
│   └── 1080p/
│       └── ...
├── audio/
│   ├── 1/
│   │   ├── 128k-2ch/
│   │   │   ├── playlist.m3u8
│   │   │   └── *.ts
│   │   └── 224k-6ch/
│   │       └── ...
│   └── 2/
│       └── ...
└── subtitles/
    ├── 1/
    │   ├── playlist.m3u8
    │   └── sub.vtt
    └── 2/
        └── ...
```

Serve the whole folder from any HTTP server and point your player at
`master.m3u8`:

```
python -m http.server 8000
# then open http://localhost:8000/movie-stream/master.m3u8
```

The master playlist already contains `EXT-X-MEDIA` entries for all audio and
subtitle tracks, `EXT-X-STREAM-INF` entries with `BANDWIDTH`, `RESOLUTION`,
`CODECS`, `AUDIO`, and `SUBTITLES` attributes, and a proper HLS version tag.

---

## How it works

1. **Probing** — `ffprobe` reads every stream in the input file: codec,
   resolution, frame rate, channels, language, and per-stream average
   bitrate (measured by summing packet sizes).
2. **Video** — In copy mode, the selected video stream is remuxed into HLS
   without re-encoding. In encode mode, it is scaled to each requested
   height using Lanczos filtering, forced to even dimensions, and encoded
   with the chosen codec and rate control.
3. **Audio** — In copy mode, each audio track is remuxed. In encode mode,
   each track is converted to every requested profile (bitrate × channels),
   with automatic channel downmixing when the source has more channels than
   the target profile can carry.
4. **Subtitles** — Every text subtitle stream is extracted to WebVTT,
   optional per-track time-shifting and time-scaling are applied, then an
   `X-TIMESTAMP-MAP` header is injected so the subtitle timeline matches the
   HLS video timeline.
5. **Master playlist** — `master.m3u8` is generated with proper `EXT-X-MEDIA`
   groups, per-rendition `BANDWIDTH`/`RESOLUTION`/`CODECS` attributes, and
   `DEFAULT` marking for the tracks you configured.
6. **Resume** — Any sub-playlist that already exists and is complete is
   skipped automatically. Interrupted sub-conversions are cleaned up on
   the next run.

---

## FAQ and troubleshooting

**FFmpeg is not found**

```
[ERROR] Executable not found: ffmpeg
```

Install FFmpeg and add it to your PATH, or pass `--ffmpeg` and `--ffprobe`
explicitly:

```
hls-converter "movie.mkv" --ffmpeg "C:\ffmpeg\bin\ffmpeg.exe" --ffprobe "C:\ffmpeg\bin\ffprobe.exe"
```

**Subtitle is out of sync**

Try a global offset first:

```
hls-converter "movie.mkv" --subtitle-offset-ms 500
```

If the drift grows over time, use a time scale instead:

```
hls-converter "movie.mkv" --subtitle-time-scale 25/23.976
```

**Master playlist has no audio**

The master playlist generator needs at least one video or audio rendition
to be complete. Check the `video/` and `audio/` subfolders for
`playlist.m3u8` files.

**Disk full during encode**

Encode mode multiplies the output size because each profile is a full
copy of the video. For a 4 GB source with three profiles expect roughly
10–12 GB of output.

**Progress output is silent when running non-interactively**

The CLI falls back to `print()` when no progress callback is registered.
For scripted use, register a callback through the library API instead.

**Re-running after changing options**

Use `--clean` to wipe the output folder and start fresh:

```
hls-converter "movie.mkv" --clean --video-mode encode --video-profiles 720
```

**Multi-audio files** — pass `--audio 1:encode,2:encode --audio-bitrate 1=128,2=224`

**Multi-video files** — only the first video stream is used. Pass
`--video-mode none` to skip video entirely and build an audio-only stream.

---

## Beta notes

This is a **Beta** release. The following may still change before 1.0:

- The public Python API (classes, method signatures, exceptions).
- Some `--help` text and default values.
- The on-disk metadata format (`.converter.json`).

**Compatibility promise:**

- New flags may be added in minor releases.
- Existing flags will not be removed without a deprecation cycle.
- Saved stream folders remain forward-compatible.

**Known limitations in this Beta:**

- Only the first video stream in the input file is used.
- Only text-based subtitles are supported. Bitmap subtitles (PGS, VobSub)
  are skipped with a warning.
- No hardware encoder auto-detection. Pass `--video-codec h264_nvenc`,
  `hevc_nvenc`, or `h264_videotoolbox` explicitly if you have the
  corresponding FFmpeg build.
- Very long files (>6 hours) may exceed ffprobe packet-iteration limits
  during bitrate analysis.

Feedback and bug reports are welcome at
**https://github.com/devdasher/hls-converter-cli/issues**.

---

## License

MIT — see the `LICENSE` file for details.

Copyright © 2026 devdasher
