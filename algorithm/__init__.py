"""
algorithm
==========
Algoritma generate jadwal kuliah (course_schedules + lectures) otomatis.

Pemakaian singkat (lihat example_integration.py untuk contoh lengkap di
app.py):

    from algorithm import generate_timeline

    result = generate_timeline(conn, timeline_generation_id)
    print(result.as_dict())
    conn.commit()  # generate_timeline TIDAK commit sendiri, caller yang commit

Struktur modul:
    config.py       - semua konstanta/heuristik yang bisa ditun-tuning
    models.py        - dataclass domain (Lecturer, Course, Room, dst)
    repository.py    - baca/tulis MySQL (pymysql)
    matching.py       - cari & urutkan kandidat dosen per course
    allocation.py      - primitif cari periode kontigu kosong + ruang
    scheduler.py        - orkestrasi 1 course -> list PlannedSession
    generator.py         - entry point generate_timeline()
"""

from .generator import GenerationResult, generate_timeline

__all__ = ["generate_timeline", "GenerationResult"]
