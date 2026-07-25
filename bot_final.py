"""
DEPRECATED - jangan dipakai lagi.

File ini dulunya salinan byte-per-byte dari github_bot_v2.py. Dua salinan
kode trading yang identik itu berbahaya: perbaikan di satu file tidak ikut
ke file lain, dan tidak ada yang tahu file mana yang sebenarnya berjalan.
Yang dipanggil oleh GitHub Actions adalah github_bot_v2.py.

Sekarang file ini hanya meneruskan ke modul yang benar, supaya perintah lama
seperti `python bot_final.py` tetap jalan tanpa menduplikasi logika.
"""

from github_bot_v2 import run_bot, update_performance_mini

if __name__ == "__main__":
    print("[DEPRECATED] bot_final.py -> meneruskan ke github_bot_v2.py\n")
    run_bot()
    update_performance_mini()
