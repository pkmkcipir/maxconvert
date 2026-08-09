# -*- coding: utf-8 -*-
"""
converter.py
Mesin konversi inti MaxConvert. Bertugas menjalankan proses FFmpeg untuk setiap
file dalam antrean, mem-parsing output FFmpeg secara real-time untuk melaporkan
progres, dan menangani 4 mode: Convert Format, Ekstrak Audio, Convert ke GIF,
dan Kompres ke Ukuran Target.

Modul ini tidak menyentuh GUI sama sekali — hanya dipanggil dari thread worker.
"""
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import command_builder as cb
from . import constants as C

NO_WINDOW_FLAG = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
_SPEED_RE = re.compile(r"speed=\s*([\d.]+)x")


@dataclass
class ConversionJob:
    job_id: str
    input_path: str
    output_path: str
    settings: dict
    duration: float = 0.0          # durasi efektif (memperhitungkan trim) dipakai untuk progress %
    status: str = C.STATUS_WAITING
    progress: float = 0.0
    speed_text: str = "-"
    error_message: str = ""
    size_bytes: int = 0
    src_duration: float = 0.0      # durasi asli file, sebelum trim


class VideoConverter:
    """Membungkus semua pemanggilan FFmpeg/FFprobe."""

    def __init__(self, ffmpeg_path: str, ffprobe_path: str):
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    # -- probing -------------------------------------------------------
    def probe_duration(self, filepath: str) -> float:
        cmd = [
            self.ffprobe_path, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", filepath,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW_FLAG
            )
            return float(result.stdout.strip())
        except Exception:
            return 0.0

    # -- eksekusi ffmpeg dengan parsing progres -------------------------
    def _run_ffmpeg(
        self,
        args: list,
        duration_for_progress: float,
        cancel_event: threading.Event,
        progress_cb: Optional[Callable[[float, str], None]] = None,
    ):
        """Jalankan satu perintah ffmpeg lengkap. Mengembalikan (sukses, pesan_error)."""
        cmd = [self.ffmpeg_path, "-y"] + args
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                encoding="utf-8",
                errors="ignore",
                creationflags=NO_WINDOW_FLAG,
            )
        except FileNotFoundError:
            return False, "FFmpeg tidak ditemukan. Coba buka ulang aplikasi."
        except Exception as exc:  # noqa: BLE001
            return False, f"Gagal menjalankan FFmpeg: {exc}"

        log_tail = []
        assert process.stdout is not None
        for line in process.stdout:
            log_tail.append(line)
            if len(log_tail) > 60:
                log_tail.pop(0)

            if cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                return False, "__CANCELLED__"

            if progress_cb and duration_for_progress > 0:
                t_match = _TIME_RE.search(line)
                if t_match:
                    h, m, s = t_match.groups()
                    current = int(h) * 3600 + int(m) * 60 + float(s)
                    pct = max(0.0, min(current / duration_for_progress * 100, 100.0))
                    s_match = _SPEED_RE.search(line)
                    speed = f"{s_match.group(1)}x" if s_match else "-"
                    progress_cb(pct, speed)

        process.wait()
        success = process.returncode == 0
        error_msg = "" if success else "".join(log_tail[-12:]).strip()
        return success, error_msg

    # -- dispatch mode ---------------------------------------------------
    def convert(
        self,
        job: ConversionJob,
        cancel_event: threading.Event,
        progress_cb: Optional[Callable[[float, str], None]] = None,
    ) -> bool:
        Path(job.output_path).parent.mkdir(parents=True, exist_ok=True)
        mode = job.settings.get("mode", C.MODE_CONVERT)

        pre_args = cb.build_trim_pre_args(job.settings)
        post_args = cb.build_trim_post_args(job.settings)

        if mode == C.MODE_GIF:
            ok, err = self._convert_gif(job, pre_args, post_args, cancel_event, progress_cb)
        elif mode == C.MODE_COMPRESS:
            ok, err = self._convert_compress(job, pre_args, post_args, cancel_event, progress_cb)
        elif mode == C.MODE_AUDIO:
            args = pre_args + ["-i", job.input_path] + post_args + cb.build_audio_extract_args(job.settings) + [job.output_path]
            ok, err = self._run_ffmpeg(args, job.duration, cancel_event, progress_cb)
        else:
            args = pre_args + ["-i", job.input_path] + post_args + cb.build_convert_args(job.settings) + [job.output_path]
            ok, err = self._run_ffmpeg(args, job.duration, cancel_event, progress_cb)

        if not ok:
            job.error_message = "Dibatalkan oleh pengguna" if err == "__CANCELLED__" else err
        return ok

    # -- mode: GIF (dua tahap: palette lalu render) -----------------------
    def _convert_gif(self, job: ConversionJob, pre_args, post_args, cancel_event, progress_cb):
        fps = job.settings.get("gif_fps", 10)
        width = job.settings.get("gif_width", 480)
        palette_path = str(Path(job.output_path).with_suffix("")) + ".palette.png"

        palette_args = (
            pre_args + ["-i", job.input_path] + post_args
            + ["-vf", f"fps={fps},scale={width}:-1:flags=lanczos,palettegen"]
            + [palette_path]
        )
        ok, err = self._run_ffmpeg(palette_args, job.duration, cancel_event, None)
        if not ok:
            return False, err or "Gagal membuat palet warna GIF"

        final_args = (
            pre_args + ["-i", job.input_path] + post_args + ["-i", palette_path]
            + ["-lavfi", f"fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse"]
            + [job.output_path]
        )
        ok, err = self._run_ffmpeg(final_args, job.duration, cancel_event, progress_cb)

        try:
            Path(palette_path).unlink(missing_ok=True)
        except OSError:
            pass
        return ok, err

    # -- mode: kompres ke ukuran target (2-pass encoding) ------------------
    def _convert_compress(self, job: ConversionJob, pre_args, post_args, cancel_event, progress_cb):
        target_mb = job.settings.get("target_size_mb", 25)
        duration = job.duration if job.duration > 0 else job.src_duration
        if duration <= 0:
            return False, "Tidak bisa membaca durasi video untuk menghitung bitrate."

        audio_kbps = job.settings.get("audio_bitrate", 128)
        use_audio = job.settings.get("audio_codec", "aac") != "none"
        target_total_kbps = (target_mb * 8192) / duration
        video_kbps = max(int(target_total_kbps - (audio_kbps if use_audio else 0)), 100)

        codec = "libx265" if job.settings.get("video_codec") == "h265" else "libx264"
        passlog = str(Path(job.output_path).with_suffix("")) + "_2pass"
        null_out = "NUL" if os.name == "nt" else "/dev/null"

        pass1_args = (
            pre_args + ["-i", job.input_path] + post_args
            + ["-c:v", codec, "-b:v", f"{video_kbps}k", "-pass", "1", "-passlogfile", passlog, "-an",
               "-f", "null", null_out]
        )
        ok, err = self._run_ffmpeg(pass1_args, duration, cancel_event, None)
        if not ok:
            self._cleanup_passlog(passlog)
            return False, err or "Gagal pada analisis bitrate (pass 1)."

        audio_args = ["-c:a", "aac", "-b:a", f"{audio_kbps}k"] if use_audio else ["-an"]
        pass2_args = (
            pre_args + ["-i", job.input_path] + post_args
            + ["-c:v", codec, "-b:v", f"{video_kbps}k", "-pass", "2", "-passlogfile", passlog]
            + audio_args + [job.output_path]
        )
        ok, err = self._run_ffmpeg(pass2_args, duration, cancel_event, progress_cb)
        self._cleanup_passlog(passlog)
        return ok, err

    @staticmethod
    def _cleanup_passlog(passlog_prefix: str):
        for suffix in (".log", "-0.log", ".log.mbtree", "-0.log.mbtree"):
            try:
                Path(passlog_prefix + suffix).unlink(missing_ok=True)
            except OSError:
                pass
