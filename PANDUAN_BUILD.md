# Panduan Build MaxConvert

Ada 2 cara membangun `MaxConvert-Setup.exe`:

- **Opsi A — Build Otomatis via GitHub Actions** (disarankan, tidak perlu komputer Windows)
- **Opsi B — Build Manual di Windows** (untuk testing cepat di komputer sendiri)

---

## Opsi A: Build Otomatis via GitHub Actions

Workflow-nya (`.github/workflows/build.yml`) sudah lengkap disiapkan. GitHub akan menjalankan Windows virtual machine, meng-compile `MaxConvert.exe`, membungkusnya jadi installer, lalu menyediakan hasilnya untuk diunduh — semua otomatis, gratis untuk repository publik (dan repository privat juga dapat jatah menit gratis per bulan).

### Langkah 1 — Buat Repository di GitHub

1. Buka [github.com/new](https://github.com/new), buat repository baru (misal `MaxConvert`). Boleh publik atau privat.
2. Di komputer Anda, masuk ke folder proyek `MaxConvert` lalu jalankan:

   ```bash
   git init
   git add .
   git commit -m "Initial commit - MaxConvert"
   git branch -M main
   git remote add origin https://github.com/USERNAME/MaxConvert.git
   git push -u origin main
   ```

   Ganti `USERNAME` dengan username GitHub Anda.

### Langkah 2 — Jalankan Build

Ada 2 cara memicu build:

**Cara 1: Push tag versi (otomatis membuat GitHub Release)**

```bash
git tag v1.0.0
git push origin v1.0.0
```

**Cara 2: Trigger manual (tanpa tag, untuk testing)**

1. Buka repository di GitHub → tab **Actions**.
2. Klik workflow **Build MaxConvert** di sidebar kiri.
3. Klik tombol **Run workflow** → isi nomor versi (opsional) → **Run workflow**.

### Langkah 3 — Unduh Hasil Build

- **Jika lewat tag (Cara 1):** buka tab **Releases** di repository Anda. `MaxConvert-Setup.exe` akan otomatis tersedia di sana setelah build selesai (±3–5 menit).
- **Jika lewat manual (Cara 2):** buka tab **Actions** → klik run yang baru saja selesai (tanda centang hijau) → scroll ke bagian **Artifacts** di bawah → unduh `MaxConvert-Setup-vX.X.X.zip`, di dalamnya ada `MaxConvert-Setup.exe`.

Itu saja — file `MaxConvert-Setup.exe` tersebut sudah bisa dibagikan dan dipasang langsung di komputer Windows 11 mana pun, tanpa perlu Python atau tools lain terpasang.

### Apa yang Dilakukan Workflow di Balik Layar

| Langkah | Fungsi |
|---|---|
| `actions/checkout` | Ambil kode dari repository |
| `actions/setup-python` | Siapkan Python 3.12 |
| `pip install -r requirements.txt` | Pasang CustomTkinter, tkinterdnd2, PyInstaller |
| `pyinstaller maxconvert.spec` | Kompilasi `main.py` + semua modul jadi `MaxConvert.exe` (mode folder/onedir) |
| `choco install innosetup` | Pasang Inno Setup di runner Windows |
| `ISCC installer.iss` | Bungkus hasil PyInstaller jadi satu `MaxConvert-Setup.exe` |
| `upload-artifact` | Simpan hasil build agar bisa diunduh dari tab Actions |
| `softprops/action-gh-release` | (Hanya saat push tag) Buat GitHub Release otomatis dengan installer terlampir |

---

## Opsi B: Build Manual di Windows

Kalau Anda punya akses ke komputer Windows 11 dan ingin build/testing langsung tanpa GitHub:

### Prasyarat

- [Python 3.11 atau 3.12](https://www.python.org/downloads/) (centang "Add python.exe to PATH" saat instalasi)
- [Inno Setup 6](https://jrsoftware.org/isdl.php)

### Langkah-Langkah

```bat
:: 1. Masuk ke folder proyek
cd MaxConvert

:: 2. (Opsional tapi disarankan) buat virtual environment
python -m venv venv
venv\Scripts\activate

:: 3. Pasang dependensi
pip install -r requirements.txt

:: 4. Coba jalankan dulu untuk memastikan semua normal
python main.py

:: 5. Build jadi .exe (mode folder, WAJIB pakai file .spec ini)
pyinstaller maxconvert.spec

:: Hasil ada di dist\MaxConvert\MaxConvert.exe

:: 6. Bungkus jadi installer (buka Inno Setup Compiler, atau lewat command line:)
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

:: Hasil installer ada di installer_output\MaxConvert-Setup.exe
```

---

## Update Versi Aplikasi

Untuk merilis versi baru:

1. Ubah `APP_VERSION` di `src/constants.py` (opsional, hanya untuk teks yang tampil di footer aplikasi).
2. Push tag baru, misalnya:
   ```bash
   git add .
   git commit -m "Update fitur X"
   git tag v1.1.0
   git push origin main
   git push origin v1.1.0
   ```
3. GitHub Actions otomatis build & bikin Release baru dengan nomor versi `1.1.0` (diambil dari nama tag, dipakai juga sebagai `AppVersion` di installer).

## Kustomisasi

- **Ganti ikon:** ganti file `assets/icon.ico` (gunakan file .ico multi-resolusi, idealnya berisi ukuran 16/32/48/256px).
- **Ganti nama aplikasi:** ubah `APP_NAME` di `src/constants.py`, dan `MyAppName` di `installer.iss`.
- **Ganti teks footer/copyright:** ubah `COPYRIGHT_TEXT` di `src/constants.py`.
- **Tambah format output baru:** tambahkan di `OUTPUT_FORMATS` dan `OUTPUT_EXT_MAP` di `src/constants.py`, lalu sesuaikan `CODEC_BY_CONTAINER` bila perlu.

## Troubleshooting

**"ISCC.exe tidak ditemukan" saat build lokal**
Pastikan Inno Setup 6 terpasang di lokasi default. Jika lokasi berbeda, sesuaikan path di perintah langkah 6 atau di `.github/workflows/build.yml`.

**Tema CustomTkinter tidak muncul / aplikasi hasil build terlihat "polos" (bukan gaya modern)**
Ini biasanya karena data folder CustomTkinter tidak ikut ter-bundle. `maxconvert.spec` sudah menangani ini lewat `collect_data_files("customtkinter")` — pastikan tidak menghapus bagian tersebut, dan selalu build dengan `pyinstaller maxconvert.spec` (bukan `pyinstaller main.py` langsung).

**Aplikasi gagal mengunduh FFmpeg otomatis di komputer pengguna**
Kemungkinan koneksi internet pengguna diblokir firewall/proxy kantor. Solusi manual: unduh [ffmpeg-release-essentials.zip](https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip), ekstrak `ffmpeg.exe` & `ffprobe.exe`, taruh di folder `%LOCALAPPDATA%\MaxConvert\ffmpeg\`.

**Build GitHub Actions gagal**
Buka tab **Actions** → klik run yang gagal (tanda silang merah) → klik nama step yang gagal untuk melihat detail error log.

---
© Copyright : iman.mn_
