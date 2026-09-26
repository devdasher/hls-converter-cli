# hls-converter-cli

General-purpose HLS media converter built on FFmpeg, by [@devdasher](https://github.com/devdasher).

## Install

```bash
pip install hls-converter-cli
```

You also need ffmpeg and ffprobe on your PATH, or pass their
locations via --ffmpeg / --ffprobe.

## CLI usage

```bash
hls-converter "movie.mkv"
hls-converter "movie.mkv" --video-mode encode --video-profiles 720,1080
hls-converter "subs.srt" --add-to-stream "/path/to/stream" --language fa
```

Run `hls-converter --about` for author, license, and project links.

## Library usage

```py
from pathlib import Path
from hls_converter_cli import (
    HLSConverter, AppConfig, CancellationToken,
)

config = AppConfig(...)          # build with build_parser()/build_config()
converter = HLSConverter(config)

result = converter.convert(
    input_file=Path("movie.mkv"),
    output_dir=Path("movie-stream"),
    on_progress=lambda ev: print(ev.stage, ev.percent),
    cancel_token=CancellationToken(),
)
```

## Features

- Copy or re-encode video to multiple resolutions
- Per-track audio bitrate and channel overrides
- Subtitle extraction to WebVTT with offset and time-scale correction
- Add audio/subtitle tracks to an existing stream folder
- Dry-run mode, progress events, cooperative cancellation

## License

MIT