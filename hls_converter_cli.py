#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HLS Converter CLI — general-purpose HLS media converter built on FFmpeg.

Part of the hls-converter-cli project:
    https://github.com/devdasher/hls-converter-cli

Dual-purpose:
  * As a command-line tool (installed via pip):
        hls-converter "movie.mkv"
        hls-converter "movie.mkv" --video-mode encode --video-profiles 720,1080
        hls-converter "new-subs.srt" --add-to-stream "/path/to/stream" --language fa

    Or, from a source checkout:
        python hls_converter_cli.py "movie.mkv"
        python -m hls_converter_cli   "movie.mkv"

  * As a third-party Python library:
        from hls_converter_cli import (
            HLSConverter, AppConfig, build_config, build_parser,
            CancellationToken, ProgressEvent, ConversionResult,
        )

        config = build_config(args)        # or construct AppConfig manually
        converter = HLSConverter(config)
        token = CancellationToken()
        result = converter.convert(
            input_file=Path("movie.mkv"),
            output_dir=Path("movie-stream"),
            on_log=lambda level, msg: print(f"[{level}] {msg}"),
            on_progress=lambda ev: print(f"{ev.stage} {ev.label} {ev.percent:.0f}%"),
            cancel_token=token,
        )

Author  : devdasher
Status  : Beta
License : MIT
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field, replace as _dc_replace
from pathlib import Path
from typing import Callable, Optional


# ============================================================
# PROJECT METADATA
# ============================================================

__version__ = "0.9.0"
__status__  = "Beta"
__author__  = "devdasher"
__license__ = "MIT"

APP_NAME: str = "HLS Converter"
APP_STATUS: str = __status__
AUTHOR: str = __author__
GITHUB_URL: str = "https://github.com/devdasher/hls-converter-cli"
PYPI_URL: str = "https://pypi.org/project/hls-converter-cli/"
LICENSE_NAME: str = __license__


__all__ = [
    # Public classes
    "HLSConverter",
    "CancellationToken",
    "ProgressEvent",
    "ConversionResult",
    # Config models
    "AppConfig",
    "VideoRequest",
    "AudioConfig",
    "SubtitleConfig",
    "VideoProfile",
    "AudioProfile",
    "AudioRequest",
    "AddToStreamOptions",
    # Media info
    "MediaInfo",
    "VideoStream",
    "AudioStream",
    "SubtitleStream",
    # Config construction
    "build_parser",
    "build_config",
    # Errors
    "ConverterError",
    # Metadata
    "__version__",
    "__status__",
    "__author__",
    "__license__",
    "APP_NAME",
    "AUTHOR",
    "GITHUB_URL",
    "PYPI_URL",
    "LICENSE_NAME",
]


def _bundled(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        # Running from a PyInstaller bundle — use the embedded copy.
        exe = "ffmpeg.exe" if name == "ffmpeg" else "ffprobe.exe"
        p = Path(base) / exe
        if p.exists():
            return str(p)
    return name  # fall back to PATH


# ============================================================
# DEFAULTS
# ============================================================

DEFAULT_FFMPEG  = _bundled("ffmpeg")
DEFAULT_FFPROBE = _bundled("ffprobe")

DEFAULT_OUTPUT_DIR_NAME = "stream"

DEFAULT_VIDEO_PROFILES = {
    144: 250, 240: 400, 360: 600, 480: 850, 540: 1000,
    720: 1300, 1080: 2800, 1440: 5000, 2160: 9000,
}
DEFAULT_VIDEO_QUALITIES = (480, 720, 1080)

DEFAULT_VIDEO_MAX_DIMENSIONS = {
    144: (256, 144), 240: (426, 240), 360: (640, 360),
    480: (854, 480), 540: (960, 540), 720: (1280, 720),
    1080: (1920, 1080), 1440: (2560, 1440), 2160: (3840, 2160),
}

VIDEO_LEVEL_MULTIPLIERS = {
    "data-saver": 0.55, "small": 0.75, "balanced": 1.00,
    "high": 1.50, "source": None,
}
DEFAULT_VIDEO_LEVEL = "balanced"

VIDEO_SOURCE_BITRATE_CAP = {
    144: 500, 240: 800, 360: 1200, 480: 1500, 540: 2000,
    720: 3000, 1080: 6000, 1440: 9000, 2160: 16000,
}

AUDIO_LEVEL_MULTIPLIERS = {
    "data-saver": 0.55, "small": 0.75, "balanced": 1.00,
    "high": 1.50, "source": None,
}
DEFAULT_AUDIO_LEVEL = "balanced"

AUDIO_CODEC_BITRATE_MULTIPLIERS = {
    "aac":        1.00,
    "libopus":    0.70, "opus": 0.70,
    "libmp3lame": 1.10, "mp3":  1.10,
    "ac3":        1.40,
    "eac3":       1.25,
    "flac":       None,
}

SUPPORTED_AUDIO_ENCODE_CODECS = {
    "aac", "libopus", "opus",
    "libmp3lame", "mp3",
    "ac3", "eac3",
}

HLS_COPY_AUDIO_CODECS = {"aac", "mp3", "ac3", "eac3"}

DEFAULT_AUDIO_PROFILES = (48, 64, 96, 128, 256, 320)

DEFAULT_VIDEO_CODEC = "libx264"
DEFAULT_VIDEO_PRESET = "medium"
DEFAULT_VIDEO_THREADS = 12

DEFAULT_AUDIO_CODEC = "aac"
DEFAULT_AUDIO_PROFILE = "aac_low"

DEFAULT_KEYFRAME_INTERVAL = 6.0
DEFAULT_SEGMENT_TIME = 6

VIDEO_ROOT = "video"
AUDIO_ROOT = "audio"
SUBTITLE_ROOT = "subtitles"

STREAM_METADATA_FILE = ".converter.json"

TEXT_SUBTITLE_CODECS = {
    "subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text",
}

AUDIO_EXTS = {".m4a", ".aac", ".mp3", ".ac3", ".eac3", ".opus",
              ".flac", ".wav", ".ogg", ".oga", ".mka"}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sbv"}
VIDEO_EXTS = {".mkv", ".mp4", ".mov", ".m4v", ".ts", ".webm", ".avi"}

RFC6381_VIDEO_CODECS = {
    "h264": "avc1.640028", "avc1": "avc1.640028",
    "hevc": "hvc1.1.6.L93.B0", "h265": "hvc1.1.6.L93.B0",
    "av1":  "av01.0.05M.08",
}
RFC6381_AUDIO_CODECS = {
    "aac": "mp4a.40.2", "mp3": "mp4a.6B",
    "ac3": "ac-3", "eac3": "ec-3", "opus": "opus",
}

VALID_AC3_BITRATES = [
    32, 40, 48, 56, 64, 80, 96, 112, 128,
    160, 192, 224, 256, 320, 384, 448, 512, 576, 640,
]

FINGERPRINT_CHUNK = 256 * 1024  # 256 KiB

# HLS version advertised in playlists. 6 is required for EXT-X-MAP and
# widely supported; the previous value (3) was technically non-compliant
# because EXT-X-MEDIA requires version 4+.
HLS_VERSION = 6

# Global dry-run flag. Set once from CLI args (or via the
# HLSConverter class for library consumers).
_DRY_RUN = False


# ============================================================
# ERRORS
# ============================================================

class ConverterError(Exception):
    """Top-level converter error."""


def fail(message: str) -> None:
    raise ConverterError(message)


# ============================================================
# THREAD-LOCAL CONTEXT (log / progress / cancel hooks)
# ============================================================
#
# These hooks are set by HLSConverter.convert() at the start of a run
# and cleared at the end. They live in thread-local storage so that two
# concurrent HLSConverter instances (on different threads) don't clash.
#
# When no hook is set (the CLI default), the module falls back to
# plain print() output, preserving the historical CLI behavior
# exactly.

_ctx = threading.local()


def _set_context(
    *,
    log_callback: Optional[Callable[[str, str], None]] = None,
    progress_callback: Optional[Callable[["ProgressEvent"], None]] = None,
    cancel_token: Optional["CancellationToken"] = None,
) -> None:
    _ctx.log_callback = log_callback
    _ctx.progress_callback = progress_callback
    _ctx.cancel_token = cancel_token


def _clear_context() -> None:
    _ctx.log_callback = None
    _ctx.progress_callback = None
    _ctx.cancel_token = None


def _get_log_callback():
    return getattr(_ctx, "log_callback", None)


def _get_progress_callback():
    return getattr(_ctx, "progress_callback", None)


def _get_cancel_token():
    return getattr(_ctx, "cancel_token", None)


# ============================================================
# LOGGING
# ============================================================

def _emit_log(level: str, message: str) -> None:
    cb = _get_log_callback()
    if cb is not None:
        try:
            cb(level, message)
            return
        except Exception:
            # Fall through to print if the callback blows up.
            pass
    # Default: CLI printing, identical to prior versions.
    if level == "INFO":
        print(f"[INFO] {message}")
    elif level == "OK":
        print(f"[OK]   {message}")
    elif level == "WARN":
        print(f"[WARN] {message}")
    elif level == "ERROR":
        print(f"[ERROR] {message}")
    else:
        print(f"[{level}] {message}")


def info(message: str) -> None:
    _emit_log("INFO", message)


def ok(message: str) -> None:
    _emit_log("OK", message)


def warn(message: str) -> None:
    _emit_log("WARN", message)


# ============================================================
# PROGRESS / CANCELLATION TYPES
# ============================================================

@dataclass
class ProgressEvent:
    """Emitted by HLSConverter.convert() when on_progress is set.

    stage:          "video" | "audio" | "subtitle" | "master" | "probing"
    label:          "1080p", "Track 1", "Subtitle 2", "copy" ...
    percent:        0..100 for this stage
    overall_percent: 0..100 across the whole job, or -1 if unknown
    eta_seconds:    estimate for THIS stage, or -1
    speed:          fps for video, or 0
    message:        short human-readable hint
    """
    stage: str
    label: str
    percent: float
    overall_percent: float = -1.0
    eta_seconds: float = -1.0
    speed: float = 0.0
    message: str = ""


@dataclass
class ConversionResult:
    """Returned by HLSConverter.convert() and .add_to_stream()."""
    success: bool
    error: Optional[str] = None
    output_dir: Optional[Path] = None
    master_playlist: Optional[Path] = None
    video_outputs: list[tuple[str, Path]] = field(default_factory=list)
    audio_outputs: list[tuple[int, Path]] = field(default_factory=list)
    subtitle_outputs: list[tuple[int, Path]] = field(default_factory=list)
    duration_seconds: float = 0.0


class CancellationToken:
    """Cooperative cancellation for a running conversion.

    Calling .cancel() from any thread will terminate any subprocesses
    currently registered by run_command(). The conversion functions
    will then raise ConverterError("Cancelled by user.") and the
    worker thread will unwind cleanly.
    """

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._procs: list[subprocess.Popen] = []
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            procs = list(self._procs)
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    # internal
    def _register_proc(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.append(proc)

    def _unregister_proc(self, proc: subprocess.Popen) -> None:
        with self._lock:
            try:
                self._procs.remove(proc)
            except ValueError:
                pass


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class VideoStream:
    index: int
    codec: str
    width: int
    height: int
    fps: float
    duration: float
    actual_bitrate: int = 0
    # 1-based ordinal among video streams (0 means "unknown / not set").
    # Added so multi-video files measure the right stream's bitrate.
    ordinal: int = 0


@dataclass
class AudioStream:
    index: int
    ordinal: int
    codec: str
    channels: int
    sample_rate: int
    language: str
    title: str
    duration: float
    actual_bitrate: int = 0


@dataclass
class SubtitleStream:
    index: int
    ordinal: int
    codec: str
    language: str
    title: str


@dataclass
class MediaInfo:
    duration: float
    videos: list[VideoStream]
    audios: list[AudioStream]
    subtitles: list[SubtitleStream]


@dataclass(frozen=True)
class VideoProfile:
    quality: str
    height: int
    bitrate: Optional[int] = None
    crf: Optional[int] = None


@dataclass(frozen=True)
class AudioProfile:
    bitrate: int
    channels: int

    @property
    def folder_name(self) -> str:
        return f"{self.bitrate}k-{self.channels}ch"


@dataclass(frozen=True)
class AudioRequest:
    track: int
    mode: str = "encode"


@dataclass
class VideoRequest:
    mode: str = "copy"
    label: Optional[str] = None
    profiles: list[VideoProfile] = field(default_factory=list)


@dataclass
class AudioConfig:
    requests: list[AudioRequest] = field(default_factory=list)
    encode_all: bool = False
    skip: bool = False
    profiles: list[AudioProfile] = field(default_factory=list)
    bitrate_overrides: dict[int, int] = field(default_factory=dict)
    channel_overrides: dict[int, int] = field(default_factory=dict)


@dataclass
class SubtitleConfig:
    mode: str = "auto"
    offset_ms: dict[int, int] = field(default_factory=dict)
    time_scale: Optional[tuple[float, float]] = None


@dataclass
class AppConfig:
    ffmpeg: str
    ffprobe: str
    output: Optional[Path]
    clean: bool
    skip_master: bool
    video: VideoRequest
    video_level: str
    video_rate_mode: str
    video_codec: str
    video_preset: str
    threads: int
    audio: AudioConfig
    audio_codec: str
    audio_profile: str
    subtitles: SubtitleConfig
    keyframe_interval: float
    segment_time: int
    default_audio_track: Optional[int]
    default_subtitle_track: Optional[int]


@dataclass
class AddToStreamOptions:
    """Extra options used only by HLSConverter.add_to_stream()."""
    audio_add_mode: str = "auto"
    audio_codec: Optional[str] = None
    audio_level: Optional[str] = None
    audio_profile: Optional[str] = None
    subtitle_offset_ms: Optional[str] = None
    subtitle_time_scale: Optional[str] = None
    track: Optional[int] = None
    language: Optional[str] = None
    title: Optional[str] = None
    skip_master: bool = False
    default_audio_track: Optional[int] = None
    default_subtitle_track: Optional[int] = None


# ============================================================
# GENERAL UTILITIES
# ============================================================

def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_fps(value: str) -> float:
    if not value:
        return 0.0
    if "/" in value:
        try:
            num, den = value.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0
    return safe_float(value)


def normalize_language(language: str) -> str:
    language = (language or "").strip().lower()
    aliases = {
        "per": "fa", "fas": "fa", "prs": "fa",
        "eng": "en", "ara": "ar",
        "ger": "de", "deu": "de",
        "fre": "fr", "fra": "fr",
        "spa": "es", "ita": "it",
        "rus": "ru", "jpn": "ja",
        "kor": "ko", "chi": "zh", "zho": "zh",
    }
    return aliases.get(language, language or "und")


def escape_m3u8(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
    )


def format_command(command: list[str]) -> str:
    return " ".join(
        f'"{item}"' if any(c.isspace() for c in item) else item
        for item in command
    )


def _print_command_failure(command: list[str], exc: subprocess.CalledProcessError) -> None:
    _emit_log("ERROR", "Command failed:")
    _emit_log("ERROR", format_command(command))
    if exc.stdout:
        _emit_log("ERROR", "--- stdout ---")
        for line in str(exc.stdout).splitlines():
            _emit_log("ERROR", line)
    if exc.stderr:
        _emit_log("ERROR", "--- stderr ---")
        for line in str(exc.stderr).splitlines():
            _emit_log("ERROR", line)


def run_command(
    command: list[str],
    *,
    capture_output: bool = False,
    progress: Optional[tuple[str, str, float]] = None,
) -> subprocess.CompletedProcess:
    """Run an external command.

    progress:
        Optional (stage, label, duration_seconds) tuple. When set, the
        command is executed with "-progress pipe:1" and ProgressEvent
        objects are emitted via the progress callback.

    Behavior:
        - If dry-run mode is active and this isn't a capture command,
          the command is printed and skipped.
        - If no progress and no cancel token are active, uses the fast
          subprocess.run path (identical to the historical CLI behavior).
        - If no progress but a cancel token is active, uses
          Popen + communicate() so stdout is captured normally while
          the process is still registered with the cancel token.
          (Previous versions incorrectly consumed stdout here as if it
          were ffmpeg progress output — that broke every ffprobe call.)
        - If progress is set, streams stdout for progress and monitors
          the cancel token for cooperative termination.
    """
    cancel_token = _get_cancel_token()

    if _DRY_RUN and not capture_output:
        print(f"[DRY-RUN] {format_command(command)}")
        return subprocess.CompletedProcess(command, 0, "", "")

    # ---------- Fast path: no cancel token, no progress -------------
    if cancel_token is None and progress is None:
        try:
            return subprocess.run(
                command,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=capture_output,
                check=True,
            )
        except FileNotFoundError:
            raise ConverterError(f"Executable not found: {command[0]}")
        except subprocess.CalledProcessError as exc:
            _print_command_failure(command, exc)
            raise ConverterError(
                f"Process exited with code {exc.returncode}."
            ) from exc

    # ---------- Capture path: no progress, but cancel token set -----
    # This is the case that used to break ffprobe_json().
    if progress is None:
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            raise ConverterError(f"Executable not found: {command[0]}")

        if cancel_token is not None:
            cancel_token._register_proc(proc)
        try:
            stdout_text, stderr_text = proc.communicate()
        finally:
            if cancel_token is not None:
                cancel_token._unregister_proc(proc)

        if cancel_token is not None and cancel_token.is_cancelled():
            raise ConverterError("Cancelled by user.")

        if proc.returncode != 0:
            fake_exc = subprocess.CalledProcessError(
                proc.returncode, command,
                output=stdout_text, stderr=stderr_text,
            )
            _print_command_failure(command, fake_exc)
            raise ConverterError(
                f"Process exited with code {proc.returncode}."
            )

        return subprocess.CompletedProcess(
            command, 0, stdout_text or "", stderr_text or "",
        )

    # ---------- Streaming progress path (ffmpeg encode/decode) ------
    cmd = list(command)
    # -progress is a global ffmpeg option; insert right after the
    # executable. -nostats keeps stderr clean.
    cmd = [cmd[0], "-progress", "pipe:1", "-nostats"] + cmd[1:]

    stage, label, duration = progress

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError:
        raise ConverterError(f"Executable not found: {cmd[0]}")

    if cancel_token is not None:
        cancel_token._register_proc(proc)

    stderr_lines: list[str] = []

    def drain_stderr() -> None:
        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_lines.append(line)
        except Exception:
            pass

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()

    progress_state: dict[str, str] = {}

    try:
        if proc.stdout is not None:
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\r\n")
                if not line:
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    progress_state[key] = value
                    if key == "progress":
                        if duration > 0:
                            _emit_progress_event(
                                progress_state, stage, label, duration,
                            )
                        progress_state = {}
                # Non key=value lines on stdout are unexpected with
                # -progress pipe:1 but harmless; ignore them.
    finally:
        proc.wait()
        stderr_thread.join(timeout=2.0)
        if cancel_token is not None:
            cancel_token._unregister_proc(proc)

    stderr_text = "".join(stderr_lines)
    stdout_text = ""  # we consumed stdout for progress

    if cancel_token is not None and cancel_token.is_cancelled():
        raise ConverterError("Cancelled by user.")

    if proc.returncode != 0:
        fake_exc = subprocess.CalledProcessError(
            proc.returncode, cmd,
            output=stdout_text, stderr=stderr_text,
        )
        _print_command_failure(cmd, fake_exc)
        raise ConverterError(
            f"Process exited with code {proc.returncode}."
        )

    return subprocess.CompletedProcess(cmd, 0, stdout_text, stderr_text)


def _emit_progress_event(
    state: dict[str, str],
    stage: str,
    label: str,
    duration: float,
) -> None:
    cb = _get_progress_callback()
    if cb is None:
        return

    # ffmpeg reports out_time_us and out_time_ms both in microseconds
    # (historical quirk: the "_ms" name is misleading).
    out_time_us_raw = state.get("out_time_us") or state.get("out_time_ms")
    out_time_s = 0.0
    if out_time_us_raw:
        try:
            out_time_s = float(out_time_us_raw) / 1_000_000.0
        except ValueError:
            out_time_s = 0.0

    percent = (out_time_s / duration) * 100.0 if duration > 0 else 0.0
    percent = max(0.0, min(100.0, percent))

    fps_str = state.get("fps", "")
    fps_val = safe_float(fps_str, 0.0) if fps_str else 0.0

    speed_str = state.get("speed", "")
    eta = -1.0
    if speed_str and out_time_s > 0 and duration > 0:
        speed_val = safe_float(speed_str.rstrip("x"), 0.0)
        if speed_val > 0:
            eta = max(0.0, (duration - out_time_s) / speed_val)

    event = ProgressEvent(
        stage=stage,
        label=label,
        percent=percent,
        overall_percent=-1.0,
        eta_seconds=eta,
        speed=fps_val,
        message=f"out_time={out_time_s:.2f}s",
    )
    try:
        cb(event)
    except Exception as exc:
        warn(f"Progress callback raised: {exc}")


def ffprobe_json(ffprobe: str, input_file: Path, args: list[str]) -> dict:
    result = run_command(
        [ffprobe, "-v", "error", "-of", "json", *args, str(input_file)],
        capture_output=True,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConverterError(f"Could not parse ffprobe JSON: {exc}") from exc


def ffprobe_text(ffprobe: str, input_file: Path, args: list[str]) -> str:
    result = run_command(
        [ffprobe, "-v", "error", *args, str(input_file)],
        capture_output=True,
    )
    return result.stdout


def executable_exists(executable: str) -> bool:
    if Path(executable).is_file():
        return True
    return shutil.which(executable) is not None


def ensure_executable(executable: str, name: str) -> None:
    if not executable_exists(executable):
        raise ConverterError(
            f"{name} was not found: {executable}\n"
            f"Use --{name.lower()} to specify its path."
        )


# ============================================================
# SOURCE FINGERPRINT
# ============================================================

def compute_source_fingerprint(path: Path) -> str:
    """Path-independent content fingerprint.

    Uses size + mtime + SHA1 of first 256 KiB. Ignores the file path
    so moving a file doesn't cause false "different source" errors.
    """
    try:
        st = path.stat()
        hasher = hashlib.sha1()
        with open(path, "rb") as fh:
            hasher.update(fh.read(FINGERPRINT_CHUNK))
        return f"{st.st_size}|{int(st.st_mtime)}|{hasher.hexdigest()[:16]}"
    except Exception as exc:
        warn(f"Could not compute fingerprint for {path}: {exc}")
        return ""


# ============================================================
# CLI PARSING HELPERS
# ============================================================

def parse_mapping_list(value: Optional[str], *, value_name: str) -> dict[str, int]:
    if not value:
        return {}
    result: dict[str, int] = {}
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ConverterError(
                f"Invalid {value_name} entry '{item}'. Expected KEY=VALUE."
            )
        key, raw_value = item.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key or not raw_value:
            raise ConverterError(
                f"Invalid {value_name} entry '{item}'. Expected KEY=VALUE."
            )
        number = safe_int(raw_value, -1)
        if number <= 0:
            raise ConverterError(f"Invalid {value_name} value in '{item}'.")
        if key in result:
            raise ConverterError(f"Duplicate {value_name} key: {key}")
        result[key] = number
    return result


def parse_int_mapping(value: Optional[str], *, value_name: str) -> dict[int, int]:
    raw = parse_mapping_list(value, value_name=value_name)
    result: dict[int, int] = {}
    for key, number in raw.items():
        track = safe_int(key, -1)
        if track <= 0:
            raise ConverterError(
                f"Invalid track number '{key}' in {value_name}."
            )
        result[track] = number
    return result


def parse_video_profile_tokens(value: str) -> list[str]:
    profiles: list[str] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if item in profiles:
            raise ConverterError(f"Duplicate video profile: {item}")
        profiles.append(item)
    if not profiles:
        raise ConverterError("--video-profiles cannot be empty.")
    return profiles


def parse_video_profile_token(
    token: str,
    bitrate_overrides: dict[str, int],
    crf_overrides: dict[str, int],
) -> VideoProfile:
    token = token.strip()
    if not token:
        raise ConverterError("Empty video profile.")
    if not token.isdigit():
        raise ConverterError(
            f"Encoded video profile '{token}' must be a numeric "
            f"height such as 480, 720, or 1080."
        )
    height = int(token)
    if height <= 0:
        raise ConverterError(f"Invalid video quality: {token}")

    bitrate = bitrate_overrides.get(token)
    crf = crf_overrides.get(token)
    if bitrate is not None and crf is not None:
        raise ConverterError(
            f"Video profile {token} has both bitrate and CRF. Choose one."
        )
    return VideoProfile(
        quality=f"{height}p",
        height=height,
        bitrate=bitrate,
        crf=crf,
    )


def parse_audio_profiles(value: Optional[str]) -> list[AudioProfile]:
    if not value:
        return [
            AudioProfile(bitrate=b, channels=(2 if b < 256 else 6))
            for b in DEFAULT_AUDIO_PROFILES
        ]
    profiles: list[AudioProfile] = []
    seen: set[tuple[int, int]] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) not in (1, 2):
            raise ConverterError(
                f"Invalid audio profile '{item}'. "
                f"Expected BITRATE or BITRATE:CHANNELS."
            )
        bitrate = safe_int(parts[0], -1)
        if bitrate <= 0:
            raise ConverterError(f"Invalid audio bitrate in '{item}'.")
        if len(parts) == 2:
            channels = safe_int(parts[1], -1)
            if channels <= 0:
                raise ConverterError(
                    f"Invalid audio channel count in '{item}'."
                )
        else:
            channels = 0
        key = (bitrate, channels)
        if key in seen:
            raise ConverterError(f"Duplicate audio profile: {item}")
        seen.add(key)
        profiles.append(AudioProfile(bitrate=bitrate, channels=channels))
    if not profiles:
        raise ConverterError("--audio-profiles cannot be empty.")
    return profiles


def parse_audio_requests(values: list[str]) -> tuple[bool, bool, list[AudioRequest]]:
    requests: list[AudioRequest] = []
    seen: set[int] = set()
    encode_all = False
    skip = False

    for value in values:
        for item in value.split(","):
            item = item.strip()
            if not item:
                continue
            low = item.lower()
            if low == "encode":
                encode_all = True
                continue
            if low == "none":
                skip = True
                continue
            parts = item.split(":")
            if len(parts) != 2:
                raise ConverterError(
                    f"Invalid --audio value '{item}'. "
                    f"Expected 'encode', 'none', or TRACK:encode."
                )
            track = safe_int(parts[0], -1)
            mode = parts[1].strip().lower()
            if track <= 0:
                raise ConverterError(f"Invalid audio track number: {parts[0]}")
            if mode != "encode":
                raise ConverterError(
                    f"Unsupported audio mode '{mode}'. Audio is copy by "
                    f"default; use TRACK:encode to enable encoding."
                )
            if track in seen:
                raise ConverterError(
                    f"Audio track {track} was specified more than once."
                )
            seen.add(track)
            requests.append(AudioRequest(track=track, mode=mode))

    if skip and (encode_all or requests):
        raise ConverterError(
            "'--audio none' cannot be combined with audio encoding requests."
        )
    if encode_all and requests:
        raise ConverterError(
            "Use either '--audio encode' or specific TRACK:encode requests, not both."
        )
    return encode_all, skip, requests


def parse_subtitle_offset(value: Optional[str]) -> dict[int, int]:
    if not value:
        return {}
    if "=" not in value:
        return {0: safe_int(value, 0)}
    result: dict[int, int] = {}
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ConverterError(
                f"Invalid --subtitle-offset-ms entry '{item}'. "
                f"Expected TRACK=MS."
            )
        k, v = item.split("=", 1)
        track = safe_int(k, -1)
        ms = safe_int(v, 0)
        if track <= 0:
            raise ConverterError(
                f"Invalid track number '{k}' in --subtitle-offset-ms."
            )
        result[track] = ms
    return result


def parse_subtitle_time_scale(value: Optional[str]) -> Optional[tuple[float, float]]:
    if not value:
        return None
    if "/" not in value:
        raise ConverterError(
            f"Invalid --subtitle-time-scale '{value}'. "
            f"Expected NUM/DEN, e.g. 25/23.976."
        )
    num, den = value.split("/", 1)
    return (safe_float(num, 0.0), safe_float(den, 0.0))


def parse_video_request(
    raw_mode: Optional[str],
    raw_label: Optional[str],
    raw_profiles: Optional[str],
    video_bitrates: dict[str, int],
    video_crfs: dict[str, int],
) -> VideoRequest:
    if raw_mode is None and raw_label is None:
        return VideoRequest(mode="copy", label=None)

    if raw_mode is None and raw_label is not None:
        label = raw_label.strip()
        if not label:
            raise ConverterError("--video-label cannot be empty.")
        if label.isdigit():
            label = f"{int(label)}p"
        return VideoRequest(mode="copy", label=label)

    value = raw_mode.strip().lower()
    if not value:
        raise ConverterError("--video-mode cannot be empty.")

    if value == "none":
        return VideoRequest(mode="none")

    if value == "copy":
        if raw_profiles:
            raise ConverterError("--video-profiles requires --video-mode encode.")
        if video_bitrates or video_crfs:
            raise ConverterError("--video-bitrate/--video-crf require --video-mode encode.")
        label = raw_label.strip() if raw_label else None
        if label and label.isdigit():
            label = f"{int(label)}p"
        return VideoRequest(mode="copy", label=label)

    if value == "encode":
        if raw_label:
            raise ConverterError("--video-label is only valid with --video-mode copy.")
        tokens = (
            parse_video_profile_tokens(raw_profiles)
            if raw_profiles
            else [str(q) for q in DEFAULT_VIDEO_QUALITIES]
        )
        profiles = [
            parse_video_profile_token(t, video_bitrates, video_crfs)
            for t in tokens
        ]
        return VideoRequest(mode="encode", profiles=profiles)

    raise ConverterError(
        f"Invalid --video-mode '{value}'. Expected copy, encode, or none."
    )


def _validate_audio_codec_for_encoding(codec: str, context: str) -> None:
    c = codec.lower()
    if c == "flac":
        raise ConverterError(
            f"{context}: FLAC is lossless and not supported for HLS audio "
            f"encoding in this tool. Choose one of: "
            f"{', '.join(sorted(SUPPORTED_AUDIO_ENCODE_CODECS))}."
        )
    if c not in SUPPORTED_AUDIO_ENCODE_CODECS:
        raise ConverterError(
            f"{context}: unsupported audio codec '{codec}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_AUDIO_ENCODE_CODECS))}."
        )


def build_config(args: argparse.Namespace) -> AppConfig:
    video_bitrates = parse_mapping_list(args.video_bitrate, value_name="--video-bitrate")
    video_crfs = parse_mapping_list(args.video_crf, value_name="--video-crf")

    raw_label = args.video_label
    video_mode = args.video_mode

    if raw_label is None and video_mode is not None:
        vm = video_mode.strip().lower()
        if vm not in ("copy", "encode", "none"):
            raw_label = video_mode.strip()
            video_mode = None

    video = parse_video_request(
        video_mode, raw_label, args.video_profiles,
        video_bitrates, video_crfs,
    )

    audio_encode_all, audio_skip, audio_requests = parse_audio_requests(args.audio)

    audio_profiles = parse_audio_profiles(args.audio_profiles)
    audio_bitrates = parse_int_mapping(args.audio_bitrate, value_name="--audio-bitrate")
    audio_channels = parse_int_mapping(args.audio_channels, value_name="--audio-channels")

    if not audio_skip and not (audio_encode_all or audio_requests):
        if args.audio_profiles:
            raise ConverterError("--audio-profiles requires audio encoding.")
        if args.audio_bitrate:
            raise ConverterError("--audio-bitrate requires audio encoding.")
        if args.audio_channels:
            raise ConverterError("--audio-channels requires audio encoding.")

    if audio_encode_all or audio_requests:
        _validate_audio_codec_for_encoding(args.audio_codec, "--audio-codec")

    if args.threads <= 0:
        raise ConverterError("--threads must be greater than zero.")
    if args.keyframe_interval <= 0:
        raise ConverterError("--keyframe-interval must be greater than zero.")
    if args.segment_time <= 0:
        raise ConverterError("--segment-time must be greater than zero.")

    if args.video_level not in VIDEO_LEVEL_MULTIPLIERS:
        raise ConverterError(
            f"Invalid --video-level '{args.video_level}'. "
            f"Choose one of: {', '.join(VIDEO_LEVEL_MULTIPLIERS.keys())}."
        )

    if args.video_rate_mode not in ("auto", "crf", "abr", "2pass"):
        raise ConverterError(
            f"Invalid --video-rate-mode '{args.video_rate_mode}'. "
            f"Expected auto, crf, abr, or 2pass."
        )

    if args.video_rate_mode == "2pass":
        if video.mode != "encode":
            raise ConverterError(
                "--video-rate-mode 2pass requires --video-mode encode."
            )
        for p in video.profiles:
            if p.crf is not None:
                raise ConverterError(
                    f"Video profile {p.quality} uses CRF, which is "
                    f"incompatible with --video-rate-mode 2pass."
                )
            if (p.bitrate is None
                    and args.video_level == "balanced"
                    and p.height not in DEFAULT_VIDEO_PROFILES):
                raise ConverterError(
                    f"No default bitrate for {p.height}p. Use "
                    f"--video-bitrate {p.height}=N or --video-level source."
                )

    if args.default_audio_track is not None and args.default_audio_track <= 0:
        raise ConverterError("--default-audio-track must be > 0.")
    if args.default_subtitle_track is not None and args.default_subtitle_track <= 0:
        raise ConverterError("--default-subtitle-track must be > 0.")

    subtitle_mode = args.subtitles
    if video.mode == "none" and audio_skip and subtitle_mode == "none":
        raise ConverterError(
            "Nothing to do: --video none, --audio none, and --subtitles none."
        )

    return AppConfig(
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
        output=Path(args.output).expanduser() if args.output else None,
        clean=args.clean,
        skip_master=args.skip_master,
        video=video,
        video_level=args.video_level,
        video_rate_mode=args.video_rate_mode,
        video_codec=args.video_codec,
        video_preset=args.video_preset,
        threads=args.threads,
        audio=AudioConfig(
            requests=audio_requests,
            encode_all=audio_encode_all,
            skip=audio_skip,
            profiles=audio_profiles,
            bitrate_overrides=audio_bitrates,
            channel_overrides=audio_channels,
        ),
        audio_codec=args.audio_codec,
        audio_profile=args.audio_profile,
        subtitles=SubtitleConfig(
            mode=subtitle_mode,
            offset_ms=parse_subtitle_offset(args.subtitle_offset_ms),
            time_scale=parse_subtitle_time_scale(args.subtitle_time_scale),
        ),
        keyframe_interval=args.keyframe_interval,
        segment_time=args.segment_time,
        default_audio_track=args.default_audio_track,
        default_subtitle_track=args.default_subtitle_track,
    )


# ============================================================
# MEDIA INSPECTION
# ============================================================

def read_media_information(ffprobe: str, input_file: Path) -> MediaInfo:
    info("Reading media streams with ffprobe...")

    data = ffprobe_json(
        ffprobe, input_file,
        [
            "-show_streams", "-show_format",
            "-show_entries",
            (
                "format=duration:"
                "stream=index,codec_type,codec_name,width,height,"
                "avg_frame_rate,r_frame_rate,channels,sample_rate,duration:"
                "stream_tags=language,title"
            ),
        ],
    )

    fmt = data.get("format", {})
    format_duration = safe_float(fmt.get("duration"))

    videos: list[VideoStream] = []
    audios: list[AudioStream] = []
    subtitles: list[SubtitleStream] = []
    video_ordinal = 0
    audio_ordinal = 0
    subtitle_ordinal = 0

    for stream in data.get("streams", []):
        index = safe_int(stream.get("index"))
        codec_type = stream.get("codec_type")
        tags = stream.get("tags") or {}

        language = normalize_language(str(tags.get("language", "") or ""))
        title = str(tags.get("title", "") or "").strip()

        if codec_type == "video":
            video_ordinal += 1
            duration = safe_float(stream.get("duration"), format_duration)
            fps = parse_fps(
                stream.get("avg_frame_rate")
                or stream.get("r_frame_rate")
                or "0/1"
            )
            videos.append(VideoStream(
                index=index,
                codec=str(stream.get("codec_name", "")),
                width=safe_int(stream.get("width")),
                height=safe_int(stream.get("height")),
                fps=fps,
                duration=duration,
                ordinal=video_ordinal,
            ))
        elif codec_type == "audio":
            audio_ordinal += 1
            duration = safe_float(stream.get("duration"), format_duration)
            audios.append(AudioStream(
                index=index,
                ordinal=audio_ordinal,
                codec=str(stream.get("codec_name", "")),
                channels=max(1, safe_int(stream.get("channels"), 1)),
                sample_rate=safe_int(stream.get("sample_rate")),
                language=language,
                title=title,
                duration=duration,
            ))
        elif codec_type == "subtitle":
            subtitle_ordinal += 1
            subtitles.append(SubtitleStream(
                index=index,
                ordinal=subtitle_ordinal,
                codec=str(stream.get("codec_name", "")),
                language=language,
                title=title,
            ))

    if format_duration <= 0:
        format_duration = max(
            [v.duration for v in videos if v.duration > 0] or [0.0]
        )

    info(
        f"Video: {len(videos)} | Audio: {len(audios)} | "
        f"Subtitles: {len(subtitles)}"
    )
    return MediaInfo(
        duration=format_duration,
        videos=videos,
        audios=audios,
        subtitles=subtitles,
    )


def measure_stream_bitrate(
    ffprobe: str, input_file: Path, *, selector: str, fallback_duration: float,
) -> int:
    text = ffprobe_text(
        ffprobe, input_file,
        [
            "-select_streams", selector,
            "-show_entries", "packet=stream_index,size",
            "-of", "csv=p=0",
        ],
    )
    total_bytes = 0
    for line in text.splitlines():
        parts = [p.strip() for p in line.strip().split(",")]
        if not parts:
            continue
        size = safe_int(parts[-1], 0)
        if size > 0:
            total_bytes += size
    if total_bytes <= 0 or fallback_duration <= 0:
        return 0
    return max(1, round(total_bytes * 8 / fallback_duration / 1000))


def measure_video_bitrate(ffprobe, input_file, video, fallback_duration):
    """Measure the average bitrate of `video`.

    Uses the video stream's 1-based ordinal so multi-video files
    measure the right stream (previous versions always measured v:0).
    """
    duration = video.duration or fallback_duration
    ordinal = video.ordinal if video.ordinal > 0 else 1
    br = measure_stream_bitrate(
        ffprobe, input_file,
        selector=f"v:{ordinal - 1}", fallback_duration=duration,
    )
    video.actual_bitrate = br
    return br


def measure_audio_bitrate(ffprobe, input_file, audio, fallback_duration):
    duration = audio.duration or fallback_duration
    br = measure_stream_bitrate(
        ffprobe, input_file,
        selector=f"a:{audio.ordinal - 1}", fallback_duration=duration,
    )
    audio.actual_bitrate = br
    return br


def inspect_bitrates(ffprobe: str, input_file: Path, media: MediaInfo) -> None:
    info("--- Bitrate analysis ---")
    for video in media.videos:
        try:
            br = measure_video_bitrate(ffprobe, input_file, video, media.duration)
            info(f"Video stream {video.index}: ~ {br} kbps actual average")
        except Exception as exc:
            warn(f"Could not measure video stream {video.index}: {exc}")
    for audio in media.audios:
        try:
            br = measure_audio_bitrate(ffprobe, input_file, audio, media.duration)
            info(
                f"Audio {audio.ordinal}: ~ {br} kbps | "
                f"{audio.channels}ch | {audio.codec}"
            )
        except Exception as exc:
            warn(f"Could not measure audio {audio.ordinal}: {exc}")
    info("------------------------")


def probe_playlist_duration(playlist_path: Path) -> float:
    try:
        text = playlist_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0.0
    total = 0.0
    for line in text.splitlines():
        if line.startswith("#EXTINF:"):
            val = line[len("#EXTINF:"):].strip().rstrip(",")
            total += safe_float(val, 0.0)
    return total


# ============================================================
# AUDIO POLICY
# ============================================================

def automatic_audio_channels(source_channels: int, bitrate: int) -> int:
    source_channels = max(1, source_channels)
    if source_channels <= 2:
        return source_channels
    if source_channels <= 6:
        return 2 if bitrate < 256 else source_channels
    return 2 if bitrate < 320 else source_channels


def resolve_audio_profile(source, requested, *, explicit_channels=None):
    if source.actual_bitrate <= 0:
        return None
    effective_bitrate = min(requested.bitrate, source.actual_bitrate)
    if effective_bitrate <= 0:
        return None
    if explicit_channels is not None:
        channels = min(max(1, explicit_channels), max(1, source.channels))
    elif requested.channels > 0:
        channels = min(requested.channels, max(1, source.channels))
    else:
        channels = automatic_audio_channels(source.channels, effective_bitrate)
    return AudioProfile(bitrate=effective_bitrate, channels=channels)


def deduplicate_audio_profiles(profiles):
    unique: dict[tuple[int, int], AudioProfile] = {}
    for p in profiles:
        unique[(p.bitrate, p.channels)] = p
    return sorted(unique.values(), key=lambda p: (p.bitrate, p.channels))


def audio_profiles_for_track(audio, config: AudioConfig) -> list[AudioProfile]:
    explicit_channels = config.channel_overrides.get(audio.ordinal)

    if audio.ordinal in config.bitrate_overrides:
        requested = [
            AudioProfile(
                bitrate=config.bitrate_overrides[audio.ordinal],
                channels=explicit_channels or 0,
            )
        ]
    else:
        requested = list(config.profiles)

    profiles: list[AudioProfile] = []
    for req in requested:
        resolved = resolve_audio_profile(
            audio, req, explicit_channels=explicit_channels,
        )
        if resolved is not None:
            profiles.append(resolved)
    return deduplicate_audio_profiles(profiles)


def codec_bitrate_multiplier(codec: str) -> Optional[float]:
    return AUDIO_CODEC_BITRATE_MULTIPLIERS.get(codec.lower())


def compute_effective_audio_bitrate(
    aac_reference_bitrate: int,
    target_codec: str,
    level: str,
    source_bitrate: int = 0,
    source_codec: str = "",
) -> int:
    ref = aac_reference_bitrate

    if source_bitrate > 0 and source_codec:
        src_mult = codec_bitrate_multiplier(source_codec)
        if src_mult:
            ref = int(source_bitrate / src_mult)

    if level == "source":
        if source_bitrate > 0:
            ref = source_bitrate
    else:
        lm = AUDIO_LEVEL_MULTIPLIERS.get(level, 1.0) or 1.0
        ref = int(ref * lm)

    tgt_mult = codec_bitrate_multiplier(target_codec)
    if tgt_mult is None:
        return 0
    result = int(ref * tgt_mult)

    if source_bitrate > 0 and target_codec.lower() == (source_codec or "").lower():
        if result > source_bitrate:
            return max(32, source_bitrate)
    return max(32, result)


def codec_specific_audio_args(
    codec: str,
    bitrate: int,
    channels: int,
    profile: Optional[str] = None,
) -> list[str]:
    c = codec.lower()

    if c == "flac":
        raise ConverterError(
            "FLAC is not supported for HLS audio encoding. "
            "Use aac, libopus, libmp3lame, ac3, or eac3."
        )

    if c == "aac":
        args = ["-c:a", "aac"]
        if profile:
            args += ["-profile:a", profile]
        args += ["-b:a", f"{bitrate}k", "-ac", str(channels)]
        return args

    if c in ("libopus", "opus"):
        return [
            "-c:a", "libopus",
            "-b:a", f"{bitrate}k",
            "-ac", str(channels),
            "-vbr", "on",
        ]

    if c in ("libmp3lame", "mp3"):
        return [
            "-c:a", "libmp3lame",
            "-b:a", f"{bitrate}k",
            "-ac", str(channels),
        ]

    if c == "ac3":
        chosen = min(VALID_AC3_BITRATES, key=lambda x: abs(x - bitrate))
        return [
            "-c:a", "ac3",
            "-b:a", f"{chosen}k",
            "-ac", str(channels),
        ]

    if c == "eac3":
        return [
            "-c:a", "eac3",
            "-b:a", f"{bitrate}k",
            "-ac", str(channels),
        ]

    raise ConverterError(
        f"Unsupported audio codec '{codec}'. "
        f"Supported: {', '.join(sorted(SUPPORTED_AUDIO_ENCODE_CODECS))}."
    )


# ============================================================
# OUTPUT / RESUME
# ============================================================

def prepare_target_directory(target_dir: Path, playlist_name: str = "playlist.m3u8") -> bool:
    playlist = target_dir / playlist_name
    if playlist.exists():
        return True

    if _DRY_RUN:
        print(f"[DRY-RUN] Would prepare directory: {target_dir}")
        return False

    if target_dir.exists():
        warn(f"Incomplete output detected: {target_dir}")
        warn("Removing only this incomplete directory...")
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    return False


def write_metadata(stream_root: Path, *, media: MediaInfo, input_file: Path) -> None:
    if _DRY_RUN:
        return
    data = {
        "source": {
            "path": str(input_file.resolve()),
            "fingerprint": compute_source_fingerprint(input_file),
            "duration": media.duration,
            "videos": [
                {"index": v.index, "ordinal": v.ordinal, "codec": v.codec,
                 "width": v.width, "height": v.height,
                 "fps": v.fps, "actual_bitrate": v.actual_bitrate}
                for v in media.videos
            ],
            "audios": [
                {"index": a.index, "ordinal": a.ordinal,
                 "codec": a.codec, "channels": a.channels,
                 "sample_rate": a.sample_rate, "language": a.language,
                 "title": a.title, "actual_bitrate": a.actual_bitrate}
                for a in media.audios
            ],
            "subtitles": [
                {"index": s.index, "ordinal": s.ordinal,
                 "codec": s.codec, "language": s.language,
                 "title": s.title}
                for s in media.subtitles
            ],
        }
    }
    (stream_root / STREAM_METADATA_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_metadata_raw(stream_root: Path) -> dict:
    file = stream_root / STREAM_METADATA_FILE
    if not file.exists():
        return {"source": {"videos": [], "audios": [], "subtitles": []}}
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:
        warn(f"Could not read {file.name}: {exc}")
        return {"source": {"videos": [], "audios": [], "subtitles": []}}


def save_metadata_raw(stream_root: Path, data: dict) -> None:
    if _DRY_RUN:
        print(f"[DRY-RUN] Would write metadata: {stream_root / STREAM_METADATA_FILE}")
        return
    (stream_root / STREAM_METADATA_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============================================================
# VIDEO DIMENSION POLICY
# ============================================================

def video_max_dimensions(height: int) -> tuple[int, int]:
    if height <= 0:
        raise ConverterError(f"Invalid video profile height: {height}")
    if height in DEFAULT_VIDEO_MAX_DIMENSIONS:
        return DEFAULT_VIDEO_MAX_DIMENSIONS[height]
    width = round(height * 16 / 9)
    width = max(2, width - width % 2)
    return width, height


def calculate_output_dimensions(
    source_width: int, source_height: int, target_height: int,
) -> tuple[int, int]:
    if source_width <= 0 or source_height <= 0:
        return 0, 0
    max_width, max_height = video_max_dimensions(target_height)
    scale = min(max_width / source_width, max_height / source_height, 1.0)
    width = max(2, int(round(source_width * scale)))
    height = max(2, int(round(source_height * scale)))
    width -= width % 2
    height -= height % 2
    return (max(2, width), max(2, height))


# ============================================================
# BITRATE COMPUTATION (video, level-aware)
# ============================================================

def compute_effective_bitrate(
    profile: VideoProfile, source_bitrate: int, level: str,
) -> int:
    if profile.bitrate is not None:
        base = profile.bitrate
    elif level == "source":
        if source_bitrate > 0:
            cap = VIDEO_SOURCE_BITRATE_CAP.get(profile.height, 999999)
            base = min(int(source_bitrate * 0.9), cap)
        else:
            base = DEFAULT_VIDEO_PROFILES.get(profile.height, 0)
    else:
        default = DEFAULT_VIDEO_PROFILES.get(profile.height, 0)
        mult = VIDEO_LEVEL_MULTIPLIERS.get(level, 1.0) or 1.0
        base = int(default * mult)
    if source_bitrate > 0 and base > source_bitrate:
        return source_bitrate
    return base


def determine_rate_mode(config: AppConfig, profile: VideoProfile) -> str:
    if config.video_rate_mode == "auto":
        return "crf" if profile.crf is not None else "abr"
    return config.video_rate_mode


# ============================================================
# VIDEO CONVERSION
# ============================================================

def determine_copy_quality(video: VideoStream, requested_label: Optional[str]) -> str:
    if requested_label:
        return requested_label
    if video.height > 0:
        return f"{video.height}p"
    return "source"


def convert_video_copy(
    ffmpeg: str, input_file: Path, stream_root: Path,
    video: VideoStream, quality: str, segment_time: int,
    duration_hint: float = 0.0,
) -> Path:
    output_dir = stream_root / VIDEO_ROOT / quality
    playlist = output_dir / "playlist.m3u8"

    if prepare_target_directory(output_dir):
        ok(f"Video {quality} already complete. Skipping.")
        return playlist

    info(f"Copying video as {quality} ({video.codec}, {video.width}x{video.height})")

    command = [
        ffmpeg, "-hide_banner", "-y", "-i", str(input_file),
        "-map", f"0:{video.index}",
        "-c:v", "copy", "-an", "-sn", "-dn",
        "-copyts", "-start_at_zero",
        "-muxdelay", "0", "-muxpreload", "0",
        "-f", "hls",
        "-hls_time", str(segment_time),
        "-hls_playlist_type", "vod",
        "-hls_flags", "independent_segments",
        "-hls_segment_filename", str(output_dir / "%05d.ts"),
        str(playlist),
    ]
    run_command(
        command,
        progress=("video", quality, duration_hint) if duration_hint > 0 else None,
    )

    if not playlist.exists() and not _DRY_RUN:
        raise ConverterError(f"Video playlist was not created: {playlist}")
    ok(f"Video {quality} complete.")
    return playlist


def convert_video_encode(
    config: AppConfig, input_file: Path, stream_root: Path,
    video: VideoStream, profile: VideoProfile,
    duration_hint: float = 0.0,
) -> Path:
    output_dir = stream_root / VIDEO_ROOT / profile.quality
    playlist = output_dir / "playlist.m3u8"

    if prepare_target_directory(output_dir):
        ok(f"Video {profile.quality} already complete. Skipping.")
        return playlist

    rate_mode = determine_rate_mode(config, profile)

    effective_bitrate = None
    if rate_mode in ("abr", "2pass"):
        effective_bitrate = compute_effective_bitrate(
            profile, video.actual_bitrate, config.video_level,
        )
        if effective_bitrate <= 0:
            raise ConverterError(
                f"No bitrate defined for video profile {profile.quality}."
            )

    info(f"Encoding video {profile.quality} ({profile.height}p) "
         f"[mode={rate_mode}]")
    if effective_bitrate is not None:
        info(f"  Target bitrate: {effective_bitrate} kbps "
             f"(level={config.video_level})")

    max_w, max_h = video_max_dimensions(profile.height)
    scale_expr = (
        f"scale={max_w}:{max_h}:"
        "force_original_aspect_ratio=decrease:"
        "force_divisible_by=2:flags=lanczos"
    )

    encode_head = [
        config.ffmpeg, "-hide_banner", "-y",
        "-i", str(input_file),
        "-map", f"0:{video.index}",
        "-c:v", config.video_codec,
        "-preset", config.video_preset,
        "-threads", str(config.threads),
        "-vf", scale_expr,
        "-pix_fmt", "yuv420p",
    ]

    keyframe_args: list[str] = []
    if config.keyframe_interval > 0:
        keyframe_args = [
            "-force_key_frames",
            f"expr:gte(t,n_forced*{config.keyframe_interval})",
        ]

    progress_tuple = (
        ("video", profile.quality, duration_hint) if duration_hint > 0 else None
    )

    if rate_mode == "2pass":
        passlog = output_dir / "ffmpeg2pass"
        passlog_arg = str(passlog)

        info("  Two-pass pass 1/2: analyzing...")
        pass1 = encode_head + [
            "-b:v", f"{effective_bitrate}k",
            "-pass", "1",
            "-passlogfile", passlog_arg,
        ] + keyframe_args + [
            "-an", "-sn", "-dn",
            "-f", "null", "-",
        ]
        if progress_tuple:
            pass1_progress = (
                progress_tuple[0],
                f"{progress_tuple[1]} (pass 1)",
                progress_tuple[2],
            )
        else:
            pass1_progress = None
        run_command(pass1, progress=pass1_progress)

        info("  Two-pass pass 2/2: encoding...")
        pass2 = encode_head + [
            "-b:v", f"{effective_bitrate}k",
            "-maxrate", f"{effective_bitrate}k",
            "-bufsize", f"{effective_bitrate * 2}k",
            "-pass", "2",
            "-passlogfile", passlog_arg,
        ] + keyframe_args + [
            "-an", "-sn", "-dn",
            "-copyts", "-start_at_zero",
            "-muxdelay", "0", "-muxpreload", "0",
            "-f", "hls",
            "-hls_time", str(config.segment_time),
            "-hls_playlist_type", "vod",
            "-hls_flags", "independent_segments",
            "-hls_segment_filename", str(output_dir / "%05d.ts"),
            str(playlist),
        ]
        if progress_tuple:
            pass2_progress = (
                progress_tuple[0],
                f"{progress_tuple[1]} (pass 2)",
                progress_tuple[2],
            )
        else:
            pass2_progress = None
        run_command(pass2, progress=pass2_progress)

        if not _DRY_RUN:
            for f in output_dir.glob(passlog.name + "*"):
                try:
                    f.unlink()
                except Exception:
                    pass
    else:
        command = encode_head + ["-an", "-sn", "-dn",
                                 "-copyts", "-start_at_zero",
                                 "-muxdelay", "0", "-muxpreload", "0"]

        if rate_mode == "crf":
            command += ["-crf", str(profile.crf)]
        else:
            command += [
                "-b:v", f"{effective_bitrate}k",
                "-maxrate", f"{effective_bitrate}k",
                "-bufsize", f"{effective_bitrate * 2}k",
            ]

        command += keyframe_args + [
            "-f", "hls",
            "-hls_time", str(config.segment_time),
            "-hls_playlist_type", "vod",
            "-hls_flags", "independent_segments",
            "-hls_segment_filename", str(output_dir / "%05d.ts"),
            str(playlist),
        ]
        run_command(command, progress=progress_tuple)

    if not playlist.exists() and not _DRY_RUN:
        raise ConverterError(f"Video playlist was not created: {playlist}")
    ok(f"Video {profile.quality} complete.")
    return playlist


# ============================================================
# AUDIO CONVERSION
# ============================================================

def convert_audio_copy(
    ffmpeg: str, input_file: Path, stream_root: Path,
    audio: AudioStream, segment_time: int,
    duration_hint: float = 0.0,
) -> Path:
    bitrate = audio.actual_bitrate
    if bitrate <= 0:
        raise ConverterError(
            f"Cannot create a copy audio rendition for track "
            f"{audio.ordinal}: source bitrate is unknown."
        )
    channels = max(1, audio.channels)
    profile = AudioProfile(bitrate=bitrate, channels=channels)

    output_dir = stream_root / AUDIO_ROOT / str(audio.ordinal) / profile.folder_name
    playlist = output_dir / "playlist.m3u8"

    if prepare_target_directory(output_dir):
        ok(f"Audio {audio.ordinal} {profile.folder_name} already complete. Skipping.")
        return playlist

    info(f"Copying audio {audio.ordinal} as {profile.folder_name}")

    command = [
        ffmpeg, "-hide_banner", "-y", "-i", str(input_file),
        "-map", f"0:{audio.index}",
        "-vn", "-sn", "-dn",
        "-c:a", "copy",
        "-copyts", "-start_at_zero",
        "-muxdelay", "0", "-muxpreload", "0",
        "-f", "hls",
        "-hls_time", str(segment_time),
        "-hls_playlist_type", "vod",
        "-hls_flags", "independent_segments",
        "-hls_segment_filename", str(output_dir / "%05d.ts"),
        str(playlist),
    ]
    progress_tuple = (
        ("audio", f"Track {audio.ordinal}", duration_hint)
        if duration_hint > 0 else None
    )
    run_command(command, progress=progress_tuple)

    if not playlist.exists() and not _DRY_RUN:
        raise ConverterError(f"Audio playlist was not created: {playlist}")
    ok(f"Audio {audio.ordinal} {profile.folder_name} complete.")
    return playlist


def convert_audio_encode(
    config: AppConfig, input_file: Path, stream_root: Path,
    audio: AudioStream, profile: AudioProfile,
    duration_hint: float = 0.0,
) -> Path:
    output_dir = stream_root / AUDIO_ROOT / str(audio.ordinal) / profile.folder_name
    playlist = output_dir / "playlist.m3u8"

    if prepare_target_directory(output_dir):
        ok(f"Audio {audio.ordinal} {profile.folder_name} already complete. Skipping.")
        return playlist

    info(f"Encoding audio {audio.ordinal} -> {profile.folder_name}")

    codec_args = codec_specific_audio_args(
        config.audio_codec,
        profile.bitrate,
        profile.channels,
        config.audio_profile,
    )

    command = [
        config.ffmpeg, "-hide_banner", "-y", "-i", str(input_file),
        "-map", f"0:{audio.index}",
        "-vn", "-sn", "-dn",
    ] + codec_args + [
        "-copyts", "-start_at_zero",
        "-muxdelay", "0", "-muxpreload", "0",
        "-f", "hls",
        "-hls_time", str(config.segment_time),
        "-hls_playlist_type", "vod",
        "-hls_flags", "independent_segments",
        "-hls_segment_filename", str(output_dir / "%05d.ts"),
        str(playlist),
    ]
    progress_tuple = (
        ("audio", f"Track {audio.ordinal}", duration_hint)
        if duration_hint > 0 else None
    )
    run_command(command, progress=progress_tuple)

    if not playlist.exists() and not _DRY_RUN:
        raise ConverterError(f"Audio playlist was not created: {playlist}")
    ok(f"Audio {audio.ordinal} {profile.folder_name} complete.")
    return playlist


# ============================================================
# SUBTITLES
# ============================================================

def probe_first_video_pts(ffprobe: str, ts_file: Path) -> float:
    try:
        text = ffprobe_text(
            ffprobe, ts_file,
            [
                "-select_streams", "v:0",
                "-show_entries", "packet=pts_time",
                "-read_intervals", "%+#1",
                "-of", "csv=p=0",
            ],
        )
        for line in text.splitlines():
            line = line.strip().rstrip(",")
            if line:
                return safe_float(line, 0.0)
    except Exception:
        pass
    return 0.0


def apply_time_scale_to_vtt(vtt_path: Path, num: float, den: float) -> None:
    if den <= 0:
        return
    ratio = num / den

    def fix_timestamp(ts: str) -> str:
        parts = ts.split(":")
        if len(parts) != 3:
            return ts
        try:
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
        except ValueError:
            return ts
        total = h * 3600 + m * 60 + s
        total *= ratio
        nh = int(total // 3600)
        nm = int((total % 3600) // 60)
        ns = total - nh * 3600 - nm * 60
        return f"{nh:02d}:{nm:02d}:{ns:06.3f}"

    try:
        content = vtt_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return
    if content.startswith("\ufeff"):
        content = content[1:]
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    out_lines: list[str] = []
    for line in content.split("\n"):
        if "-->" in line:
            before, after = line.split("-->", 1)
            after_parts = after.strip().split()
            if after_parts:
                fixed = fix_timestamp(after_parts[0])
                rest = " ".join(after_parts[1:])
                line = f"{before.strip()} --> {fixed}" + (f" {rest}" if rest else "")
        out_lines.append(line)
    vtt_path.write_text("\n".join(out_lines), encoding="utf-8")


def inject_timestamp_map(vtt_path: Path, mpegts: int) -> None:
    # Guard against negative timestamps: MPEGTS is a 33-bit unsigned
    # counter in the transport stream, so a negative value is invalid.
    if mpegts < 0:
        warn(
            f"Subtitle offset produced a negative MPEGTS value "
            f"({mpegts}); clamping to 0. Check --subtitle-offset-ms."
        )
        mpegts = 0

    try:
        content = vtt_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        warn(f"Could not read {vtt_path}: {exc}")
        return

    if content.startswith("\ufeff"):
        content = content[1:]
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = content.split("\n")

    filtered: list[str] = []
    for line in lines:
        if line.strip().upper().startswith("X-TIMESTAMP-MAP"):
            continue
        filtered.append(line)

    header = f"X-TIMESTAMP-MAP=MPEGTS:{mpegts},LOCAL:00:00:00.000"

    out: list[str] = []
    injected = False
    for line in filtered:
        out.append(line)
        if not injected and line.strip().upper() == "WEBVTT":
            out.append(header)
            injected = True

    if not injected:
        for i, line in enumerate(out):
            if line.strip():
                out.insert(i + 1, header)
                injected = True
                break

    vtt_path.write_text("\n".join(out), encoding="utf-8")


def write_subtitle_playlist(output_dir: Path, vtt_name: str, media_duration: float) -> Path:
    playlist = output_dir / "playlist.m3u8"
    duration_seconds = max(1.0, float(media_duration))
    target_duration = int(duration_seconds) + 1
    playlist.write_text(
        "\n".join([
            "#EXTM3U",
            f"#EXT-X-VERSION:{HLS_VERSION}",
            f"#EXT-X-TARGETDURATION:{target_duration}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            f"#EXTINF:{duration_seconds:.3f},",
            vtt_name,
            "#EXT-X-ENDLIST",
            "",
        ]),
        encoding="utf-8",
    )
    return playlist


def convert_subtitle(
    ffmpeg: str, ffprobe: str, input_file: Path, stream_root: Path,
    subtitle: SubtitleStream, media_duration: float,
    video_pts_seconds: float, offset_ms: int,
    time_scale: Optional[tuple[float, float]],
) -> Optional[Path]:
    if subtitle.codec.lower() not in TEXT_SUBTITLE_CODECS:
        warn(
            f"Subtitle {subtitle.ordinal}: {subtitle.codec} is not a "
            f"supported text subtitle. Skipping."
        )
        return None

    output_dir = stream_root / SUBTITLE_ROOT / str(subtitle.ordinal)
    playlist = output_dir / "playlist.m3u8"

    if prepare_target_directory(output_dir):
        ok(f"Subtitle {subtitle.ordinal} already complete. Skipping.")
        return playlist

    vtt_file = output_dir / "sub.vtt"
    info(f"Converting subtitle {subtitle.ordinal} ({subtitle.codec}) -> WebVTT")

    extract_command = [
        ffmpeg, "-hide_banner", "-y", "-i", str(input_file),
        "-map", f"0:{subtitle.index}",
        "-c:s", "webvtt",
        "-copyts", "-start_at_zero",
        str(vtt_file),
    ]
    run_command(extract_command)

    if _DRY_RUN:
        ok(f"Subtitle {subtitle.ordinal} would be written. (dry-run)")
        return playlist

    if not vtt_file.exists() or vtt_file.stat().st_size == 0:
        warn(f"Subtitle {subtitle.ordinal} was not created or is empty.")
        return None

    if time_scale is not None:
        apply_time_scale_to_vtt(vtt_file, *time_scale)
        info(f"Applied time scale {time_scale[0]}/{time_scale[1]} to subtitle.")

    base_ticks = int(round(video_pts_seconds * 90000))
    offset_ticks = int(round(offset_ms * 90))
    inject_timestamp_map(vtt_file, base_ticks + offset_ticks)
    write_subtitle_playlist(output_dir, vtt_file.name, media_duration)

    ok(f"Subtitle {subtitle.ordinal} complete.")
    return playlist


# ============================================================
# OUTPUT DISCOVERY
# ============================================================

def discover_video_playlists(stream_root: Path) -> list[tuple[str, Path]]:
    root = stream_root / VIDEO_ROOT
    if not root.exists():
        return []
    result: list[tuple[str, Path]] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        playlist = directory / "playlist.m3u8"
        if playlist.exists():
            result.append((directory.name, playlist))

    def sort_key(item):
        label = item[0]
        m = re.search(r"(\d+)", label)
        if m:
            return (0, int(m.group(1)), label)
        return (1, label)

    return sorted(result, key=sort_key)


def discover_audio_playlists(stream_root: Path) -> list[tuple[int, AudioProfile, Path]]:
    root = stream_root / AUDIO_ROOT
    if not root.exists():
        return []
    result: list[tuple[int, AudioProfile, Path]] = []
    for track_dir in root.iterdir():
        if not track_dir.is_dir():
            continue
        track = safe_int(track_dir.name, -1)
        if track <= 0:
            continue
        for profile_dir in track_dir.iterdir():
            if not profile_dir.is_dir():
                continue
            m = re.fullmatch(r"(\d+)k?-(\d+)ch", profile_dir.name)
            if not m:
                continue
            playlist = profile_dir / "playlist.m3u8"
            if not playlist.exists():
                continue
            result.append((
                track,
                AudioProfile(bitrate=int(m.group(1)), channels=int(m.group(2))),
                playlist,
            ))
    return sorted(result, key=lambda x: (x[0], x[1].bitrate, x[1].channels))


def discover_subtitles(stream_root: Path) -> list[int]:
    root = stream_root / SUBTITLE_ROOT
    if not root.exists():
        return []
    result: list[int] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        ordinal = safe_int(directory.name, -1)
        if ordinal <= 0:
            continue
        if (directory / "playlist.m3u8").exists():
            result.append(ordinal)
    return sorted(result)


# ============================================================
# METADATA HELPERS
# ============================================================

def load_saved_metadata(
    stream_root: Path, input_file: Optional[Path] = None,
) -> Optional[dict]:
    file = stream_root / STREAM_METADATA_FILE
    if not file.exists():
        return None
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:
        warn(f"Could not read {file.name}: {exc}")
        return None

    if input_file is not None:
        saved = data.get("source", {}).get("fingerprint", "")
        current = compute_source_fingerprint(input_file)
        if saved and current and saved != current:
            warn(
                "Existing output was generated from a different source "
                "file. Use --clean to regenerate from scratch."
            )
            return None
    return data


def metadata_audio_by_ordinal(metadata: Optional[dict]) -> dict[int, dict]:
    result: dict[int, dict] = {}
    if not metadata:
        return result
    for audio in metadata.get("source", {}).get("audios", []):
        ordinal = safe_int(audio.get("ordinal"), -1)
        if ordinal > 0:
            result[ordinal] = audio
    return result


def metadata_subtitle_by_ordinal(metadata: Optional[dict]) -> dict[int, dict]:
    result: dict[int, dict] = {}
    if not metadata:
        return result
    for subtitle in metadata.get("source", {}).get("subtitles", []):
        ordinal = safe_int(subtitle.get("ordinal"), -1)
        if ordinal > 0:
            result[ordinal] = subtitle
    return result


def metadata_video(metadata: Optional[dict]) -> Optional[dict]:
    if not metadata:
        return None
    videos = metadata.get("source", {}).get("videos", [])
    return videos[0] if videos else None


# ============================================================
# MASTER PLAYLIST
# ============================================================

def audio_display_name(metadata, track, profile) -> str:
    audio_data = metadata_audio_by_ordinal(metadata).get(track, {})
    language = normalize_language(str(audio_data.get("language", "") or ""))
    title = str(audio_data.get("title", "") or "").strip()
    parts: list[str] = []
    if language != "und":
        parts.append(language.upper())
    if title:
        parts.append(title)
    parts.append(f"{profile.bitrate} kbps")
    parts.append(f"{profile.channels}ch")
    return " - ".join(parts)


def subtitle_display_name(metadata, ordinal) -> tuple[str, str]:
    data = metadata_subtitle_by_ordinal(metadata).get(ordinal, {})
    language = normalize_language(str(data.get("language", "") or ""))
    title = str(data.get("title", "") or "").strip()
    if title:
        name = title
    elif language != "und":
        name = language.upper()
    else:
        name = f"Subtitle {ordinal}"
    return language, name


def probe_codec_name(ffprobe: str, ts_file: Path, kind: str) -> str:
    selector = "v:0" if kind == "video" else "a:0"
    try:
        data = ffprobe_json(
            ffprobe, ts_file,
            ["-select_streams", selector, "-show_entries", "stream=codec_name"],
        )
        streams = data.get("streams", [])
        if streams:
            return str(streams[0].get("codec_name", ""))
    except Exception:
        pass
    return ""


def rfc6381(codec_name: str, kind: str) -> str:
    if not codec_name:
        return ""
    name = codec_name.lower()
    if kind == "video":
        return RFC6381_VIDEO_CODECS.get(name, name)
    return RFC6381_AUDIO_CODECS.get(name, name)


def collect_audio_codecs(
    audio_playlists: list[tuple[int, AudioProfile, Path]],
    ffprobe: str,
    metadata: Optional[dict],
) -> set[str]:
    """Return the set of *output* audio codec names.

    The metadata records the *source* codecs, which is wrong once the
    track has been re-encoded. We therefore probe an actual TS segment
    for each audio rendition, and only fall back to metadata when a
    segment can't be read.
    """
    meta_map = metadata_audio_by_ordinal(metadata)
    codecs: set[str] = set()
    probed_keys: set[tuple[int, int, int]] = set()

    for track, profile, playlist in audio_playlists:
        key = (track, profile.bitrate, profile.channels)
        if key in probed_keys:
            continue
        probed_keys.add(key)

        first_ts = next(iter(sorted(playlist.parent.glob("*.ts"))), None)
        if first_ts is None:
            entry = meta_map.get(track)
            if entry and entry.get("codec"):
                codecs.add(str(entry["codec"]))
            continue

        name = probe_codec_name(ffprobe, first_ts, "audio")
        if name:
            codecs.add(name)
        else:
            entry = meta_map.get(track)
            if entry and entry.get("codec"):
                codecs.add(str(entry["codec"]))
    return codecs


def write_master_playlist(
    stream_root: Path,
    *,
    metadata: Optional[dict],
    ffprobe: str,
    default_audio_track: Optional[int] = None,
    default_subtitle_track: Optional[int] = None,
) -> Path:
    master = stream_root / "master.m3u8"

    video_playlists = discover_video_playlists(stream_root)
    audio_playlists = discover_audio_playlists(stream_root)
    subtitle_ordinals = discover_subtitles(stream_root)

    if not video_playlists and not audio_playlists:
        raise ConverterError(
            "No completed video or audio playlists found. "
            "Cannot generate master.m3u8."
        )

    lines = ["#EXTM3U", f"#EXT-X-VERSION:{HLS_VERSION}"]

    audio_by_track: dict[int, list[tuple[AudioProfile, Path]]] = {}
    for track, profile, playlist in audio_playlists:
        audio_by_track.setdefault(track, []).append((profile, playlist))

    if default_audio_track is not None and default_audio_track not in audio_by_track:
        warn(
            f"--default-audio-track {default_audio_track} was requested "
            f"but no such audio track exists. Falling back to automatic "
            f"selection."
        )

    if (default_subtitle_track is not None
            and default_subtitle_track not in subtitle_ordinals):
        warn(
            f"--default-subtitle-track {default_subtitle_track} was requested "
            f"but no such subtitle track exists. No subtitle will be DEFAULT=YES."
        )

    for ordinal in subtitle_ordinals:
        language, name = subtitle_display_name(metadata, ordinal)
        uri = f"{SUBTITLE_ROOT}/{ordinal}/playlist.m3u8"
        is_default = (default_subtitle_track is not None
                      and ordinal == default_subtitle_track)
        lines.append(
            "#EXT-X-MEDIA:"
            "TYPE=SUBTITLES,"
            'GROUP-ID="subtitles",'
            f'LANGUAGE="{escape_m3u8(language)}",'
            f'NAME="{escape_m3u8(name)}",'
            f"DEFAULT={'YES' if is_default else 'NO'},"
            "AUTOSELECT=YES,"
            "FORCED=NO,"
            f'URI="{escape_m3u8(uri)}"'
        )

    def choose_audio_for_quality(quality: str):
        candidates: list[tuple[int, AudioProfile, Path]] = []
        for track, profiles in audio_by_track.items():
            for profile, playlist in profiles:
                candidates.append((track, profile, playlist))
        if not candidates:
            return None

        if default_audio_track is not None:
            matching = [c for c in candidates if c[0] == default_audio_track]
            if matching:
                # Deterministic: pick the highest bitrate rendition.
                return max(
                    matching,
                    key=lambda x: (x[1].bitrate, x[1].channels),
                )

        m = re.search(r"(\d+)", quality)
        height = int(m.group(1)) if m else 0
        if height <= 480:
            limit = 128
        elif height <= 720:
            limit = 160
        else:
            limit = None
        if limit is not None:
            preferred = [
                it for it in candidates
                if it[1].bitrate <= limit and it[1].channels <= 2
            ]
            if preferred:
                return max(preferred, key=lambda x: (x[1].bitrate, x[1].channels))
        return max(candidates, key=lambda x: (x[1].bitrate, x[1].channels))

    audio_group_for_quality: dict[str, Optional[str]] = {}

    for quality, _ in video_playlists:
        chosen = choose_audio_for_quality(quality)
        group_id = f"audio-{quality}" if chosen else None
        audio_group_for_quality[quality] = group_id

        if group_id is None:
            continue

        for track, profile, playlist in audio_playlists:
            audio_map = metadata_audio_by_ordinal(metadata)
            audio_data = audio_map.get(track, {})
            language = normalize_language(str(audio_data.get("language", "") or ""))
            name = audio_display_name(metadata, track, profile)
            is_default = (
                chosen is not None and chosen[0] == track and chosen[1] == profile
            )
            uri = playlist.relative_to(stream_root).as_posix()
            lines.append(
                "#EXT-X-MEDIA:"
                "TYPE=AUDIO,"
                f'GROUP-ID="{escape_m3u8(group_id)}",'
                f'LANGUAGE="{escape_m3u8(language)}",'
                f'NAME="{escape_m3u8(name)}",'
                f"DEFAULT={'YES' if is_default else 'NO'},"
                "AUTOSELECT=YES,"
                f'URI="{escape_m3u8(uri)}"'
            )

    video_data = metadata_video(metadata)
    src_w = safe_int(video_data.get("width")) if video_data else 0
    src_h = safe_int(video_data.get("height")) if video_data else 0

    video_codec_by_quality: dict[str, str] = {}
    for quality, playlist in video_playlists:
        first_ts = next(iter(sorted(playlist.parent.glob("*.ts"))), None)
        codec = ""
        if first_ts is not None:
            codec = probe_codec_name(ffprobe, first_ts, "video")
        video_codec_by_quality[quality] = codec

    audio_codec_set = collect_audio_codecs(audio_playlists, ffprobe, metadata)

    if video_playlists:
        for quality, playlist in video_playlists:
            m = re.search(r"(\d+)", quality)
            target_h = int(m.group(1)) if m else 0

            if src_w > 0 and src_h > 0 and target_h > 0:
                out_w, out_h = calculate_output_dimensions(src_w, src_h, target_h)
            else:
                out_w, out_h = 0, 0

            bitrate = 0
            if target_h in DEFAULT_VIDEO_PROFILES:
                bitrate = DEFAULT_VIDEO_PROFILES[target_h]
            # Fall back to measured source bitrate for copy mode with
            # an unrecognised height (e.g. --video-label "source").
            if bitrate <= 0 and video_data:
                bitrate = safe_int(video_data.get("actual_bitrate"), 0)
            if bitrate <= 0:
                bitrate = 1000  # never emit BANDWIDTH=1

            group_id = audio_group_for_quality.get(quality)
            audio_bitrate = 0
            if group_id:
                chosen = choose_audio_for_quality(quality)
                if chosen:
                    audio_bitrate = chosen[1].bitrate

            bandwidth = max(1, (bitrate + audio_bitrate) * 1000)

            attrs = [f"BANDWIDTH={bandwidth}"]
            if out_w > 0 and out_h > 0:
                attrs.append(f"RESOLUTION={out_w}x{out_h}")

            vc = rfc6381(video_codec_by_quality.get(quality, ""), "video")
            codecs: list[str] = []
            if vc:
                codecs.append(vc)
            if group_id:
                for name in sorted(audio_codec_set):
                    mapped = rfc6381(name, "audio")
                    if mapped and mapped not in codecs:
                        codecs.append(mapped)
            if codecs:
                attrs.append(f'CODECS="{",".join(codecs)}"')

            if group_id:
                attrs.append(f'AUDIO="{group_id}"')
            if subtitle_ordinals:
                attrs.append('SUBTITLES="subtitles"')

            lines.append("#EXT-X-STREAM-INF:" + ",".join(attrs))
            lines.append(playlist.relative_to(stream_root).as_posix())

    if _DRY_RUN:
        print(f"[DRY-RUN] Would write master playlist: {master}")
        return master

    master.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok(f"Master playlist regenerated: {master}")
    return master


# ============================================================
# PROCESSING DECISIONS
# ============================================================

def requested_audio_tracks(media: MediaInfo, config: AudioConfig) -> set[int]:
    if config.encode_all:
        return {a.ordinal for a in media.audios}
    return {r.track for r in config.requests}


def validate_audio_track_numbers(media: MediaInfo, config: AudioConfig) -> None:
    available = {a.ordinal for a in media.audios}
    requested = requested_audio_tracks(media, config)
    missing = sorted(requested - available)
    if missing:
        raise ConverterError(
            "Requested audio track(s) do not exist: "
            + ", ".join(str(x) for x in missing)
        )


def process_audio(
    config: AppConfig, input_file: Path, stream_root: Path, media: MediaInfo,
) -> None:
    if config.audio.skip:
        info("Audio processing skipped (--audio none).")
        return
    if not media.audios:
        return

    validate_audio_track_numbers(media, config.audio)
    selected = requested_audio_tracks(media, config.audio)

    info("--- Audio processing ---")
    for audio in media.audios:
        if audio.ordinal in selected:
            profiles = audio_profiles_for_track(audio, config.audio)
            if not profiles:
                warn(
                    f"Audio {audio.ordinal}: no valid encoded profiles "
                    f"could be produced."
                )
                continue
            for profile in profiles:
                convert_audio_encode(
                    config, input_file, stream_root, audio, profile,
                    duration_hint=media.duration,
                )
        else:
            convert_audio_copy(
                config.ffmpeg, input_file, stream_root, audio,
                config.segment_time,
                duration_hint=media.duration,
            )


def process_video(
    config: AppConfig, input_file: Path, stream_root: Path, media: MediaInfo,
) -> None:
    if config.video.mode == "none":
        info("Video processing skipped (--video none).")
        return

    info("--- Video processing ---")
    if not media.videos:
        warn("No video stream in input. Nothing to do.")
        return

    source_video = media.videos[0]

    if config.video.mode == "copy":
        quality = determine_copy_quality(source_video, config.video.label)
        convert_video_copy(
            config.ffmpeg, input_file, stream_root,
            source_video, quality, config.segment_time,
            duration_hint=media.duration,
        )
        return

    for profile in config.video.profiles:
        convert_video_encode(
            config, input_file, stream_root, source_video, profile,
            duration_hint=media.duration,
        )


def process_subtitles(
    config: AppConfig, input_file: Path, stream_root: Path, media: MediaInfo,
) -> None:
    if config.subtitles.mode == "none":
        info("Subtitle processing skipped (--subtitles none).")
        return
    if not media.subtitles:
        return

    info("--- Subtitle processing ---")

    video_pts_seconds = 0.0
    if config.video.mode != "none":
        video_playlists = discover_video_playlists(stream_root)
        if video_playlists:
            first_video_playlist = video_playlists[0][1]
            first_ts = next(iter(sorted(first_video_playlist.parent.glob("*.ts"))), None)
            if first_ts is not None:
                video_pts_seconds = probe_first_video_pts(config.ffprobe, first_ts)
                info(
                    f"Detected first video PTS: {video_pts_seconds:.3f} s "
                    f"({int(round(video_pts_seconds * 90000))} ticks)"
                )

    for subtitle in media.subtitles:
        offset_ms = config.subtitles.offset_ms.get(
            subtitle.ordinal,
            config.subtitles.offset_ms.get(0, 0),
        )
        convert_subtitle(
            config.ffmpeg, config.ffprobe,
            input_file, stream_root, subtitle,
            media.duration, video_pts_seconds,
            offset_ms, config.subtitles.time_scale,
        )


# ============================================================
# ADD-TO-STREAM (external track merging)
# ============================================================

def detect_external_kind(ffprobe: str, path: Path) -> str:
    ext = path.suffix.lower()

    try:
        data = ffprobe_json(
            ffprobe, path,
            ["-show_entries", "stream=codec_type"],
        )
        kinds: set[str] = set()
        for s in data.get("streams", []):
            kinds.add(str(s.get("codec_type", "")))
        if "subtitle" in kinds:
            return "subtitle"
        if "audio" in kinds and "video" not in kinds:
            return "audio"
        if "audio" in kinds and "video" in kinds:
            return "video"
        if "video" in kinds:
            return "video"
    except Exception:
        pass

    if ext in SUBTITLE_EXTS:
        return "subtitle"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    return "unknown"


def next_available_ordinal(stream_root: Path, root_name: str) -> int:
    root = stream_root / root_name
    if not root.exists():
        return 1
    existing = [safe_int(d.name, -1) for d in root.iterdir() if d.is_dir()]
    existing = [x for x in existing if x > 0]
    return (max(existing) + 1) if existing else 1


def probe_external_audio(ffprobe: str, path: Path) -> AudioStream:
    data = ffprobe_json(
        ffprobe, path,
        [
            "-show_streams",
            "-show_entries",
            (
                "stream=index,codec_type,codec_name,channels,sample_rate,"
                "duration:stream_tags=language,title"
            ),
        ],
    )
    for stream in data.get("streams", []):
        if str(stream.get("codec_type", "")) != "audio":
            continue
        tags = stream.get("tags") or {}
        return AudioStream(
            index=safe_int(stream.get("index"), 0),
            ordinal=1,
            codec=str(stream.get("codec_name", "")),
            channels=max(1, safe_int(stream.get("channels"), 2)),
            sample_rate=safe_int(stream.get("sample_rate"), 48000),
            language=normalize_language(str(tags.get("language", "") or "")),
            title=str(tags.get("title", "") or "").strip(),
            duration=safe_float(stream.get("duration"), 0.0),
        )
    raise ConverterError(f"No audio stream found in {path}")


def probe_external_subtitle(ffprobe: str, path: Path) -> SubtitleStream:
    data = ffprobe_json(
        ffprobe, path,
        [
            "-show_streams",
            "-show_entries",
            "stream=index,codec_type,codec_name:stream_tags=language,title",
        ],
    )
    for stream in data.get("streams", []):
        ct = str(stream.get("codec_type", ""))
        if ct and ct != "subtitle":
            continue
        tags = stream.get("tags") or {}
        return SubtitleStream(
            index=safe_int(stream.get("index"), 0),
            ordinal=1,
            codec=str(stream.get("codec_name", path.suffix.lstrip("."))),
            language=normalize_language(str(tags.get("language", "") or "")),
            title=str(tags.get("title", "") or "").strip(),
        )
    raise ConverterError(f"No subtitle stream found in {path}")


def check_external_conflict(
    source: dict, kind: str, ordinal: int, input_path: Path,
) -> None:
    key = "audios" if kind == "audio" else "subtitles"
    current_fp = compute_source_fingerprint(input_path)
    if not current_fp:
        return

    for entry in source.get(key, []):
        if safe_int(entry.get("ordinal"), -1) != ordinal:
            continue
        if not entry.get("external"):
            continue
        existing_fp = entry.get("source_fingerprint", "")
        if existing_fp and existing_fp != current_fp:
            raise ConverterError(
                f"Track {ordinal} already exists and was created from a "
                f"different source file:\n"
                f"  existing: {entry.get('source_path')}\n"
                f"  new:      {input_path}\n"
                f"Use --track N (a different number) or --clean."
            )


def _resolve_audio_plan(
    options: AddToStreamOptions,
    audio: AudioStream,
    measured_bitrate: int,
) -> tuple[bool, str, int, int]:
    source_channels = max(1, audio.channels)
    copy_compatible = audio.codec.lower() in HLS_COPY_AUDIO_CODECS

    mode = options.audio_add_mode or "auto"
    if mode == "copy":
        if not copy_compatible:
            raise ConverterError(
                f"Cannot copy '{audio.codec}' into MPEG-TS HLS. "
                f"Use --audio-add-mode encode."
            )
        do_copy = True
    elif mode == "encode":
        do_copy = False
    else:
        do_copy = copy_compatible

    if do_copy:
        bitrate = measured_bitrate if measured_bitrate > 0 else 128
        channels = source_channels
        return (True, audio.codec, bitrate, channels)

    target_codec = options.audio_codec or DEFAULT_AUDIO_CODEC
    _validate_audio_codec_for_encoding(target_codec, "--audio-codec")

    level = options.audio_level or DEFAULT_AUDIO_LEVEL
    ref_bitrate = measured_bitrate if measured_bitrate > 0 else 128
    if measured_bitrate <= 0:
        warn("Could not determine source bitrate; using 128 kbps reference.")

    target_bitrate = compute_effective_audio_bitrate(
        aac_reference_bitrate=ref_bitrate,
        target_codec=target_codec,
        level=level,
        source_bitrate=measured_bitrate,
        source_codec=audio.codec,
    )
    channels = automatic_audio_channels(source_channels, target_bitrate)
    if channels < source_channels:
        warn(
            f"Downmixing {source_channels}ch -> {channels}ch "
            f"(automatic policy at {target_bitrate} kbps)."
        )
    return (False, target_codec, max(32, target_bitrate), channels)


def _add_audio_to_stream(
    ffmpeg: str, ffprobe: str,
    stream_root: Path, source: dict,
    input_path: Path, media_duration: float,
    segment_time: int,
    options: AddToStreamOptions,
) -> None:
    audio = probe_external_audio(ffprobe, input_path)

    measured = measure_audio_bitrate(
        ffprobe, input_path, audio, audio.duration or media_duration,
    )
    if measured <= 0:
        try:
            data = ffprobe_json(
                ffprobe, input_path,
                ["-show_entries", "stream=bit_rate"],
            )
            streams = data.get("streams", [])
            if streams:
                measured = max(1, safe_int(streams[0].get("bit_rate"), 0) // 1000)
        except Exception:
            measured = 0

    do_copy, target_codec, bitrate, channels = _resolve_audio_plan(
        options, audio, measured,
    )

    if options.track is not None:
        track_num = int(options.track)
        if track_num <= 0:
            raise ConverterError("--track must be > 0.")
    else:
        track_num = next_available_ordinal(stream_root, AUDIO_ROOT)

    check_external_conflict(source, "audio", track_num, input_path)

    profile = AudioProfile(bitrate=bitrate, channels=channels)
    output_dir = stream_root / AUDIO_ROOT / str(track_num) / profile.folder_name
    playlist = output_dir / "playlist.m3u8"

    language = normalize_language(options.language or audio.language)
    title = (options.title or audio.title or "").strip()

    if prepare_target_directory(output_dir):
        ok(f"Audio track {track_num} {profile.folder_name} already exists. Skipping encode.")
    else:
        info(
            f"Adding audio track {track_num} "
            f"({audio.codec} -> {'copy' if do_copy else target_codec}, "
            f"{channels}ch, {bitrate} kbps)"
        )
        if do_copy:
            codec_args = ["-c:a", "copy"]
        else:
            codec_args = codec_specific_audio_args(
                target_codec, bitrate, channels, options.audio_profile,
            )

        command = [
            ffmpeg, "-hide_banner", "-y", "-i", str(input_path),
            "-vn", "-sn", "-dn",
            "-map", "0:a:0",
        ] + codec_args + [
            "-copyts", "-start_at_zero",
            "-muxdelay", "0", "-muxpreload", "0",
            "-f", "hls",
            "-hls_time", str(segment_time),
            "-hls_playlist_type", "vod",
            "-hls_flags", "independent_segments",
            "-hls_segment_filename", str(output_dir / "%05d.ts"),
            str(playlist),
        ]
        duration_hint = audio.duration or media_duration
        progress_tuple = (
            ("audio", f"Track {track_num}", duration_hint)
            if duration_hint > 0 else None
        )
        run_command(command, progress=progress_tuple)
        if not playlist.exists() and not _DRY_RUN:
            raise ConverterError(f"Audio playlist was not created: {playlist}")
        ok(f"Audio track {track_num} complete.")

    existing = [
        a for a in source["audios"]
        if safe_int(a.get("ordinal"), -1) == track_num
    ]
    entry = {
        "index": audio.index,
        "ordinal": track_num,
        "codec": audio.codec if do_copy else target_codec,
        "channels": channels,
        "sample_rate": audio.sample_rate,
        "language": language,
        "title": title,
        "actual_bitrate": bitrate,
        "external": True,
        "source_path": str(input_path),
        "source_fingerprint": compute_source_fingerprint(input_path),
    }
    if existing:
        existing[0].update(entry)
    else:
        source["audios"].append(entry)


def _add_subtitle_to_stream(
    ffmpeg: str, ffprobe: str,
    stream_root: Path, source: dict,
    input_path: Path, media_duration: float,
    video_pts_seconds: float,
    options: AddToStreamOptions,
) -> None:
    subtitle = probe_external_subtitle(ffprobe, input_path)
    if subtitle.codec.lower() not in TEXT_SUBTITLE_CODECS:
        raise ConverterError(
            f"Unsupported subtitle codec '{subtitle.codec}'. "
            f"Only text subtitles (srt/ass/ssa/vtt/...) can be added."
        )

    if options.track is not None:
        ordinal = int(options.track)
        if ordinal <= 0:
            raise ConverterError("--track must be > 0.")
    else:
        ordinal = next_available_ordinal(stream_root, SUBTITLE_ROOT)

    check_external_conflict(source, "subtitle", ordinal, input_path)

    language = normalize_language(options.language or subtitle.language)
    title = (options.title or subtitle.title or "").strip()

    offset_map = parse_subtitle_offset(options.subtitle_offset_ms)
    offset_ms = offset_map.get(ordinal, offset_map.get(0, 0))
    time_scale = parse_subtitle_time_scale(options.subtitle_time_scale)

    info(f"Adding subtitle track {ordinal} ({subtitle.codec}, lang={language})")

    # Use the target ordinal (not the input-file stream's ordinal, which
    # probe_external_subtitle() always sets to 1) so the output is
    # written to subtitles/<ordinal>/.
    target_subtitle = _dc_replace(subtitle, ordinal=ordinal)

    convert_subtitle(
        ffmpeg, ffprobe, input_path, stream_root,
        target_subtitle, media_duration, video_pts_seconds,
        offset_ms, time_scale,
    )

    existing = [
        s for s in source["subtitles"]
        if safe_int(s.get("ordinal"), -1) == ordinal
    ]
    entry = {
        "index": subtitle.index,
        "ordinal": ordinal,
        "codec": subtitle.codec,
        "language": language,
        "title": title,
        "external": True,
        "source_path": str(input_path),
        "source_fingerprint": compute_source_fingerprint(input_path),
    }
    if time_scale is not None:
        entry["time_scale"] = f"{time_scale[0]}/{time_scale[1]}"
    if existing:
        existing[0].update(entry)
    else:
        source["subtitles"].append(entry)


def run_add_to_stream(
    ffmpeg: str, ffprobe: str,
    stream_dir: Path, input_path: Path,
    options: AddToStreamOptions,
    segment_time: Optional[int] = None,
) -> ConversionResult:
    ensure_executable(ffmpeg, "FFmpeg")
    ensure_executable(ffprobe, "FFprobe")

    stream_root = Path(stream_dir).expanduser().resolve()
    if not stream_root.is_dir():
        raise ConverterError(f"Stream folder does not exist:\n{stream_root}")

    video_playlists = discover_video_playlists(stream_root)
    audio_playlists = discover_audio_playlists(stream_root)
    if not video_playlists and not audio_playlists:
        raise ConverterError(
            f"No video or audio playlist found in {stream_root}. "
            f"Is this really an HLS stream folder?"
        )

    input_path = Path(input_path).expanduser().resolve()
    if not input_path.is_file():
        raise ConverterError(f"Input file does not exist:\n{input_path}")

    kind = detect_external_kind(ffprobe, input_path)
    if kind == "video":
        raise ConverterError(
            "Cannot add a video file to an existing stream.\n"
            "Create a new stream folder instead."
        )
    if kind == "unknown":
        raise ConverterError(
            f"Could not determine the type of {input_path.name}.\n"
            f"Expected audio (.m4a/.aac/.mp3/.ac3/.eac3/...) "
            f"or subtitle (.srt/.ass/.ssa/.vtt)."
        )

    metadata = load_metadata_raw(stream_root)
    source = metadata.setdefault("source", {})
    source.setdefault("videos", [])
    source.setdefault("audios", [])
    source.setdefault("subtitles", [])

    media_duration = safe_float(source.get("duration"), 0.0)
    if media_duration <= 0 and video_playlists:
        media_duration = probe_playlist_duration(video_playlists[0][1])
        if media_duration > 0:
            info(f"Duration from playlist: {media_duration:.2f} s")
    if media_duration <= 0:
        # Fall back to the added input file's own duration.
        media_duration = audio_or_subtitle_duration(ffprobe, input_path)
        if media_duration > 0:
            info(f"Duration from input file: {media_duration:.2f} s")
    if media_duration <= 0:
        warn("Could not determine stream duration.")

    info("=" * 68)
    info("Add to existing stream")
    info("=" * 68)
    info(f"Stream: {stream_root}")
    info(f"Input : {input_path}")
    info(f"Kind  : {kind}")

    if segment_time is None or segment_time <= 0:
        segment_time = DEFAULT_SEGMENT_TIME

    if kind == "audio":
        _add_audio_to_stream(
            ffmpeg, ffprobe, stream_root, source,
            input_path, media_duration, segment_time, options,
        )
    elif kind == "subtitle":
        video_pts_seconds = 0.0
        if video_playlists:
            first_ts = next(
                iter(sorted(video_playlists[0][1].parent.glob("*.ts"))), None,
            )
            if first_ts is not None:
                video_pts_seconds = probe_first_video_pts(ffprobe, first_ts)
                info(
                    f"Detected first video PTS: {video_pts_seconds:.3f} s "
                    f"({int(round(video_pts_seconds * 90000))} ticks)"
                )
        _add_subtitle_to_stream(
            ffmpeg, ffprobe, stream_root, source,
            input_path, media_duration, video_pts_seconds, options,
        )
    else:
        raise ConverterError(f"Unsupported kind: {kind}")

    save_metadata_raw(stream_root, metadata)

    master = None
    if not options.skip_master:
        info("--- Master playlist ---")
        master = write_master_playlist(
            stream_root, metadata=metadata, ffprobe=ffprobe,
            default_audio_track=options.default_audio_track,
            default_subtitle_track=options.default_subtitle_track,
        )

    info("=" * 68)
    info("ADD COMPLETE")
    info("=" * 68)

    return ConversionResult(
        success=True,
        output_dir=stream_root,
        master_playlist=master,
    )


def audio_or_subtitle_duration(ffprobe: str, path: Path) -> float:
    """Best-effort duration probe for an audio or subtitle input."""
    try:
        data = ffprobe_json(
            ffprobe, path,
            ["-show_entries", "format=duration:stream=duration"],
        )
        fmt = data.get("format", {})
        duration = safe_float(fmt.get("duration"), 0.0)
        if duration > 0:
            return duration
        best = 0.0
        for s in data.get("streams", []):
            d = safe_float(s.get("duration"), 0.0)
            if d > best:
                best = d
        return best
    except Exception:
        return 0.0


# ============================================================
# SUMMARY
# ============================================================

def print_summary(input_file: Path, stream_root: Path, media: MediaInfo) -> None:
    video_playlists = discover_video_playlists(stream_root)
    audio_playlists = discover_audio_playlists(stream_root)
    subtitle_files = discover_subtitles(stream_root)

    info("=" * 68)
    info("CONVERSION SUMMARY")
    info("=" * 68)
    info(f"Input : {input_file}")
    info(f"Output: {stream_root}")

    info("Video playlists:")
    if video_playlists:
        for quality, _ in video_playlists:
            info(f"  - {quality}")
    else:
        info("  None")

    info("Audio playlists:")
    if audio_playlists:
        for track, profile, _ in audio_playlists:
            info(f"  - Track {track}: {profile.folder_name}")
    else:
        info("  None")

    info("Subtitles:")
    if subtitle_files:
        for ordinal in subtitle_files:
            info(f"  - Track {ordinal}: {SUBTITLE_ROOT}/{ordinal}/playlist.m3u8")
    else:
        info("  None")

    info("Source streams:")
    info(f"  Video : {len(media.videos)}")
    info(f"  Audio : {len(media.audios)}")
    info(f"  Subs  : {len(media.subtitles)}")
    info("=" * 68)
    info("DONE")
    info("=" * 68)


# ============================================================
# HIGH-LEVEL API: HLSConverter
# ============================================================

class HLSConverter:
    """Programmatic interface to the converter.

    Typical usage:

        from pathlib import Path
        from convert_hls import (
            HLSConverter, CancellationToken, ProgressEvent,
        )

        # Build an AppConfig — you can use build_config(args) from CLI
        # parsing, or construct one manually.
        config = AppConfig(...)

        converter = HLSConverter(config)
        token = CancellationToken()

        def on_log(level, msg):
            print(f"[{level}] {msg}")

        def on_progress(ev: ProgressEvent):
            print(f"{ev.stage} {ev.label} {ev.percent:.0f}%")

        result = converter.convert(
            input_file=Path("movie.mkv"),
            output_dir=Path("movie-stream"),
            on_log=on_log,
            on_progress=on_progress,
            cancel_token=token,
        )

        if result.success:
            print("Done:", result.master_playlist)
        else:
            print("Failed:", result.error)
    """

    def __init__(self, config: AppConfig):
        self.config = config

    # ---------- public: convert ----------

    def convert(
        self,
        input_file: Path,
        output_dir: Optional[Path] = None,
        *,
        on_log: Optional[Callable[[str, str], None]] = None,
        on_progress: Optional[Callable[[ProgressEvent], None]] = None,
        cancel_token: Optional[CancellationToken] = None,
    ) -> ConversionResult:
        """Convert a source file into an HLS stream.

        output_dir: defaults to "<input_parent>/<input_stem>-stream".
        """
        input_file = Path(input_file).expanduser()
        if not input_file.is_file():
            return ConversionResult(
                success=False,
                error=f"Input file does not exist: {input_file}",
            )

        if output_dir is None:
            output_dir = input_file.parent / (input_file.stem + "-stream")
        output_dir = Path(output_dir).expanduser()

        _set_context(
            log_callback=on_log,
            progress_callback=on_progress,
            cancel_token=cancel_token,
        )
        try:
            return self._do_convert(input_file, output_dir)
        except ConverterError as exc:
            return ConversionResult(success=False, error=str(exc))
        except KeyboardInterrupt:
            return ConversionResult(success=False, error="Cancelled by user.")
        except Exception as exc:
            return ConversionResult(success=False, error=f"Unexpected error: {exc}")
        finally:
            _clear_context()

    # ---------- public: add_to_stream ----------

    def add_to_stream(
        self,
        input_file: Path,
        stream_dir: Path,
        *,
        options: Optional[AddToStreamOptions] = None,
        on_log: Optional[Callable[[str, str], None]] = None,
        on_progress: Optional[Callable[[ProgressEvent], None]] = None,
        cancel_token: Optional[CancellationToken] = None,
    ) -> ConversionResult:
        """Add an audio or subtitle track to an existing HLS stream folder
        and regenerate master.m3u8."""
        if options is None:
            options = AddToStreamOptions()

        _set_context(
            log_callback=on_log,
            progress_callback=on_progress,
            cancel_token=cancel_token,
        )
        try:
            return run_add_to_stream(
                self.config.ffmpeg,
                self.config.ffprobe,
                Path(stream_dir),
                Path(input_file),
                options,
                segment_time=self.config.segment_time,
            )
        except ConverterError as exc:
            return ConversionResult(success=False, error=str(exc))
        except KeyboardInterrupt:
            return ConversionResult(success=False, error="Cancelled by user.")
        except Exception as exc:
            return ConversionResult(success=False, error=f"Unexpected error: {exc}")
        finally:
            _clear_context()

    # ---------- internal ----------

    def _do_convert(self, input_file: Path, output_dir: Path) -> ConversionResult:
        config = self.config

        ensure_executable(config.ffmpeg, "FFmpeg")
        ensure_executable(config.ffprobe, "FFprobe")

        info("=" * 68)
        info(f"{APP_NAME} v{__version__} ({APP_STATUS}) — {GITHUB_URL}")
        info("=" * 68)
        info(f"Input : {input_file}")
        info(f"Output: {output_dir}")
        if _DRY_RUN:
            info("Mode  : DRY RUN (no ffmpeg commands will execute)")

        if config.clean and output_dir.exists() and not _DRY_RUN:
            warn(f"--clean was specified. Removing: {output_dir}")
            shutil.rmtree(output_dir)

        if not _DRY_RUN:
            output_dir.mkdir(parents=True, exist_ok=True)

        media = read_media_information(config.ffprobe, input_file)
        inspect_bitrates(config.ffprobe, input_file, media)
        write_metadata(output_dir, media=media, input_file=input_file)

        process_video(config, input_file, output_dir, media)
        process_audio(config, input_file, output_dir, media)
        process_subtitles(config, input_file, output_dir, media)

        master: Optional[Path] = None
        if not config.skip_master:
            info("--- Master playlist ---")
            metadata = load_saved_metadata(output_dir, input_file)
            master = write_master_playlist(
                output_dir, metadata=metadata, ffprobe=config.ffprobe,
                default_audio_track=config.default_audio_track,
                default_subtitle_track=config.default_subtitle_track,
            )

        video_outputs = discover_video_playlists(output_dir)
        audio_tuples = discover_audio_playlists(output_dir)
        audio_outputs = [(t, p) for t, _, p in audio_tuples]
        subtitle_outputs = [
            (o, output_dir / SUBTITLE_ROOT / str(o) / "playlist.m3u8")
            for o in discover_subtitles(output_dir)
        ]

        print_summary(input_file, output_dir, media)

        return ConversionResult(
            success=True,
            output_dir=output_dir,
            master_playlist=master,
            video_outputs=video_outputs,
            audio_outputs=audio_outputs,
            subtitle_outputs=subtitle_outputs,
            duration_seconds=media.duration,
        )


# ============================================================
# ABOUT
# ============================================================

def print_about() -> None:
    """Print author, license and project links. Used by --about."""
    print(f"{APP_NAME} v{__version__} ({APP_STATUS})")
    print("A general-purpose HLS media converter built on FFmpeg.")
    print()
    print(f"Status  : {APP_STATUS}")
    print(f"Author  : {AUTHOR}")
    print(f"GitHub  : {GITHUB_URL}")
    print(f"PyPI    : {PYPI_URL}")
    print(f"License : {LICENSE_NAME}")
    print()
    print("Requires ffmpeg and ffprobe on PATH,")
    print("or pass their locations via --ffmpeg / --ffprobe.")


# ============================================================
# ARGPARSE
# ============================================================

_EPILOG = f"""\
Examples:
  Convert a file with default settings (video copy):
    %(prog)s "movie.mkv"

  Encode to multiple resolutions:
    %(prog)s "movie.mkv" --video-mode encode --video-profiles 720,1080

  Add an external subtitle track to an existing stream:
    %(prog)s "new-subs.srt" --add-to-stream "/path/to/stream" --language fa

  Encode specific audio tracks at per-track bitrates:
    %(prog)s "movie.mkv" --audio 1:encode,2:encode --audio-bitrate 1=128,2=224

  Preview without executing any ffmpeg command:
    %(prog)s "movie.mkv" --dry-run

Project : {GITHUB_URL}
Author  : {AUTHOR}
Version : {__version__} ({APP_STATUS})
License : {LICENSE_NAME}
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        # prog is intentionally left unset so argparse auto-detects it
        # from sys.argv[0]. This gives the correct name for every way
        # the tool can be invoked:
        #   - hls-converter ...           (pip console script)
        #   - python -m convert_hls ...   (module invocation)
        #   - python convert_hls.py ...   (direct file execution)
        description=(
            f"{APP_NAME} — general-purpose HLS media converter.\n"
            "Copy is the default; encoding must be requested explicitly.\n"
            "Use --add-to-stream to add audio/subtitle tracks to an "
            "existing stream folder."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument("input", nargs="?", help="Input media file.")
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {__version__} ({APP_STATUS})  ({GITHUB_URL})",
    )
    parser.add_argument(
        "--about", action="store_true",
        help="Show author, license and project links, then exit.",
    )

    general = parser.add_argument_group("General")
    general.add_argument("--output", metavar="PATH",
                         help="Output stream directory "
                              "(default: <input_stem>-stream next to input)")
    general.add_argument("--ffmpeg", default=DEFAULT_FFMPEG, metavar="PATH")
    general.add_argument("--ffprobe", default=DEFAULT_FFPROBE, metavar="PATH")
    general.add_argument("--clean", action="store_true",
                         help="Remove the entire output stream directory first")
    general.add_argument("--skip-master", "--no-master", dest="skip_master",
                         action="store_true",
                         help="Do not regenerate master.m3u8 after processing")
    general.add_argument("--dry-run", action="store_true",
                         help="Print ffmpeg commands without executing them")
    general.add_argument("--default-audio-track", type=int, metavar="N",
                         help="Force this audio track number as DEFAULT in the master")
    general.add_argument("--default-subtitle-track", type=int, metavar="N",
                         help="Force this subtitle track number as DEFAULT in the master")

    add = parser.add_argument_group("Add to existing stream")
    add.add_argument("--add-to-stream", metavar="PATH",
                     help="Add the input file (audio or subtitle) to this "
                          "existing HLS stream folder and regenerate the master.")
    add.add_argument("--track", type=int, metavar="N",
                     help="Track number to assign (default: next available)")
    add.add_argument("--language", metavar="LANG",
                     help="Language tag for the added track, e.g. fa, en")
    add.add_argument("--title", metavar="TEXT",
                     help="Title for the added track")

    video = parser.add_argument_group("Video")
    video.add_argument("--video-mode", "--video", dest="video_mode", metavar="MODE",
                       help="copy | encode | none (default: copy). "
                            "You may also pass a quality label like 1080 "
                            "as shorthand for --video-mode copy --video-label 1080.")
    video.add_argument("--video-label", metavar="LABEL",
                       help="Quality label for copy mode, e.g. 1080")
    video.add_argument("--video-profiles", metavar="LIST",
                       help="Video qualities to encode, e.g. 480,720,1080")
    video.add_argument("--video-level", metavar="LEVEL",
                       default=DEFAULT_VIDEO_LEVEL,
                       choices=list(VIDEO_LEVEL_MULTIPLIERS.keys()),
                       help="Auto-bitrate level: data-saver, small, balanced, high, source")
    video.add_argument("--video-rate-mode", metavar="MODE",
                       default="auto",
                       choices=["auto", "crf", "abr", "2pass"],
                       help="Rate control: auto (crf if CRF set, else abr), "
                            "crf, abr, or 2pass. 2pass requires encode mode "
                            "and bitrate; incompatible with CRF.")
    video.add_argument("--video-bitrate", metavar="LIST",
                       help="Per-quality bitrate overrides, e.g. 720=1300,1080=2800")
    video.add_argument("--video-crf", metavar="LIST",
                       help="Per-quality CRF overrides, e.g. 720=20,1080=18")
    video.add_argument("--video-codec", default=DEFAULT_VIDEO_CODEC, metavar="CODEC")
    video.add_argument("--video-preset", default=DEFAULT_VIDEO_PRESET, metavar="PRESET")

    audio = parser.add_argument_group("Audio")
    audio.add_argument("--audio", action="append", default=[], metavar="MODE",
                       help="encode | none | TRACK:encode (repeatable)")
    audio.add_argument("--audio-profiles", metavar="LIST",
                       help="Encoded audio profiles, e.g. 128:2,224:6")
    audio.add_argument("--audio-bitrate", metavar="LIST",
                       help="Per-track bitrate override, e.g. 2=128,4=224")
    audio.add_argument("--audio-channels", metavar="LIST",
                       help="Per-track channel override, e.g. 2=2,4=6")
    audio.add_argument("--audio-codec", default=DEFAULT_AUDIO_CODEC, metavar="CODEC",
                       help=f"Target audio codec (default: {DEFAULT_AUDIO_CODEC}). "
                            f"Also used by --audio-add-mode encode. Examples: "
                            f"aac, libopus, libmp3lame, ac3, eac3.")
    audio.add_argument("--audio-profile", default=DEFAULT_AUDIO_PROFILE, metavar="PROFILE",
                       help="AAC encoder profile (only used when codec is aac)")
    audio.add_argument("--audio-add-mode", metavar="MODE",
                       default="auto", choices=["auto", "copy", "encode"],
                       help="For --add-to-stream: auto (copy if compatible, "
                            "else encode), copy (force copy), or encode "
                            "(force encode to --audio-codec).")
    audio.add_argument("--audio-level", metavar="LEVEL",
                       default=DEFAULT_AUDIO_LEVEL,
                       choices=list(AUDIO_LEVEL_MULTIPLIERS.keys()),
                       help="Auto-bitrate level for --audio-add-mode encode: "
                            "data-saver, small, balanced, high, source")

    subs = parser.add_argument_group("Subtitles")
    subs.add_argument("--subtitles", choices=("auto", "none"), default="auto",
                      help="auto (default) or none")
    subs.add_argument("--subtitle-offset-ms", metavar="N or TRACK=N,...",
                      help="Shift subtitles by milliseconds. Default 0. "
                           "Per-track syntax: 1=500,2=-200. Fallback only.")
    subs.add_argument("--subtitle-time-scale", metavar="NUM/DEN",
                      help="Time scale for drift correction, e.g. 25/23.976")

    hls = parser.add_argument_group("HLS")
    hls.add_argument("--threads", "--video-threads", dest="threads",
                     type=int, default=DEFAULT_VIDEO_THREADS, metavar="N")
    hls.add_argument("--segment-time", "--hls-segment-time", dest="segment_time",
                     type=int, default=DEFAULT_SEGMENT_TIME, metavar="SEC")
    hls.add_argument("--keyframe-interval", "--force-keyframe-interval",
                     dest="keyframe_interval",
                     type=float, default=DEFAULT_KEYFRAME_INTERVAL, metavar="SEC")

    return parser


# ============================================================
# INPUT SELECTION (CLI convenience)
# ============================================================

def choose_input_file(supplied: Optional[str]) -> Path:
    if supplied:
        path = Path(supplied).expanduser()
        if not path.is_file():
            raise ConverterError(f"Input file does not exist:\n{path}")
        return path

    files = sorted([
        *Path.cwd().glob("*.mkv"),
        *Path.cwd().glob("*.mp4"),
        *Path.cwd().glob("*.mov"),
        *Path.cwd().glob("*.m4v"),
    ])
    if not files:
        raise ConverterError(
            "No input media file was specified and "
            "no MKV/MP4/MOV/M4V file was found."
        )
    if len(files) == 1:
        return files[0]

    print("\nMultiple media files found:\n")
    for index, file in enumerate(files, 1):
        print(f"  {index}. {file.name}")
    while True:
        try:
            choice = int(input("\nSelect input number: ").strip())
            if 1 <= choice <= len(files):
                return files[choice - 1]
        except ValueError:
            pass
        print("Invalid selection.")


# ============================================================
# CLI MAIN
# ============================================================

def main() -> int:
    global _DRY_RUN
    parser = build_parser()
    try:
        args = parser.parse_args()

        # --about short-circuits everything else.
        if getattr(args, "about", False):
            print_about()
            return 0

        _DRY_RUN = bool(getattr(args, "dry_run", False))

        # ---------- Add-to-stream mode ----------
        if args.add_to_stream:
            if not args.input:
                raise ConverterError(
                    "--add-to-stream requires an input file."
                )
            options = AddToStreamOptions(
                audio_add_mode=args.audio_add_mode,
                audio_codec=args.audio_codec,
                audio_level=args.audio_level,
                audio_profile=args.audio_profile,
                subtitle_offset_ms=args.subtitle_offset_ms,
                subtitle_time_scale=args.subtitle_time_scale,
                track=args.track,
                language=args.language,
                title=args.title,
                skip_master=args.skip_master,
                default_audio_track=args.default_audio_track,
                default_subtitle_track=args.default_subtitle_track,
            )

            # Build a minimal config for ffmpeg/ffprobe paths and
            # segment_time only.
            minimal_config = AppConfig(
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
                output=None,
                clean=False,
                skip_master=True,
                video=VideoRequest(mode="none"),
                video_level=DEFAULT_VIDEO_LEVEL,
                video_rate_mode="auto",
                video_codec=DEFAULT_VIDEO_CODEC,
                video_preset=DEFAULT_VIDEO_PRESET,
                threads=DEFAULT_VIDEO_THREADS,
                audio=AudioConfig(),
                audio_codec=args.audio_codec,
                audio_profile=args.audio_profile,
                subtitles=SubtitleConfig(mode="none"),
                keyframe_interval=DEFAULT_KEYFRAME_INTERVAL,
                segment_time=args.segment_time,
                default_audio_track=args.default_audio_track,
                default_subtitle_track=args.default_subtitle_track,
            )

            converter = HLSConverter(minimal_config)
            result = converter.add_to_stream(
                input_file=Path(args.input),
                stream_dir=Path(args.add_to_stream),
                options=options,
            )
            if result.success:
                return 0
            print(f"\n[ERROR] {result.error}", file=sys.stderr)
            return 1

        # ---------- Normal conversion mode ----------
        config = build_config(args)
        input_file = choose_input_file(args.input)
        ensure_executable(config.ffmpeg, "FFmpeg")
        ensure_executable(config.ffprobe, "FFprobe")

        output_dir = config.output
        if output_dir is None:
            output_dir = input_file.parent / (input_file.stem + "-stream")

        converter = HLSConverter(config)
        result = converter.convert(
            input_file=input_file,
            output_dir=output_dir,
        )
        if result.success:
            return 0
        print(f"\n[ERROR] {result.error}", file=sys.stderr)
        return 1

    except ConverterError as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n\n[ERROR] Operation cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())