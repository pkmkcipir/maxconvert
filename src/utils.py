# -*- coding: utf-8 -*-
"""
utils.py
Fungsi-fungsi bantu kecil yang dipakai di berbagai modul.
"""
import os
import sys
from pathlib import Path


def format_size(num_bytes: float) -> str:
    """Ubah jumlah byte menjadi teks yang mudah dibaca (KB/MB/GB)."""
    if num_bytes is None:
        return "-"
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < step:
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{int(num_bytes)} {unit}"
        num_bytes /= step
    return f"{num_bytes:.1f} PB"


def format_duration(seconds: float) -> str:
    """Ubah detik menjadi format jam:menit:detik."""
    if not seconds or seconds <= 0:
        return "-"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_eta(percent_done: float, elapsed_seconds: float) -> str:
    """Estimasi waktu tersisa berdasarkan progres saat ini."""
    if percent_done <= 0.5 or elapsed_seconds <= 0:
        return "menghitung..."
    total_estimate = elapsed_seconds / (percent_done / 100.0)
    remaining = max(total_estimate - elapsed_seconds, 0)
    return format_duration(remaining)


def unique_output_path(output_path: str) -> str:
    """
    Jika file output sudah ada, tambahkan (1), (2), dst agar tidak menimpa file lain.
    """
    path = Path(output_path)
    if not path.exists():
        return str(path)

    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        if not candidate.exists():
            return str(candidate)
        counter += 1


def safe_filename_stem(filename: str) -> str:
    """Ambil nama file tanpa ekstensi."""
    return Path(filename).stem


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def open_in_explorer(path: str) -> None:
    """Buka folder di Windows Explorer. Aman dipanggil di platform lain (tidak melakukan apa-apa)."""
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
    except Exception:
        pass


def resource_path(relative_path: str) -> str:
    """
    Path absolut ke berkas resource (mis. assets/icon.ico), baik saat dijalankan
    langsung dari source maupun setelah dibekukan menjadi .exe oleh PyInstaller.
    """
    if hasattr(sys, "_MEIPASS"):
        base = Path(getattr(sys, "_MEIPASS"))
    else:
        base = Path(__file__).resolve().parent.parent
    return str(base / relative_path)


def parse_time_to_seconds(text: str):
    """Ubah teks 'HH:MM:SS', 'MM:SS', atau detik polos menjadi float detik. None jika kosong/tidak valid."""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def seconds_to_ffmpeg_time(seconds: float) -> str:
    """Ubah detik menjadi format waktu HH:MM:SS.mmm yang dipahami FFmpeg."""
    seconds = max(seconds, 0)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"
