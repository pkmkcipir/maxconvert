# -*- coding: utf-8 -*-
"""
command_builder.py
Menerjemahkan pengaturan yang dipilih pengguna di GUI menjadi argumen FFmpeg.
Modul ini murni fungsi (tanpa efek samping) supaya mudah diuji.
"""

# codec_key -> {hw_mode: nama_encoder_ffmpeg}
_CODEC_ENCODER_MAP = {
    "h264": {"cpu": "libx264", "nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf"},
    "h265": {"cpu": "libx265", "nvenc": "hevc_nvenc", "qsv": "hevc_qsv", "amf": "hevc_amf"},
    "vp9": {"cpu": "libvpx-vp9"},
}

_ROTATE_FILTERS = {
    "90cw": "transpose=1",
    "90ccw": "transpose=2",
    "180": "transpose=2,transpose=2",
    "flip_h": "hflip",
    "flip_v": "vflip",
}


def build_video_filters(resolution: tuple | None, rotate_key: str | None) -> list:
    """Bangun daftar filter -vf (scale, rotate/flip)."""
    filters = []
    if resolution:
        w, h = resolution
        filters.append(f"scale={w}:{h}")
    if rotate_key and rotate_key in _ROTATE_FILTERS:
        filters.append(_ROTATE_FILTERS[rotate_key])
    return filters


def build_video_codec_args(codec_key: str, hw_mode: str, crf: int, speed_preset: str) -> list:
    """
    Bangun argumen -c:v ... untuk mode CPU maupun hardware acceleration.
    Jika hw_mode tidak tersedia untuk codec_key, otomatis jatuh ke CPU (libx264/libx265).
    """
    codec_table = _CODEC_ENCODER_MAP.get(codec_key, _CODEC_ENCODER_MAP["h264"])
    encoder = codec_table.get(hw_mode)
    if not encoder:
        encoder = codec_table.get("cpu")
        hw_mode = "cpu"

    if hw_mode == "nvenc":
        return ["-c:v", encoder, "-preset", "p5", "-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    if hw_mode == "qsv":
        return ["-c:v", encoder, "-global_quality", str(crf)]
    if hw_mode == "amf":
        return ["-c:v", encoder, "-quality", "balanced", "-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf)]
    if codec_key == "vp9":
        return ["-c:v", encoder, "-crf", str(crf), "-b:v", "0", "-deadline", "good", "-cpu-used", "2"]
    return ["-c:v", encoder, "-preset", speed_preset, "-crf", str(crf)]


def build_audio_codec_args(audio_key: str, bitrate_kbps: int) -> list:
    """Bangun argumen -c:a ... berdasarkan pilihan audio."""
    if audio_key == "none":
        return ["-an"]
    if audio_key == "copy":
        return ["-c:a", "copy"]
    codec_name = {"aac": "aac", "mp3": "libmp3lame"}.get(audio_key, "aac")
    return ["-c:a", codec_name, "-b:a", f"{bitrate_kbps}k"]


def build_convert_args(settings: dict) -> list:
    """Argumen untuk mode 'Convert Format Video' (mode utama)."""
    args = []

    filters = build_video_filters(settings.get("resolution"), settings.get("rotate"))
    if filters:
        args += ["-vf", ",".join(filters)]

    args += build_video_codec_args(
        settings.get("video_codec", "h264"),
        settings.get("hw_mode", "cpu"),
        settings.get("crf", 23),
        settings.get("speed_preset", "fast"),
    )
    args += build_audio_codec_args(settings.get("audio_codec", "aac"), settings.get("audio_bitrate", 128))

    # movflags +faststart membuat MP4 bisa langsung streaming (moov atom di depan)
    if settings.get("output_format") == "MP4":
        args += ["-movflags", "+faststart"]

    return args


def build_audio_extract_args(settings: dict) -> list:
    """Argumen untuk mode 'Ekstrak Audio Saja'."""
    fmt = settings.get("audio_format", "mp3")
    codec_map = {"mp3": "libmp3lame", "aac": "aac", "m4a": "aac", "wav": "pcm_s16le"}
    codec = codec_map.get(fmt, "libmp3lame")

    args = ["-vn", "-c:a", codec]
    if fmt != "wav":
        args += ["-b:a", f"{settings.get('audio_bitrate', 192)}k"]
    return args


def build_trim_pre_args(settings: dict) -> list:
    """Argumen -ss yang WAJIB ditaruh sebelum -i untuk fast-seek yang akurat."""
    start = settings.get("start_time")
    return ["-ss", start] if start else []


def build_trim_post_args(settings: dict) -> list:
    """Argumen -t (durasi) yang ditaruh setelah -i, dihitung dari trim_duration_seconds."""
    duration = settings.get("trim_duration_seconds")
    if duration and duration > 0:
        return ["-t", str(duration)]
    return []
