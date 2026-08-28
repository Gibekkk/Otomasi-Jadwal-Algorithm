"""
Smoke test end-to-end TANPA database sungguhan -- data disusun langsung
sebagai objek `models.py` supaya logic inti (matching + scheduler) bisa
divalidasi cepat. Tidak butuh pymysql/mariadb.

Jalankan:
    cd algorithm/..   # root project
    python -m algorithm.tests.test_smoke

Kalau pytest terinstall, juga bisa:
    pytest algorithm/tests/test_smoke.py
"""

from __future__ import annotations

from .. import config as cfg
from ..generator import order_courses
from ..matching import build_candidates
from ..models import Course, Lecturer, Period, Room
from ..scheduler import schedule_course

SPEC_BACKEND = "spec-backend"
SPEC_NETWORK = "spec-network"


def make_periods(n=8):
    periods = []
    hour = 7
    for i in range(n):
        periods.append(
            Period(
                id=f"P{i+1}",
                time_start=f"{hour:02d}:00:00",
                time_end=f"{hour+1:02d}:00:00",
                order=i,
            )
        )
        hour += 1
    return periods


def make_lecturers():
    lecturers = {}

    # Dosen full time (tidak ada baris lecturer_schedules -> available di semua periode)
    lecturers["FT1"] = Lecturer(
        id="FT1",
        name="Dr. Fulan (full time)",
        category_id="prodi-if",
        is_active=True,
        is_interdiscipline=False,
        specialization_ids={SPEC_BACKEND},
        is_dlb=False,
    )
    lecturers["FT2"] = Lecturer(
        id="FT2",
        name="Dr. Fulanah (full time)",
        category_id="prodi-if",
        is_active=True,
        is_interdiscipline=False,
        specialization_ids={SPEC_NETWORK},
        is_dlb=False,
    )

    # Dosen DLB, jadwal terbatas (hanya 3 periode tersedia total)
    lecturers["DLB1"] = Lecturer(
        id="DLB1",
        name="Budi (DLB)",
        category_id="prodi-if",
        is_active=True,
        is_interdiscipline=False,
        specialization_ids={SPEC_BACKEND},
        available_period_ids={"P1", "P2", "P3"},
        is_dlb=True,
    )
    # DLB dengan jadwal sangat sempit (cuma 1 periode) -- dipakai utk cek
    # "course sks <= lecturer schedule count" menolak dia utk course besar
    lecturers["DLB2"] = Lecturer(
        id="DLB2",
        name="Citra (DLB)",
        category_id="prodi-if",
        is_active=True,
        is_interdiscipline=False,
        specialization_ids={SPEC_BACKEND},
        available_period_ids={"P1"},
        is_dlb=True,
    )
    return lecturers


def make_rooms():
    return [
        Room(id="R1", name="Ruang 101", capacity=40),
        Room(id="R2", name="Ruang 102", capacity=25),
        Room(id="LAB1", name="Lab Jaringan", capacity=20, lab_group_id="LG1", lab_specialization_ids={SPEC_NETWORK}),
        Room(id="LAB2", name="Lab RPL", capacity=15, lab_group_id="LG2", lab_specialization_ids={SPEC_BACKEND}),
    ]


def make_courses():
    return [
        Course(
            id="C1",
            name="Pemrograman Web",
            capacity=30,
            sks_count=3,
            lecturer_count=1,
            is_lab=False,
            is_odd=True,
            is_active=True,
            is_interdiscipline=False,
            category_id="prodi-if",
            specialization_ids={SPEC_BACKEND},
        ),
        Course(
            id="C2",
            name="Jaringan Komputer",
            capacity=18,
            sks_count=4,
            lecturer_count=1,
            is_lab=True,
            is_odd=True,
            is_active=True,
            is_interdiscipline=False,
            category_id="prodi-if",
            specialization_ids={SPEC_NETWORK},
        ),
        Course(
            id="C3",
            name="Basis Data (kelas besar)",
            capacity=70,  # lebih besar dari kapasitas ruang manapun -> harus split
            sks_count=2,
            lecturer_count=1,
            is_lab=False,
            is_odd=True,
            is_active=True,
            is_interdiscipline=False,
            category_id="prodi-if",
            specialization_ids=set(),
        ),
        Course(
            id="C4",
            name="Course Tanpa Dosen Cocok",
            capacity=20,
            sks_count=2,
            lecturer_count=1,
            is_lab=False,
            is_odd=True,
            is_active=True,
            is_interdiscipline=False,
            category_id="prodi-if",
            specialization_ids={"spec-tidak-ada-dosennya"},
        ),
    ]


def run():
    periods = make_periods()
    lecturers = make_lecturers()
    rooms = make_rooms()
    courses = make_courses()

    ordered = order_courses(courses)
    assert ordered[0].id == "C2", "course lab dgn sks besar harus diproses duluan"

    all_sessions = []
    for course in ordered:
        candidates = build_candidates(course, lecturers)
        sessions = schedule_course(course, candidates, rooms, periods, cfg.DAY_ORDER)
        all_sessions.extend(sessions)
        print(f"course={course.name:30s} splits={sorted({s.course_index for s in sessions})} sessions={len(sessions)}")

    # --- assertions ---

    # C1: course biasa sks=3. Sejak 1 chunk (blok periode kontigu/hari) = 1
    # course_schedule, dan sks=3 termasuk PRIORITIZE_DAY_SPLIT_FOR_SKS
    # (dibatasi maks ceil(3/2)=2 periode/hari), C1 harus kepecah jadi 2
    # course_schedule (2 periode di hari pertama + 1 periode di hari
    # berikutnya) -- BUKAN 3 course_schedule identik (1 per periode).
    c1_sessions = [s for s in all_sessions if s.course_id == "C1"]
    assert len(c1_sessions) == 2, f"C1 harus 2 course_schedule (chunk 2+1 hari), dapat {len(c1_sessions)}"
    assert sum(s.sks_count for s in c1_sessions) == 3, (
        f"total sks_count C1 di semua course_schedule harus 3, dapat {sum(s.sks_count for s in c1_sessions)}"
    )
    assert all(not s.is_lab_block for s in c1_sessions)
    assert all(a.lecturer_id is not None for s in c1_sessions for a in s.lecturer_assignments), (
        "C1 harus dapat dosen (FT1 cocok spesialisasi backend)"
    )

    # C2: course lab sks=4 -> teori 3 periode (kepecah 2+1 hari krn day-split
    # cap sks=3) + 1 blok lab kontigu -> total 3 course_schedule (2 teori +
    # 1 lab), BUKAN 6 course_schedule 1-per-periode. Blok lab disimpan
    # dengan sks_count=1 (bukan 3) krn backend sudah punya konvensi tetap
    # "1 course_schedule lab = 3 schedule slot berturutan dari period_id
    # start" -- period_id start-nya tetap harus benar (awal blok 3-periode).
    c2_sessions = [s for s in all_sessions if s.course_id == "C2"]
    lab_blocks = [s for s in c2_sessions if s.is_lab_block]
    theory_blocks = [s for s in c2_sessions if not s.is_lab_block]
    assert len(theory_blocks) == 2, f"C2 teori harus 2 course_schedule (chunk 2+1 hari), dapat {len(theory_blocks)}"
    assert sum(s.sks_count for s in theory_blocks) == 3, "total sks_count teori C2 harus 3"
    assert len(lab_blocks) == 1, f"C2 lab harus 1 course_schedule kontigu, dapat {len(lab_blocks)}"
    assert lab_blocks[0].sks_count == 1, (
        "sks_count blok lab C2 harus tetap 1 (backend sudah mengekspansi 1 lab jadi 3 schedule sendiri)"
    )
    lab_room = next(r for r in rooms if r.id == lab_blocks[0].room_id)
    assert lab_room.is_lab and SPEC_NETWORK in lab_room.lab_specialization_ids, (
        "ruang lab yg dipilih harus match spesialisasi course (jaringan)"
    )

    # C3: kapasitas 70 > kapasitas ruang terbesar (40) -> harus ke-split min 2 course_index
    c3_indices = {s.course_index for s in all_sessions if s.course_id == "C3"}
    assert len(c3_indices) >= 2, f"C3 (kapasitas 70) harus split jadi >=2 kelas, dapat {c3_indices}"

    # C4: tidak ada dosen dengan spesialisasi yang cocok -> harus tetap ada course_schedule
    # (best effort) tapi lecturer_id None + fallback_reason terisi
    c4_sessions = [s for s in all_sessions if s.course_id == "C4"]
    assert len(c4_sessions) > 0, "C4 tetap harus menghasilkan course_schedule (best effort placement)"
    for s in c4_sessions:
        primary = s.lecturer_assignments[0]
        assert primary.lecturer_id is None, "C4 seharusnya tidak dapat dosen sama sekali"
        assert primary.fallback_reason, "C4 harus punya fallback_reason"

    print("\nSemua assertion lolos.")


if __name__ == "__main__":
    run()
