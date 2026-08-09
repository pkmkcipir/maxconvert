# -*- coding: utf-8 -*-
"""
main.py — Titik masuk aplikasi MaxConvert.
Jalankan dengan: python main.py
"""
import sys
from pathlib import Path

# Pastikan folder proyek ini ada di sys.path agar `from src...` selalu bisa diimpor,
# terlepas dari direktori kerja saat aplikasi dijalankan.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.gui import MaxConvertApp  # noqa: E402


def main():
    app = MaxConvertApp()
    app.mainloop()


if __name__ == "__main__":
    main()
