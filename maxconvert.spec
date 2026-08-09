# -*- mode: python ; coding: utf-8 -*-
"""
maxconvert.spec
File spesifikasi PyInstaller untuk MaxConvert.

PENTING: Build HARUS memakai mode onedir (bukan --onefile), karena CustomTkinter
menyertakan berkas data non-Python (.json tema, .otf font) yang tidak bisa
dikemas dengan baik oleh mode onefile. Lihat dokumentasi resmi CustomTkinter:
https://customtkinter.tomschimansky.com/documentation/packaging/

Cara pakai:
    pyinstaller maxconvert.spec
Hasil build ada di dist/MaxConvert/ (folder aplikasi lengkap).
"""
from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += collect_data_files("customtkinter")

# tkinterdnd2 bersifat opsional (aplikasi tetap jalan tanpa drag & drop jika gagal
# diimpor), jadi kegagalan collect di sini tidak menghentikan proses build.
try:
    datas += collect_data_files("tkinterdnd2")
except Exception:
    pass

datas += [("assets", "assets")]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MaxConvert",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MaxConvert",
)
