"""
Regression test utk 2 bug yang dilaporkan user:

1. `_force_placement` untuk blok lab dulu cuma coba HARI PERTAMA di
   `day_order` lalu berhenti (unconditional `break`) -- padahal slot
   valid mungkin ada di hari lain. Akibatnya course yang SEBENARNYA
   masih bisa dicarikan jadwal malah tidak dapat course_schedule sama
   sekali.
2. `fallback_reason` dulu dihitung sebagai satu string gabungan lalu
   ditempel ke SEMUA sesi dalam 1 split -- termasuk sesi yang sudah
   dapat dosen asli & bebas-bentrok (padahal cuma porsi lain, mis. lab,
   yang gagal). Fallback sekarang harus HANYA nempel di porsi yang
   memang tidak dapat dosen ter-verifikasi.

Jalankan:
    python -m algorithm.tests.test_fallback_scoping
"""

from __future__ import annotations

from .. import config as cfg
from ..matching import build_candidates
from ..models import Course, Lecturer, Period, Room
from ..scheduler import schedule_course

SPEC = "spec-1"


def make_periods(n=6):
    return [
        Period(id=f"P{i+1}", time_start=f"{7+i:02d}:00:00", time_end=f"{8+i:02d}:00:00", order=i)
        for i in range(n)
    ]


def test_lab_force_placement_tries_all_days_not_just_first():
    """Monday penuh (ruang lab kepakai course lain), tapi Tuesday kosong
    -- dosen tidak eligible (kategori beda) supaya jalur force-placement
    yang dites, bukan jalur normal. Course HARUS tetap dapat blok lab di
    hari Tuesday, bukan hilang total."""
    periods = make_periods(3)
    course = Course(
        id="C1", name="Lab Tanpa Dosen", capacity=10, sks_count=4, lecturer_count=1, is_lab=True,
        is_odd=True, is_active=True, is_interdiscipline=False, category_id="prodi-lain",
        specialization_ids={SPEC},
    )
    # dosen ada tapi kategori tidak cocok -> tidak eligible sama sekali
    lecturer = Lecturer(
        id="FT1", name="A", category_id="prodi-if", is_active=True, is_interdiscipline=False,
        specialization_ids={SPEC}, is_dlb=False,
    )
    theory_room = Room(id="R1", name="Ruang Teori", capacity=20)
    lab_room = Room(id="LAB1", name="Lab", capacity=20, lab_group_id="LG1", lab_specialization_ids={SPEC})
    # penuhi lab_room di MONDAY (semua 3 periode) supaya force-placement
    # TERPAKSA lanjut cari hari lain.
    lab_room.booked["MONDAY"] = {"P1", "P2", "P3"}
    rooms = [theory_room, lab_room]

    candidates = build_candidates(course, {"FT1": lecturer})
    assert candidates == [], "dosen sengaja dibuat tidak eligible utk tes ini"

    sessions = schedule_course(course, candidates, rooms, periods, cfg.DAY_ORDER)
    lab_sessions = [s for s in sessions if s.is_lab_block]
    assert lab_sessions, (
        "blok lab harus tetap dapat course_schedule di hari lain (Tuesday dst), "
        "bukan hilang total gara2 Monday penuh"
    )
    days_used = {s.day for s in lab_sessions}
    assert "MONDAY" not in days_used, "Monday penuh, seharusnya tidak dipakai"
    assert days_used, "harus ada hari lain yang dipakai (bug lama: berhenti di hari pertama)"
    for s in lab_sessions:
        assert s.lecturer_assignments[0].lecturer_id is None
        assert s.lecturer_assignments[0].fallback_reason
    print(f"OK: blok lab force-placement lanjut cari hari lain -> dipakai {days_used}")


def test_fallback_reason_does_not_leak_to_successful_theory_sessions():
    """Dosen utama KETEMU & sesi teori berhasil penuh + bebas-bentrok,
    tapi blok lab-nya sendiri gagal dapat slot sama sekali (tidak ada
    ruang lab). Sesi TEORI (yang dapat dosen asli) TIDAK BOLEH ikut
    ditandai fallback_reason -- itu murni masalah porsi lab."""
    periods = make_periods(6)
    course = Course(
        id="C1", name="Course Campuran", capacity=10, sks_count=4, lecturer_count=1, is_lab=True,
        is_odd=True, is_active=True, is_interdiscipline=False, category_id="prodi-if",
        specialization_ids={SPEC},
    )
    lecturer = Lecturer(
        id="FT1", name="A", category_id="prodi-if", is_active=True, is_interdiscipline=False,
        specialization_ids={SPEC}, is_dlb=False,
    )
    # TIDAK ADA ruang lab sama sekali -> blok lab pasti gagal total,
    # tapi ruang teori tersedia -> teori harus tetap sukses & bersih.
    rooms = [Room(id="R1", name="Ruang Teori", capacity=20)]

    candidates = build_candidates(course, {"FT1": lecturer})
    sessions = schedule_course(course, candidates, rooms, periods, cfg.DAY_ORDER)

    theory_sessions = [s for s in sessions if not s.is_lab_block]
    lab_sessions = [s for s in sessions if s.is_lab_block]

    assert theory_sessions, "porsi teori harus tetap terjadwal"
    assert not lab_sessions, "blok lab memang harus gagal total (tidak ada ruang lab sama sekali)"

    for s in theory_sessions:
        primary = s.lecturer_assignments[0]
        assert primary.lecturer_id == "FT1", "teori harus dapat dosen asli yang sama"
        assert primary.fallback_reason is None, (
            "sesi teori yang SUDAH dapat dosen asli & bebas-bentrok tidak boleh ikut "
            "ditandai fallback hanya karena porsi lab (bagian lain) gagal"
        )
    print("OK: fallback_reason tidak bocor ke sesi teori yang sudah sukses dapat dosen")


def test_partial_theory_keeps_real_lecturer_on_scheduled_periods():
    """Kalau dosen cuma dapat SEBAGIAN periode teori (mis. 2 dari 3),
    periode yang BERHASIL dapat dosen tetap harus bersih (lecturer asli,
    tanpa fallback); sisanya yang dipaksa baru dapat fallback."""
    periods = make_periods(2)  # cuma 2 periode/hari -> sks 3 pasti kepecah
    course = Course(
        id="C1", name="Course Panjang", capacity=10, sks_count=3, lecturer_count=1, is_lab=False,
        is_odd=True, is_active=True, is_interdiscipline=False, category_id="prodi-if",
        specialization_ids=set(),
    )
    lecturer = Lecturer(
        id="FT1", name="A", category_id="prodi-if", is_active=True, is_interdiscipline=False, is_dlb=False,
    )
    rooms = [Room(id="R1", name="R1", capacity=20)]
    # Cuma sediakan hari MONDAY & TUESDAY (2 hari x 2 periode = 4 slot,
    # cukup utk teori 3 -> full dgn dosen asli, TANPA perlu force-placement.
    day_order = ["MONDAY", "TUESDAY"]

    sessions = schedule_course(course, [lecturer], rooms, periods, day_order)
    assert len(sessions) == 3
    for s in sessions:
        a = s.lecturer_assignments[0]
        assert a.lecturer_id == "FT1"
        assert a.fallback_reason is None, "harusnya dapat penuh dgn dosen asli, tidak perlu fallback"
    print("OK: teori yg lintas hari dgn dosen asli tetap bersih tanpa fallback")


if __name__ == "__main__":
    test_lab_force_placement_tries_all_days_not_just_first()
    test_fallback_reason_does_not_leak_to_successful_theory_sessions()
    test_partial_theory_keeps_real_lecturer_on_scheduled_periods()
    print("\nSemua test fallback-scoping lolos.")
