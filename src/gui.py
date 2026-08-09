# -*- coding: utf-8 -*-
"""
gui.py
Antarmuka utama MaxConvert. Dibangun dengan CustomTkinter.

Alur singkat:
1. Saat aplikasi dibuka, cek apakah FFmpeg sudah tersedia (lokal/sistem).
   Jika belum, unduh otomatis (sekali saja) agar installer MaxConvert tetap ringan.
2. Setelah FFmpeg siap, deteksi encoder GPU yang benar-benar berfungsi.
3. Pengguna menambah file (tombol / drag-drop), mengatur mode & kualitas,
   lalu menekan "Mulai Konversi". Proses berjalan di background thread agar
   UI tetap responsif, dengan progres real-time per file & keseluruhan.
"""
import os
import sys
import queue
import threading
import uuid
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

from . import constants as C
from .converter import VideoConverter, ConversionJob
from .ffmpeg_manager import FFmpegManager, detect_hardware_encoders
from .utils import (
    format_size, format_duration, format_eta, unique_output_path,
    resource_path, parse_time_to_seconds, seconds_to_ffmpeg_time,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    class _DnDRoot(TkinterDnD.Tk, ctk.CTk):
        """Root window yang menggabungkan CustomTkinter dengan dukungan drag & drop."""

        def __init__(self, *args, **kwargs):
            ctk.CTk.__init__(self, *args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)

    DND_AVAILABLE = True
    _RootBase = _DnDRoot
except Exception:  # noqa: BLE001 - drag & drop bersifat opsional, aplikasi tetap jalan tanpanya
    DND_AVAILABLE = False
    _RootBase = ctk.CTk


ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class MaxConvertApp(_RootBase):
    def __init__(self):
        super().__init__()

        self.title(f"{C.APP_NAME} — {C.APP_TAGLINE}")
        self.geometry(f"{C.WINDOW_WIDTH}x{C.WINDOW_HEIGHT}")
        self.minsize(C.WINDOW_MIN_WIDTH, C.WINDOW_MIN_HEIGHT)

        try:
            self.iconbitmap(resource_path("assets/icon.ico"))
        except Exception:
            pass

        # -- Font -------------------------------------------------------
        self.font_title = ctk.CTkFont(family="Segoe UI", size=22, weight="bold")
        self.font_tagline = ctk.CTkFont(family="Segoe UI", size=12)
        self.font_section = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        self.font_body = ctk.CTkFont(family="Segoe UI", size=12)
        self.font_body_bold = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        self.font_small = ctk.CTkFont(family="Segoe UI", size=11)
        self.font_footer = ctk.CTkFont(family="Segoe UI", size=10)

        # -- State --------------------------------------------------------
        self.ffmpeg_manager = FFmpegManager()
        self.converter: VideoConverter | None = None
        self.available_hw_encoders = {"nvenc": False, "qsv": False, "amf": False}

        self.jobs: list[ConversionJob] = []
        self.jobs_by_id: dict[str, ConversionJob] = {}
        self.job_rows: dict[str, dict] = {}

        self.ui_queue: "queue.Queue" = queue.Queue()
        self.is_converting = False
        self.cancel_event = threading.Event()
        self._pending_jobs: list[ConversionJob] = []
        self._job_iter_lock = threading.Lock()
        self._job_iter_index = 0
        self._last_output_dir = None

        self.current_mode = C.MODE_CONVERT
        self.advanced_visible = False

        self._build_ui()
        self._poll_ui_queue()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if self.ffmpeg_manager.is_ready():
            self._on_ffmpeg_ready()
        else:
            self._start_ffmpeg_setup()

    # =====================================================================
    # BANGUN UI
    # =====================================================================
    def _build_ui(self):
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_setup_banner()
        self._build_main_area()
        self._build_progress_area()
        self._build_footer()

    def _build_header(self):
        header = ctk.CTkFrame(self, corner_radius=0, fg_color=("gray90", "gray14"), height=64)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)

        text_frame = ctk.CTkFrame(header, fg_color="transparent")
        text_frame.grid(row=0, column=0, sticky="w", padx=20, pady=8)
        ctk.CTkLabel(text_frame, text=C.APP_NAME, font=self.font_title, anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            text_frame, text=C.APP_TAGLINE, font=self.font_tagline, anchor="w",
            text_color=("gray35", "gray70"),
        ).pack(anchor="w")

    def _build_setup_banner(self):
        """Banner tipis yang muncul hanya saat FFmpeg pertama kali diunduh."""
        self.setup_banner = ctk.CTkFrame(self, fg_color=("#FEF3C7", "#78350F"), corner_radius=0, height=44)
        self.setup_banner.grid_columnconfigure(0, weight=1)
        self.setup_label = ctk.CTkLabel(
            self.setup_banner, text="Menyiapkan komponen FFmpeg untuk pertama kali...",
            font=self.font_small, text_color=("#78350F", "#FDE68A"),
        )
        self.setup_label.grid(row=0, column=0, sticky="w", padx=16, pady=4)
        self.setup_progress = ctk.CTkProgressBar(self.setup_banner, width=220, height=8)
        self.setup_progress.set(0)
        self.setup_progress.grid(row=0, column=1, sticky="e", padx=16, pady=4)
        # Belum ditampilkan (grid) — hanya muncul jika _start_ffmpeg_setup() dipanggil.

    def _build_main_area(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=2, column=0, sticky="nsew", padx=16, pady=(12, 6))
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=2)
        main.grid_rowconfigure(0, weight=1)

        self._build_queue_panel(main)
        self._build_settings_panel(main)

    # -- Panel Antrean File ------------------------------------------------
    def _build_queue_panel(self, parent):
        panel = ctk.CTkFrame(parent, corner_radius=10)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(panel, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        self.add_files_btn = ctk.CTkButton(
            toolbar, text="+ Tambah File", width=110, command=self._on_add_files_click
        )
        self.add_files_btn.pack(side="left", padx=(0, 6))
        self.add_folder_btn = ctk.CTkButton(
            toolbar, text="+ Tambah Folder", width=120, fg_color="transparent", border_width=1,
            command=self._on_add_folder_click,
        )
        self.add_folder_btn.pack(side="left", padx=(0, 6))
        self.clear_btn = ctk.CTkButton(
            toolbar, text="Bersihkan", width=90, fg_color="transparent", border_width=1,
            text_color=("gray30", "gray70"), command=self._clear_all,
        )
        self.clear_btn.pack(side="right")

        self.queue_list_frame = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        self.queue_list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.queue_list_frame.grid_columnconfigure(0, weight=1)

        self.empty_placeholder = ctk.CTkLabel(
            self.queue_list_frame,
            text=(
                "Seret & lepas file video di sini\n(atau klik \"Tambah File\")\n\n"
                "Mendukung MP4, MKV, AVI, MOV, WMV, FLV, WebM, MXF, TS, dan lainnya"
                if DND_AVAILABLE else
                "Klik \"Tambah File\" untuk memulai\n\n"
                "Mendukung MP4, MKV, AVI, MOV, WMV, FLV, WebM, MXF, TS, dan lainnya"
            ),
            font=self.font_small, text_color=("gray45", "gray55"), justify="center",
        )
        self.empty_placeholder.grid(row=0, column=0, pady=60)

        if DND_AVAILABLE:
            try:
                panel.drop_target_register(DND_FILES)
                panel.dnd_bind("<<Drop>>", self._on_drop)
                self.queue_list_frame.drop_target_register(DND_FILES)
                self.queue_list_frame.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    def _update_empty_placeholder(self):
        if self.jobs:
            self.empty_placeholder.grid_remove()
        else:
            self.empty_placeholder.grid()

    # -- Panel Pengaturan ----------------------------------------------------
    def _build_settings_panel(self, parent):
        outer = ctk.CTkFrame(parent, corner_radius=10)
        outer.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        panel = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        panel.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        panel.grid_columnconfigure(0, weight=1)
        self.settings_scroll = panel

        # -- Mode ---------------------------------------------------------
        ctk.CTkLabel(panel, text="Mode Konversi", font=self.font_section, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=10, pady=(10, 4)
        )
        self.mode_menu = ctk.CTkOptionMenu(
            panel, values=list(C.MODE_LABELS.values()), command=self._on_mode_change
        )
        self.mode_menu.set(C.MODE_LABELS[C.MODE_CONVERT])
        self.mode_menu.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 12))

        # Container untuk panel spesifik-mode (hanya satu yang tampil setiap saat)
        self.mode_panel_container = ctk.CTkFrame(panel, fg_color="transparent")
        self.mode_panel_container.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        self.mode_panel_container.grid_columnconfigure(0, weight=1)

        self._build_panel_convert()
        self._build_panel_audio()
        self._build_panel_gif()
        self._build_panel_compress()
        self._show_mode_panel(C.MODE_CONVERT)

        # -- Bagian umum: trim, output folder, proses bersamaan -----------
        self._build_common_settings(panel, start_row=3)

    def _section_label(self, master, text, row, col=0, pady=(14, 4)):
        ctk.CTkLabel(master, text=text, font=self.font_section, anchor="w").grid(
            row=row, column=col, sticky="ew", padx=10, pady=pady
        )

    # -- Panel Mode: Convert Format Video -------------------------------------
    def _build_panel_convert(self):
        f = ctk.CTkFrame(self.mode_panel_container, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        self.panel_convert = f

        ctk.CTkLabel(f, text="Format Output", font=self.font_body, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=10, pady=(4, 2)
        )
        self.output_format_menu = ctk.CTkOptionMenu(
            f, values=C.OUTPUT_FORMATS, command=self._on_output_format_change
        )
        self.output_format_menu.set("MP4")
        self.output_format_menu.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))

        ctk.CTkLabel(f, text="Preset Kualitas", font=self.font_body, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=10, pady=(0, 2)
        )
        self.quality_preset_menu = ctk.CTkOptionMenu(
            f, values=list(C.QUALITY_PRESETS.keys()), command=self._on_quality_preset_change
        )
        self.quality_preset_menu.set(C.DEFAULT_QUALITY_PRESET)
        self.quality_preset_menu.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))

        self.advanced_toggle_btn = ctk.CTkButton(
            f, text="▸ Pengaturan Lanjutan", fg_color="transparent", hover_color=("gray85", "gray25"),
            text_color=("gray30", "gray70"), anchor="w", command=self._toggle_advanced,
        )
        self.advanced_toggle_btn.grid(row=4, column=0, sticky="ew", padx=6, pady=(0, 4))

        adv = ctk.CTkFrame(f, fg_color=("gray95", "gray16"), corner_radius=8)
        adv.grid_columnconfigure(0, weight=1)
        self.advanced_frame = adv

        ctk.CTkLabel(adv, text="Codec Video", font=self.font_small, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=10, pady=(10, 2)
        )
        self.video_codec_menu = ctk.CTkOptionMenu(adv, values=list(C.VIDEO_CODEC_LABELS.values()))
        self.video_codec_menu.set(C.VIDEO_CODEC_LABELS["h264"])
        self.video_codec_menu.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))

        ctk.CTkLabel(adv, text="Kualitas Manual (CRF) — dipakai saat preset Custom", font=self.font_small, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=10, pady=(0, 2)
        )
        crf_row = ctk.CTkFrame(adv, fg_color="transparent")
        crf_row.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        crf_row.grid_columnconfigure(0, weight=1)
        self.crf_slider = ctk.CTkSlider(
            crf_row, from_=0, to=51, number_of_steps=51, command=self._on_crf_slide, state="disabled"
        )
        self.crf_slider.set(23)
        self.crf_slider.grid(row=0, column=0, sticky="ew")
        self.crf_value_label = ctk.CTkLabel(crf_row, text="23", width=28, font=self.font_small)
        self.crf_value_label.grid(row=0, column=1, padx=(8, 0))

        ctk.CTkLabel(adv, text="Kecepatan Encode CPU", font=self.font_small, anchor="w").grid(
            row=4, column=0, sticky="ew", padx=10, pady=(0, 2)
        )
        self.speed_preset_menu = ctk.CTkOptionMenu(adv, values=C.SPEED_PRESET_CPU, state="disabled")
        self.speed_preset_menu.set("fast")
        self.speed_preset_menu.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 8))

        ctk.CTkLabel(adv, text="Resolusi", font=self.font_small, anchor="w").grid(
            row=6, column=0, sticky="ew", padx=10, pady=(0, 2)
        )
        self.resolution_menu = ctk.CTkOptionMenu(adv, values=list(C.RESOLUTION_OPTIONS.keys()))
        self.resolution_menu.set("Original (Tanpa Ubah)")
        self.resolution_menu.grid(row=7, column=0, sticky="ew", padx=10, pady=(0, 8))

        ctk.CTkLabel(adv, text="Rotasi / Cerminkan", font=self.font_small, anchor="w").grid(
            row=8, column=0, sticky="ew", padx=10, pady=(0, 2)
        )
        self.rotate_menu = ctk.CTkOptionMenu(adv, values=list(C.ROTATE_OPTIONS.keys()))
        self.rotate_menu.set("Tanpa Rotasi")
        self.rotate_menu.grid(row=9, column=0, sticky="ew", padx=10, pady=(0, 8))

        ctk.CTkLabel(adv, text="Percepatan GPU", font=self.font_small, anchor="w").grid(
            row=10, column=0, sticky="ew", padx=10, pady=(0, 2)
        )
        self.hw_accel_menu = ctk.CTkOptionMenu(adv, values=[C.HW_ACCEL_LABELS["cpu"]])
        self.hw_accel_menu.set(C.HW_ACCEL_LABELS["cpu"])
        self.hw_accel_menu.grid(row=11, column=0, sticky="ew", padx=10, pady=(0, 8))

        ctk.CTkLabel(adv, text="Codec Audio", font=self.font_small, anchor="w").grid(
            row=12, column=0, sticky="ew", padx=10, pady=(0, 2)
        )
        self.audio_codec_menu = ctk.CTkOptionMenu(
            adv, values=list(C.AUDIO_CODEC_OPTIONS.keys()), command=self._on_audio_codec_change
        )
        self.audio_codec_menu.set("AAC (Umum)")
        self.audio_codec_menu.grid(row=13, column=0, sticky="ew", padx=10, pady=(0, 8))

        ctk.CTkLabel(adv, text="Bitrate Audio (kbps)", font=self.font_small, anchor="w").grid(
            row=14, column=0, sticky="ew", padx=10, pady=(0, 2)
        )
        bitrate_row = ctk.CTkFrame(adv, fg_color="transparent")
        bitrate_row.grid(row=15, column=0, sticky="ew", padx=10, pady=(0, 12))
        bitrate_row.grid_columnconfigure(0, weight=1)
        self.audio_bitrate_slider = ctk.CTkSlider(
            bitrate_row, from_=64, to=320, number_of_steps=16, command=self._on_audio_bitrate_slide
        )
        self.audio_bitrate_slider.set(128)
        self.audio_bitrate_slider.grid(row=0, column=0, sticky="ew")
        self.audio_bitrate_label = ctk.CTkLabel(bitrate_row, text="128", width=32, font=self.font_small)
        self.audio_bitrate_label.grid(row=0, column=1, padx=(8, 0))

    # -- Panel Mode: Ekstrak Audio ------------------------------------------
    def _build_panel_audio(self):
        f = ctk.CTkFrame(self.mode_panel_container, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        self.panel_audio = f

        ctk.CTkLabel(f, text="Format Audio", font=self.font_body, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=10, pady=(4, 2)
        )
        self.audio_format_menu = ctk.CTkOptionMenu(f, values=[fmt.upper() for fmt in C.AUDIO_EXTRACT_FORMATS])
        self.audio_format_menu.set("MP3")
        self.audio_format_menu.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))

        ctk.CTkLabel(f, text="Bitrate Audio (kbps)", font=self.font_body, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=10, pady=(0, 2)
        )
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        row.grid_columnconfigure(0, weight=1)
        self.audio2_bitrate_slider = ctk.CTkSlider(
            row, from_=64, to=320, number_of_steps=16, command=self._on_audio2_bitrate_slide
        )
        self.audio2_bitrate_slider.set(192)
        self.audio2_bitrate_slider.grid(row=0, column=0, sticky="ew")
        self.audio2_bitrate_label = ctk.CTkLabel(row, text="192", width=32, font=self.font_small)
        self.audio2_bitrate_label.grid(row=0, column=1, padx=(8, 0))

        ctk.CTkLabel(
            f, text="Catatan: WAV selalu tanpa kompresi (bitrate diabaikan).",
            font=self.font_small, text_color=("gray45", "gray55"), anchor="w", justify="left",
        ).grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))

    # -- Panel Mode: Convert ke GIF -------------------------------------------
    def _build_panel_gif(self):
        f = ctk.CTkFrame(self.mode_panel_container, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        self.panel_gif = f

        ctk.CTkLabel(f, text="Lebar GIF (px)", font=self.font_body, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=10, pady=(4, 2)
        )
        row1 = ctk.CTkFrame(f, fg_color="transparent")
        row1.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        row1.grid_columnconfigure(0, weight=1)
        self.gif_width_slider = ctk.CTkSlider(row1, from_=160, to=720, number_of_steps=14, command=self._on_gif_width_slide)
        self.gif_width_slider.set(480)
        self.gif_width_slider.grid(row=0, column=0, sticky="ew")
        self.gif_width_label = ctk.CTkLabel(row1, text="480", width=32, font=self.font_small)
        self.gif_width_label.grid(row=0, column=1, padx=(8, 0))

        ctk.CTkLabel(f, text="Kecepatan (FPS)", font=self.font_body, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=10, pady=(0, 2)
        )
        row2 = ctk.CTkFrame(f, fg_color="transparent")
        row2.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        row2.grid_columnconfigure(0, weight=1)
        self.gif_fps_slider = ctk.CTkSlider(row2, from_=5, to=24, number_of_steps=19, command=self._on_gif_fps_slide)
        self.gif_fps_slider.set(10)
        self.gif_fps_slider.grid(row=0, column=0, sticky="ew")
        self.gif_fps_label = ctk.CTkLabel(row2, text="10", width=32, font=self.font_small)
        self.gif_fps_label.grid(row=0, column=1, padx=(8, 0))

        ctk.CTkLabel(
            f, text="GIF otomatis memakai palet warna optimal untuk hasil terbaik.",
            font=self.font_small, text_color=("gray45", "gray55"), anchor="w", justify="left",
        ).grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))

    # -- Panel Mode: Kompres ke Ukuran Target ---------------------------------
    def _build_panel_compress(self):
        f = ctk.CTkFrame(self.mode_panel_container, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        self.panel_compress = f

        ctk.CTkLabel(f, text="Ukuran Target (MB)", font=self.font_body, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=10, pady=(4, 2)
        )
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        row.grid_columnconfigure(0, weight=1)
        self.target_size_slider = ctk.CTkSlider(row, from_=5, to=200, number_of_steps=39, command=self._on_target_size_slide)
        self.target_size_slider.set(25)
        self.target_size_slider.grid(row=0, column=0, sticky="ew")
        self.target_size_label = ctk.CTkLabel(row, text="25 MB", width=54, font=self.font_small)
        self.target_size_label.grid(row=0, column=1, padx=(8, 0))

        quick_row = ctk.CTkFrame(f, fg_color="transparent")
        quick_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        ctk.CTkButton(
            quick_row, text="16 MB (WhatsApp)", width=118, height=26, font=self.font_small,
            fg_color="transparent", border_width=1, text_color=("gray30", "gray75"),
            command=lambda: self._set_target_size(16),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            quick_row, text="25 MB (Email)", width=100, height=26, font=self.font_small,
            fg_color="transparent", border_width=1, text_color=("gray30", "gray75"),
            command=lambda: self._set_target_size(25),
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            quick_row, text="100 MB", width=76, height=26, font=self.font_small,
            fg_color="transparent", border_width=1, text_color=("gray30", "gray75"),
            command=lambda: self._set_target_size(100),
        ).pack(side="left", padx=4)

        ctk.CTkLabel(f, text="Codec Video", font=self.font_body, anchor="w").grid(
            row=3, column=0, sticky="ew", padx=10, pady=(0, 2)
        )
        self.compress_codec_menu = ctk.CTkOptionMenu(
            f, values=[C.VIDEO_CODEC_LABELS["h264"], C.VIDEO_CODEC_LABELS["h265"]]
        )
        self.compress_codec_menu.set(C.VIDEO_CODEC_LABELS["h264"])
        self.compress_codec_menu.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))

        ctk.CTkLabel(
            f, text="Output selalu berupa MP4. Estimasi bitrate dihitung otomatis dari durasi video.",
            font=self.font_small, text_color=("gray45", "gray55"), anchor="w", justify="left",
        ).grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 10))

    # -- Bagian umum: trim, folder output, proses bersamaan --------------------
    def _build_common_settings(self, panel, start_row):
        self._section_label(panel, "Potong Video (Opsional)", start_row)

        self.trim_enabled_var = ctk.BooleanVar(value=False)
        self.trim_check = ctk.CTkCheckBox(
            panel, text="Aktifkan potong video (berlaku ke semua file)",
            variable=self.trim_enabled_var, font=self.font_small, command=self._on_trim_toggle,
        )
        self.trim_check.grid(row=start_row + 1, column=0, sticky="w", padx=10, pady=(0, 6))

        self.trim_fields_frame = ctk.CTkFrame(panel, fg_color="transparent")
        self.trim_fields_frame.grid(row=start_row + 2, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.trim_fields_frame.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(self.trim_fields_frame, text="Mulai (mm:ss)", font=self.font_small).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(self.trim_fields_frame, text="Selesai (mm:ss)", font=self.font_small).grid(row=0, column=1, sticky="w")
        self.trim_start_entry = ctk.CTkEntry(self.trim_fields_frame, placeholder_text="00:00")
        self.trim_start_entry.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self.trim_end_entry = ctk.CTkEntry(self.trim_fields_frame, placeholder_text="kosong = sampai akhir")
        self.trim_end_entry.grid(row=1, column=1, sticky="ew", padx=(4, 0))
        self.trim_fields_frame.grid_remove()

        self._section_label(panel, "Folder Output", start_row + 3)
        self.same_as_source_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            panel, text="Simpan di folder yang sama dengan file asal", variable=self.same_as_source_var,
            font=self.font_small, command=self._on_same_as_source_toggle,
        ).grid(row=start_row + 4, column=0, sticky="w", padx=10, pady=(0, 6))

        out_row = ctk.CTkFrame(panel, fg_color="transparent")
        out_row.grid(row=start_row + 5, column=0, sticky="ew", padx=10, pady=(0, 10))
        out_row.grid_columnconfigure(0, weight=1)
        self.output_dir_entry = ctk.CTkEntry(out_row, placeholder_text="Pilih folder output...", state="disabled")
        self.output_dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.output_dir_btn = ctk.CTkButton(out_row, text="Pilih...", width=70, state="disabled", command=self._on_choose_output_dir)
        self.output_dir_btn.grid(row=0, column=1)

        self._section_label(panel, "Proses Bersamaan", start_row + 6)
        self.concurrent_menu = ctk.CTkOptionMenu(panel, values=["1", "2", "3"])
        self.concurrent_menu.set("1")
        self.concurrent_menu.grid(row=start_row + 7, column=0, sticky="ew", padx=10, pady=(0, 16))

    # -- Area Progres & Kontrol -------------------------------------------------
    def _build_progress_area(self):
        area = ctk.CTkFrame(self, corner_radius=10)
        area.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 6))
        area.grid_columnconfigure(0, weight=1)

        info_row = ctk.CTkFrame(area, fg_color="transparent")
        info_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        info_row.grid_columnconfigure(0, weight=1)
        self.overall_label = ctk.CTkLabel(info_row, text="Siap untuk memulai", font=self.font_body_bold, anchor="w")
        self.overall_label.grid(row=0, column=0, sticky="w")
        self.current_speed_label = ctk.CTkLabel(info_row, text="", font=self.font_small, text_color=("gray40", "gray65"))
        self.current_speed_label.grid(row=0, column=1, sticky="e")

        self.overall_progress_bar = ctk.CTkProgressBar(area, height=12)
        self.overall_progress_bar.set(0)
        self.overall_progress_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        btn_row = ctk.CTkFrame(area, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 14))
        self.start_btn = ctk.CTkButton(
            btn_row, text="Mulai Konversi", height=38, font=self.font_body_bold, command=self.start_conversion
        )
        self.start_btn.pack(side="left", padx=(0, 8))
        self.cancel_btn = ctk.CTkButton(
            btn_row, text="Batalkan", height=38, fg_color="#B91C1C", hover_color="#991B1B",
            state="disabled", command=self.cancel_conversion,
        )
        self.cancel_btn.pack(side="left", padx=(0, 8))
        self.open_output_btn = ctk.CTkButton(
            btn_row, text="Buka Folder Output", height=38, fg_color="transparent", border_width=1,
            text_color=("gray25", "gray80"), command=self._open_output_folder,
        )
        self.open_output_btn.pack(side="left")

    def _build_footer(self):
        footer = ctk.CTkLabel(
            self, text=f"{C.COPYRIGHT_TEXT}  •  {C.APP_NAME} v{C.APP_VERSION}",
            font=self.font_footer, text_color=("gray50", "gray50"),
        )
        footer.grid(row=4, column=0, pady=(0, 8))

    # =====================================================================
    # SETUP FFMPEG
    # =====================================================================
    def _start_ffmpeg_setup(self):
        self.setup_banner.grid(row=1, column=0, sticky="ew")
        self.start_btn.configure(state="disabled")
        self.ffmpeg_manager.download_async(
            progress_callback=lambda p: self.ui_queue.put(("ffmpeg_progress", p)),
            done_callback=lambda ok, err: self.ui_queue.put(("ffmpeg_done", (ok, err))),
        )

    def _update_setup_progress(self, percent: float):
        self.setup_progress.set(percent / 100.0)
        self.setup_label.configure(text=f"Mengunduh komponen FFmpeg... {percent:.0f}%")

    def _on_ffmpeg_setup_done(self, ok: bool, err: str):
        if ok:
            self.setup_banner.grid_remove()
            self._on_ffmpeg_ready()
        else:
            self.setup_label.configure(text=f"Gagal menyiapkan FFmpeg: {err}")
            messagebox.showerror(
                C.APP_NAME,
                "Gagal mengunduh FFmpeg secara otomatis.\n\n"
                f"Detail: {err}\n\n"
                "Silakan periksa koneksi internet Anda lalu buka ulang aplikasi. "
                "Alternatif lain: pasang FFmpeg secara manual dan pastikan tersedia di PATH sistem.",
            )

    def _on_ffmpeg_ready(self):
        ffmpeg_path, ffprobe_path = self.ffmpeg_manager.get_paths()
        self.converter = VideoConverter(ffmpeg_path, ffprobe_path)
        self.start_btn.configure(state="normal")
        threading.Thread(target=self._detect_gpu_background, args=(ffmpeg_path,), daemon=True).start()

    def _detect_gpu_background(self, ffmpeg_path):
        results = detect_hardware_encoders(ffmpeg_path)
        self.ui_queue.put(("gpu_detected", results))

    def _on_gpu_detected(self, results: dict):
        self.available_hw_encoders = results
        labels = []
        for key in ("nvenc", "qsv", "amf"):
            if results.get(key):
                labels.append(C.HW_ACCEL_LABELS[key])
        labels.append(C.HW_ACCEL_LABELS["cpu"])
        self.hw_accel_menu.configure(values=labels)
        self.hw_accel_menu.set(labels[0])

    # =====================================================================
    # EVENT: MODE & PENGATURAN
    # =====================================================================
    def _show_mode_panel(self, mode_key: str):
        for p in (self.panel_convert, self.panel_audio, self.panel_gif, self.panel_compress):
            p.grid_forget()
        panel_map = {
            C.MODE_CONVERT: self.panel_convert,
            C.MODE_AUDIO: self.panel_audio,
            C.MODE_GIF: self.panel_gif,
            C.MODE_COMPRESS: self.panel_compress,
        }
        panel_map[mode_key].grid(row=0, column=0, sticky="ew")
        if mode_key == C.MODE_CONVERT and self.advanced_visible:
            self.advanced_frame.grid(row=5, column=0, sticky="ew", padx=6, pady=(0, 4))

    def _on_mode_change(self, label: str):
        reverse = {v: k for k, v in C.MODE_LABELS.items()}
        self.current_mode = reverse.get(label, C.MODE_CONVERT)
        self._show_mode_panel(self.current_mode)

    def _toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_frame.grid(row=5, column=0, sticky="ew", padx=6, pady=(0, 4))
            self.advanced_toggle_btn.configure(text="▾ Pengaturan Lanjutan")
        else:
            self.advanced_frame.grid_remove()
            self.advanced_toggle_btn.configure(text="▸ Pengaturan Lanjutan")

    def _on_output_format_change(self, fmt: str):
        allowed = C.CODEC_BY_CONTAINER.get(fmt, ["h264", "h265"])
        values = [C.VIDEO_CODEC_LABELS[c] for c in allowed]
        self.video_codec_menu.configure(values=values)
        if self.video_codec_menu.get() not in values:
            self.video_codec_menu.set(values[0])

    def _on_quality_preset_change(self, preset: str):
        is_custom = preset == "Custom"
        state = "normal" if is_custom else "disabled"
        self.crf_slider.configure(state=state)
        self.speed_preset_menu.configure(state=state)
        if not is_custom:
            values = C.QUALITY_PRESETS[preset]
            self.crf_slider.set(values["crf"])
            self.crf_value_label.configure(text=str(values["crf"]))
            self.speed_preset_menu.set(values["speed"])

    def _on_crf_slide(self, value):
        self.crf_value_label.configure(text=str(int(value)))

    def _on_audio_codec_change(self, label: str):
        key = C.AUDIO_CODEC_OPTIONS.get(label, "aac")
        state = "disabled" if key in ("copy", "none") else "normal"
        self.audio_bitrate_slider.configure(state=state)

    def _on_audio_bitrate_slide(self, value):
        self.audio_bitrate_label.configure(text=str(int(value)))

    def _on_audio2_bitrate_slide(self, value):
        self.audio2_bitrate_label.configure(text=str(int(value)))

    def _on_gif_width_slide(self, value):
        self.gif_width_label.configure(text=str(int(value)))

    def _on_gif_fps_slide(self, value):
        self.gif_fps_label.configure(text=str(int(value)))

    def _on_target_size_slide(self, value):
        self.target_size_label.configure(text=f"{int(value)} MB")

    def _set_target_size(self, mb: int):
        self.target_size_slider.set(mb)
        self.target_size_label.configure(text=f"{mb} MB")

    def _on_trim_toggle(self):
        if self.trim_enabled_var.get():
            self.trim_fields_frame.grid()
        else:
            self.trim_fields_frame.grid_remove()

    def _on_same_as_source_toggle(self):
        if self.same_as_source_var.get():
            self.output_dir_entry.configure(state="disabled")
            self.output_dir_btn.configure(state="disabled")
        else:
            self.output_dir_entry.configure(state="normal")
            self.output_dir_btn.configure(state="normal")

    def _on_choose_output_dir(self):
        folder = filedialog.askdirectory(title="Pilih Folder Output")
        if folder:
            self.output_dir_entry.configure(state="normal")
            self.output_dir_entry.delete(0, "end")
            self.output_dir_entry.insert(0, folder)
            self.output_dir_entry.configure(state="normal" if not self.same_as_source_var.get() else "disabled")

    # =====================================================================
    # MANAJEMEN FILE / ANTREAN
    # =====================================================================
    def _on_add_files_click(self):
        pattern = " ".join(f"*{ext}" for ext in C.SUPPORTED_INPUT_EXTENSIONS)
        paths = filedialog.askopenfilenames(
            title="Pilih File Video",
            filetypes=[("File Video", pattern), ("Semua File", "*.*")],
        )
        if paths:
            self.add_files_from_paths(list(paths))

    def _on_add_folder_click(self):
        folder = filedialog.askdirectory(title="Pilih Folder Berisi Video")
        if not folder:
            return
        found = []
        for root_dir, _dirs, files in os.walk(folder):
            for fname in files:
                if Path(fname).suffix.lower() in C.SUPPORTED_INPUT_EXTENSIONS:
                    found.append(os.path.join(root_dir, fname))
        self.add_files_from_paths(found)

    def _on_drop(self, event):
        paths = self._parse_dnd_paths(event.data)
        self.add_files_from_paths(paths)

    @staticmethod
    def _parse_dnd_paths(data: str) -> list:
        """tkinterdnd2 membungkus path yang mengandung spasi dengan kurung kurawal { }."""
        paths, current, in_brace = [], "", False
        for ch in data:
            if ch == "{":
                in_brace = True
                current = ""
            elif ch == "}":
                in_brace = False
                paths.append(current)
                current = ""
            elif ch == " " and not in_brace:
                if current:
                    paths.append(current)
                    current = ""
            else:
                current += ch
        if current:
            paths.append(current)
        return paths

    def add_files_from_paths(self, paths: list):
        existing = {j.input_path for j in self.jobs}
        added = []
        for p in paths:
            p = os.path.normpath(p)
            if not os.path.isfile(p):
                continue
            if Path(p).suffix.lower() not in C.SUPPORTED_INPUT_EXTENSIONS:
                continue
            if p in existing:
                continue
            job = ConversionJob(job_id=str(uuid.uuid4()), input_path=p, output_path="", settings={})
            try:
                job.size_bytes = os.path.getsize(p)
            except OSError:
                job.size_bytes = 0
            self.jobs.append(job)
            self.jobs_by_id[job.job_id] = job
            existing.add(p)
            added.append(job)
            self._add_job_row(job)

        self._update_empty_placeholder()
        if added and self.converter:
            threading.Thread(target=self._probe_durations, args=(added,), daemon=True).start()

    def _probe_durations(self, jobs_list):
        for job in jobs_list:
            dur = self.converter.probe_duration(job.input_path)
            job.src_duration = dur
            job.duration = dur
            self.ui_queue.put(("job_update", job.job_id))

    def _add_job_row(self, job: ConversionJob):
        row = ctk.CTkFrame(self.queue_list_frame, fg_color=("gray92", "gray17"), corner_radius=8)
        row.grid(row=len(self.job_rows) + 1, column=0, sticky="ew", pady=4, padx=2)
        row.grid_columnconfigure(0, weight=1)

        name = Path(job.input_path).name
        display_name = name if len(name) <= 46 else name[:43] + "..."
        name_label = ctk.CTkLabel(row, text=display_name, anchor="w", font=self.font_body_bold)
        name_label.grid(row=0, column=0, sticky="ew", padx=(12, 4), pady=(8, 0))

        info_label = ctk.CTkLabel(
            row, text=f"{format_size(job.size_bytes)} • menghitung durasi...",
            anchor="w", font=self.font_small, text_color=("gray40", "gray60"),
        )
        info_label.grid(row=1, column=0, sticky="ew", padx=(12, 4), pady=(0, 8))

        status_label = ctk.CTkLabel(
            row, text=job.status, font=self.font_small, text_color=self._status_color(job.status), width=92
        )
        status_label.grid(row=0, column=1, rowspan=2, padx=6)

        progress_bar = ctk.CTkProgressBar(row, width=110, height=8)
        progress_bar.set(0)
        progress_bar.grid(row=0, column=2, rowspan=2, padx=6)

        remove_btn = ctk.CTkButton(
            row, text="✕", width=28, height=28, fg_color="transparent",
            hover_color=("gray80", "gray30"), text_color=("gray40", "gray70"),
            command=lambda jid=job.job_id: self._remove_job(jid),
        )
        remove_btn.grid(row=0, column=3, rowspan=2, padx=(6, 10))

        self.job_rows[job.job_id] = {
            "frame": row, "name_label": name_label, "info_label": info_label,
            "status_label": status_label, "progress_bar": progress_bar,
        }

    def _status_color(self, status: str):
        return {
            C.STATUS_WAITING: ("gray45", "gray60"),
            C.STATUS_PROCESSING: ("#2563EB", "#60A5FA"),
            C.STATUS_DONE: ("#16A34A", "#4ADE80"),
            C.STATUS_FAILED: ("#DC2626", "#F87171"),
            C.STATUS_CANCELLED: ("#D97706", "#FBBF24"),
        }.get(status, ("gray45", "gray60"))

    def _refresh_job_row(self, job: ConversionJob):
        widgets = self.job_rows.get(job.job_id)
        if not widgets:
            return
        dur_text = format_duration(job.duration) if job.duration else "menghitung durasi..."
        widgets["info_label"].configure(text=f"{format_size(job.size_bytes)} • {dur_text}")
        widgets["status_label"].configure(text=job.status, text_color=self._status_color(job.status))
        widgets["progress_bar"].set(max(0.0, min(job.progress / 100.0, 1.0)))

    def _remove_job(self, job_id):
        if self.is_converting:
            return
        job = self.jobs_by_id.pop(job_id, None)
        if job and job in self.jobs:
            self.jobs.remove(job)
        widgets = self.job_rows.pop(job_id, None)
        if widgets:
            widgets["frame"].destroy()
        self._update_empty_placeholder()

    def _clear_all(self):
        if self.is_converting:
            return
        for widgets in self.job_rows.values():
            widgets["frame"].destroy()
        self.job_rows.clear()
        self.jobs.clear()
        self.jobs_by_id.clear()
        self._update_empty_placeholder()
        self.overall_label.configure(text="Siap untuk memulai")
        self.overall_progress_bar.set(0)

    # =====================================================================
    # KONVERSI
    # =====================================================================
    def _gather_settings(self) -> dict:
        settings = {"mode": self.current_mode, "output_format": self.output_format_menu.get()}

        if self.current_mode == C.MODE_CONVERT:
            codec_reverse = {v: k for k, v in C.VIDEO_CODEC_LABELS.items()}
            hw_reverse = {v: k for k, v in C.HW_ACCEL_LABELS.items()}
            preset = self.quality_preset_menu.get()
            if preset != "Custom":
                p = C.QUALITY_PRESETS[preset]
                crf, speed = p["crf"], p["speed"]
            else:
                crf, speed = int(self.crf_slider.get()), self.speed_preset_menu.get()

            settings.update({
                "video_codec": codec_reverse.get(self.video_codec_menu.get(), "h264"),
                "hw_mode": hw_reverse.get(self.hw_accel_menu.get(), "cpu"),
                "crf": crf,
                "speed_preset": speed,
                "resolution": C.RESOLUTION_OPTIONS.get(self.resolution_menu.get()),
                "rotate": C.ROTATE_OPTIONS.get(self.rotate_menu.get()),
                "audio_codec": C.AUDIO_CODEC_OPTIONS.get(self.audio_codec_menu.get(), "aac"),
                "audio_bitrate": int(self.audio_bitrate_slider.get()),
            })
        elif self.current_mode == C.MODE_AUDIO:
            settings.update({
                "audio_format": self.audio_format_menu.get().lower(),
                "audio_bitrate": int(self.audio2_bitrate_slider.get()),
            })
        elif self.current_mode == C.MODE_GIF:
            settings.update({
                "gif_width": int(self.gif_width_slider.get()),
                "gif_fps": int(self.gif_fps_slider.get()),
            })
        elif self.current_mode == C.MODE_COMPRESS:
            codec_reverse = {v: k for k, v in C.VIDEO_CODEC_LABELS.items()}
            settings.update({
                "target_size_mb": int(self.target_size_slider.get()),
                "video_codec": codec_reverse.get(self.compress_codec_menu.get(), "h264"),
                "audio_codec": "aac",
                "audio_bitrate": 128,
            })

        if self.trim_enabled_var.get():
            start_sec = parse_time_to_seconds(self.trim_start_entry.get()) or 0
            end_sec = parse_time_to_seconds(self.trim_end_entry.get())
            if start_sec:
                settings["start_time"] = seconds_to_ffmpeg_time(start_sec)
            if end_sec is not None and end_sec > start_sec:
                settings["trim_duration_seconds"] = end_sec - start_sec

        return settings

    def _resolve_output_dir(self, job: ConversionJob) -> str:
        if self.same_as_source_var.get():
            return str(Path(job.input_path).parent)
        chosen = self.output_dir_entry.get().strip()
        return chosen if chosen else str(Path(job.input_path).parent)

    def _resolve_output_ext(self, settings: dict) -> str:
        mode = settings["mode"]
        if mode == C.MODE_AUDIO:
            return "." + settings.get("audio_format", "mp3")
        if mode == C.MODE_GIF:
            return ".gif"
        if mode == C.MODE_COMPRESS:
            return ".mp4"
        return C.OUTPUT_EXT_MAP.get(settings.get("output_format", "MP4"), ".mp4")

    def start_conversion(self):
        if self.is_converting or not self.jobs:
            return
        if not self.converter:
            messagebox.showwarning(C.APP_NAME, "FFmpeg belum siap. Mohon tunggu proses persiapan selesai.")
            return

        settings = self._gather_settings()
        pending = [j for j in self.jobs if j.status != C.STATUS_DONE]
        if not pending:
            messagebox.showinfo(C.APP_NAME, "Semua file di antrean sudah selesai dikonversi.")
            return

        for job in pending:
            job.settings = dict(settings)
            job.status = C.STATUS_WAITING
            job.progress = 0.0
            job.error_message = ""
            out_dir = self._resolve_output_dir(job)
            ext = self._resolve_output_ext(settings)
            out_name = Path(job.input_path).stem + ext
            job.output_path = unique_output_path(str(Path(out_dir) / out_name))
            self._last_output_dir = out_dir
            self._refresh_job_row(job)

        self.is_converting = True
        self.cancel_event.clear()
        self._set_controls_running(True)

        self._pending_jobs = pending
        self._job_iter_index = 0
        self._completed_jobs = 0

        n_workers = max(1, min(int(self.concurrent_menu.get()), 3))
        for _ in range(n_workers):
            threading.Thread(target=self._worker_loop, daemon=True).start()

    def _worker_loop(self):
        while True:
            with self._job_iter_lock:
                idx = self._job_iter_index
                if idx >= len(self._pending_jobs):
                    return
                self._job_iter_index += 1
            self._run_single_job(self._pending_jobs[idx])

    def _run_single_job(self, job: ConversionJob):
        if self.cancel_event.is_set():
            job.status = C.STATUS_CANCELLED
            self.ui_queue.put(("job_update", job.job_id))
            self._mark_job_finished()
            return

        job.status = C.STATUS_PROCESSING
        self.ui_queue.put(("job_update", job.job_id))

        src_duration = self.converter.probe_duration(job.input_path)
        job.src_duration = src_duration
        effective_duration = src_duration

        if job.settings.get("trim_duration_seconds"):
            effective_duration = job.settings["trim_duration_seconds"]
        elif job.settings.get("start_time") and src_duration > 0:
            start_sec = parse_time_to_seconds(job.settings["start_time"]) or 0
            effective_duration = max(src_duration - start_sec, 0.1)

        job.duration = effective_duration if effective_duration > 0 else src_duration

        def _progress_cb(pct, speed):
            job.progress = pct
            job.speed_text = speed
            self.ui_queue.put(("job_progress", job.job_id))

        ok = self.converter.convert(job, self.cancel_event, _progress_cb)

        if ok:
            job.status = C.STATUS_DONE
            job.progress = 100.0
        else:
            job.status = C.STATUS_CANCELLED if self.cancel_event.is_set() else C.STATUS_FAILED
        self.ui_queue.put(("job_update", job.job_id))
        self._mark_job_finished()

    def _mark_job_finished(self):
        with self._job_iter_lock:
            self._completed_jobs += 1
            done = self._completed_jobs >= len(self._pending_jobs)
        self.ui_queue.put(("overall_progress", None))
        if done:
            self.ui_queue.put(("conversion_finished", None))

    def _refresh_overall_progress(self):
        total = len(self._pending_jobs)
        if total == 0:
            return
        progress_sum = 0.0
        for j in self._pending_jobs:
            if j.status == C.STATUS_DONE:
                progress_sum += 100.0
            elif j.status == C.STATUS_PROCESSING:
                progress_sum += j.progress
            elif j.status in (C.STATUS_FAILED, C.STATUS_CANCELLED):
                progress_sum += 100.0
        overall_pct = progress_sum / total
        self.overall_progress_bar.set(overall_pct / 100.0)
        done_count = sum(1 for j in self._pending_jobs if j.status in (C.STATUS_DONE, C.STATUS_FAILED, C.STATUS_CANCELLED))
        self.overall_label.configure(text=f"{done_count} / {total} selesai ({overall_pct:.0f}%)")

        active = [j for j in self._pending_jobs if j.status == C.STATUS_PROCESSING]
        if active:
            speeds = ", ".join(f"{j.speed_text}" for j in active if j.speed_text != "-")
            self.current_speed_label.configure(text=f"Kecepatan: {speeds}" if speeds else "")
        else:
            self.current_speed_label.configure(text="")

    def _on_conversion_finished(self):
        self.is_converting = False
        self._set_controls_running(False)
        fail_count = sum(1 for j in self._pending_jobs if j.status == C.STATUS_FAILED)
        done_count = sum(1 for j in self._pending_jobs if j.status == C.STATUS_DONE)
        cancel_count = sum(1 for j in self._pending_jobs if j.status == C.STATUS_CANCELLED)
        self.current_speed_label.configure(text="")

        if cancel_count and not done_count and not fail_count:
            self.overall_label.configure(text="Konversi dibatalkan.")
        elif fail_count:
            self.overall_label.configure(text=f"Selesai: {done_count} berhasil, {fail_count} gagal.")
            failed_jobs = [j for j in self._pending_jobs if j.status == C.STATUS_FAILED]
            first_err = failed_jobs[0].error_message[-300:] if failed_jobs and failed_jobs[0].error_message else ""
            messagebox.showwarning(
                C.APP_NAME,
                f"{fail_count} file gagal dikonversi.\n\nContoh pesan error:\n{first_err}",
            )
        else:
            self.overall_label.configure(text=f"Semua {done_count} file berhasil dikonversi!")

    def _set_controls_running(self, running: bool):
        state = "disabled" if running else "normal"
        self.start_btn.configure(state=state, text="Memproses..." if running else "Mulai Konversi")
        self.cancel_btn.configure(state=("normal" if running else "disabled"))
        self.add_files_btn.configure(state=state)
        self.add_folder_btn.configure(state=state)
        self.clear_btn.configure(state=state)

    def cancel_conversion(self):
        if not self.is_converting:
            return
        self.cancel_event.set()
        self.cancel_btn.configure(state="disabled", text="Membatalkan...")

    def _open_output_folder(self):
        target = self._last_output_dir
        if not target and self.jobs:
            target = str(Path(self.jobs[0].input_path).parent)
        if target and os.path.isdir(target):
            from .utils import open_in_explorer
            open_in_explorer(target)
        else:
            messagebox.showinfo(C.APP_NAME, "Belum ada folder output yang tercatat. Tambahkan file & jalankan konversi terlebih dahulu.")

    # =====================================================================
    # POLLING ANTRIAN UI (dipanggil berkala dari main thread)
    # =====================================================================
    def _poll_ui_queue(self):
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "job_update":
                    job = self.jobs_by_id.get(payload)
                    if job:
                        self._refresh_job_row(job)
                elif kind == "job_progress":
                    job = self.jobs_by_id.get(payload)
                    if job:
                        self._refresh_job_row(job)
                elif kind == "overall_progress":
                    self._refresh_overall_progress()
                elif kind == "conversion_finished":
                    self._on_conversion_finished()
                elif kind == "ffmpeg_progress":
                    self._update_setup_progress(payload)
                elif kind == "ffmpeg_done":
                    ok, err = payload
                    self._on_ffmpeg_setup_done(ok, err)
                elif kind == "gpu_detected":
                    self._on_gpu_detected(payload)
        except queue.Empty:
            pass
        self.after(80, self._poll_ui_queue)

    # =====================================================================
    def _on_close(self):
        if self.is_converting:
            if messagebox.askyesno(
                C.APP_NAME,
                "Proses konversi sedang berjalan. Yakin ingin keluar dan membatalkan semua proses?",
            ):
                self.cancel_event.set()
                self.after(300, self.destroy)
            return
        self.destroy()
