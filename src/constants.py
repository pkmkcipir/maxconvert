# -*- coding: utf-8 -*-
"""
constants.py
Berisi seluruh konstanta aplikasi: identitas, daftar format, preset kualitas,
dan opsi lain yang dipakai di seluruh bagian MaxConvert.
"""

APP_NAME = "MaxConvert"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Convert Video Cepat & Ringan"
COPYRIGHT_TEXT = "© Copyright : iman.mn_"

# ---------------------------------------------------------------------------
# Format yang didukung
# ---------------------------------------------------------------------------
SUPPORTED_INPUT_EXTENSIONS = (
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mxf", ".vob", ".ogv", ".gif",
)

OUTPUT_FORMATS = ["MP4", "MKV", "AVI", "MOV", "WebM"]

OUTPUT_EXT_MAP = {
    "MP4": ".mp4",
    "MKV": ".mkv",
    "AVI": ".avi",
    "MOV": ".mov",
    "WebM": ".webm",
}

# Kompatibilitas codec video per kontainer output (dipakai untuk validasi ringan)
CODEC_BY_CONTAINER = {
    "MP4": ["h264", "h265"],
    "MKV": ["h264", "h265", "vp9"],
    "AVI": ["h264"],
    "MOV": ["h264", "h265"],
    "WebM": ["vp9"],
}

VIDEO_CODEC_LABELS = {
    "h264": "H.264 (Kompatibel Luas)",
    "h265": "H.265 / HEVC (Ukuran Lebih Kecil)",
    "vp9": "VP9 (Untuk WebM)",
}

AUDIO_CODEC_OPTIONS = {
    "AAC (Umum)": "aac",
    "MP3": "mp3",
    "Salin Tanpa Ubah (Copy)": "copy",
    "Tanpa Audio": "none",
}

# ---------------------------------------------------------------------------
# Preset kualitas -> (crf, speed_preset_cpu)
# CRF lebih kecil = kualitas lebih tinggi & file lebih besar
# ---------------------------------------------------------------------------
QUALITY_PRESETS = {
    "Kualitas Tinggi": {"crf": 18, "speed": "slow"},
    "Seimbang (Disarankan)": {"crf": 23, "speed": "fast"},
    "Ukuran Kecil": {"crf": 28, "speed": "faster"},
    "Custom": None,  # nilai diambil dari slider manual
}
DEFAULT_QUALITY_PRESET = "Seimbang (Disarankan)"

RESOLUTION_OPTIONS = {
    "Original (Tanpa Ubah)": None,
    "2160p (4K)": (3840, -2),
    "1440p (2K)": (2560, -2),
    "1080p (Full HD)": (1920, -2),
    "720p (HD)": (1280, -2),
    "480p (SD)": (854, -2),
}

ROTATE_OPTIONS = {
    "Tanpa Rotasi": None,
    "Putar 90° Searah Jarum Jam": "90cw",
    "Putar 90° Berlawanan Jarum Jam": "90ccw",
    "Putar 180°": "180",
    "Cerminkan Horizontal": "flip_h",
    "Cerminkan Vertikal": "flip_v",
}

SPEED_PRESET_CPU = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"]

HW_ACCEL_LABELS = {
    "auto": "Otomatis (Deteksi GPU)",
    "nvenc": "NVIDIA GPU (NVENC)",
    "qsv": "Intel Quick Sync (QSV)",
    "amf": "AMD GPU (AMF)",
    "cpu": "CPU Saja (Tanpa GPU)",
}

# ---------------------------------------------------------------------------
# Mode konversi
# ---------------------------------------------------------------------------
MODE_CONVERT = "convert"
MODE_AUDIO = "audio"
MODE_GIF = "gif"
MODE_COMPRESS = "compress"

MODE_LABELS = {
    MODE_CONVERT: "Convert Format Video",
    MODE_AUDIO: "Ekstrak Audio Saja",
    MODE_GIF: "Convert ke GIF",
    MODE_COMPRESS: "Kompres ke Ukuran Target",
}

AUDIO_EXTRACT_FORMATS = ["mp3", "aac", "m4a", "wav"]

STATUS_WAITING = "Menunggu"
STATUS_PROCESSING = "Memproses"
STATUS_DONE = "Selesai"
STATUS_FAILED = "Gagal"
STATUS_CANCELLED = "Dibatalkan"

# Ukuran jendela default
WINDOW_WIDTH = 980
WINDOW_HEIGHT = 700
WINDOW_MIN_WIDTH = 860
WINDOW_MIN_HEIGHT = 600
