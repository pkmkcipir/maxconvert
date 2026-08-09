# -*- coding: utf-8 -*-
"""
ffmpeg_manager.py
Mengelola deteksi FFmpeg/FFprobe yang sudah terpasang, mengunduh binary portable
secara otomatis jika belum ada (agar installer MaxConvert tetap ringan), dan
mendeteksi encoder hardware (GPU) apa saja yang benar-benar berfungsi di sistem.
"""
import os
import shutil
import subprocess
import threading
import zipfile
import urllib.request
from pathlib import Path

# Link resmi & stabil dari gyan.dev — selalu mengarah ke build "essentials" terbaru.
FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

NO_WINDOW_FLAG = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def get_app_data_dir() -> Path:
    """Lokasi penyimpanan data aplikasi (FFmpeg portable, cache, dll)."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    else:
        base = Path.home() / ".local" / "share"
    app_dir = base / "MaxConvert"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


class FFmpegManager:
    """Mendeteksi dan (bila perlu) mengunduh FFmpeg + FFprobe."""

    def __init__(self):
        self.data_dir = get_app_data_dir()
        self.ffmpeg_dir = self.data_dir / "ffmpeg"
        self.ffmpeg_exe = self.ffmpeg_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        self.ffprobe_exe = self.ffmpeg_dir / ("ffprobe.exe" if os.name == "nt" else "ffprobe")

    # -- deteksi -----------------------------------------------------------
    def _local_ready(self) -> bool:
        return self.ffmpeg_exe.exists() and self.ffprobe_exe.exists()

    def _system_ready(self) -> bool:
        return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

    def is_ready(self) -> bool:
        return self._local_ready() or self._system_ready()

    def get_paths(self):
        """Kembalikan (path_ffmpeg, path_ffprobe) yang siap dipakai, atau (None, None)."""
        if self._local_ready():
            return str(self.ffmpeg_exe), str(self.ffprobe_exe)
        if self._system_ready():
            return shutil.which("ffmpeg"), shutil.which("ffprobe")
        return None, None

    # -- unduh otomatis ------------------------------------------------------
    def download_async(self, progress_callback=None, done_callback=None) -> threading.Thread:
        """
        Unduh & ekstrak FFmpeg portable di background thread agar UI tidak macet.
        progress_callback(percent: float) dipanggil berkala.
        done_callback(success: bool, error_message: str) dipanggil saat selesai.
        """

        def _run():
            zip_path = self.data_dir / "_ffmpeg_download.zip"
            try:
                self.ffmpeg_dir.mkdir(parents=True, exist_ok=True)

                def _hook(block_num, block_size, total_size):
                    if progress_callback and total_size > 0:
                        pct = min(block_num * block_size / total_size * 100, 100)
                        progress_callback(pct)

                urllib.request.urlretrieve(FFMPEG_DOWNLOAD_URL, str(zip_path), _hook)

                found_any = False
                with zipfile.ZipFile(zip_path, "r") as zf:
                    for member in zf.namelist():
                        base = os.path.basename(member)
                        if base.lower() in ("ffmpeg.exe", "ffprobe.exe"):
                            target = self.ffmpeg_dir / base
                            with zf.open(member) as src, open(target, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            found_any = True

                if zip_path.exists():
                    zip_path.unlink()

                if found_any and self._local_ready():
                    if done_callback:
                        done_callback(True, "")
                else:
                    if done_callback:
                        done_callback(False, "Berkas ffmpeg.exe/ffprobe.exe tidak ditemukan di paket unduhan.")
            except Exception as exc:  # noqa: BLE001 - ingin tangkap semua & laporkan ke UI
                if zip_path.exists():
                    try:
                        zip_path.unlink()
                    except OSError:
                        pass
                if done_callback:
                    done_callback(False, str(exc))

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return thread


def detect_hardware_encoders(ffmpeg_path: str) -> dict:
    """
    Uji encoder GPU mana yang benar-benar bisa dipakai di sistem ini dengan
    merender klip sintetis super singkat. Mengembalikan dict of bool.
    """
    results = {"nvenc": False, "qsv": False, "amf": False}
    encoder_by_key = {"nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf"}

    if not ffmpeg_path:
        return results

    for key, encoder in encoder_by_key.items():
        try:
            proc = subprocess.run(
                [
                    ffmpeg_path, "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
                    "-frames:v", "1", "-c:v", encoder, "-f", "null", "-",
                ],
                capture_output=True,
                timeout=15,
                creationflags=NO_WINDOW_FLAG,
            )
            results[key] = proc.returncode == 0
        except Exception:
            results[key] = False

    return results
