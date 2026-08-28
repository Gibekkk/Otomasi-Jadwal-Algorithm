"""
Test edge case tambahan (masih tanpa DB). Jalankan:
    python -m algorithm.tests.test_edge_cases
"""

from __future__ import annotations

from .. import config as cfg
from ..matching import build_candidates, is_eligible
from ..models import Course, Lecturer, Period, Room
from ..scheduler import schedule_course


def make_periods(n):
    return [Period(id=f"P{i+1}", time_start=f"{7+i:02d}:00:00", time_end=f"{8+i:02d}:00:00", order=i) for i in range(n)]


def test_dlb_rejected_when_schedule_not_enough():
    """STEP: 'match course to candidate lecturers -> course sks <= lecturer schedule count'"""
    course = Course(
        id="C1", name="X", capacity=10, sks_count=3, lecturer_count=1, is_lab=False, is_odd=True,
        is_active=True, is_interdiscipline=False, category_id="p1", specialization_ids=set(),
    )
    dlb_cukup = Lecturer(
        id="L1", name="A", category_id="p1", is_active=True, is_interdiscipline=False,
        available_period_ids={"P1", "P2", "P3"}, is_dlb=True,
    )
    dlb_kurang = Lecturer(
        id="L2", name="B", category_id="p1", is_active=True, is_interdiscipline=False,
        available_period_ids={"P1", "P2"}, is_dlb=True,
    )
    ok1, _ = is_eligible(course, dlb_cukup)
    ok2, reason2 = is_eligible(course, dlb_kurang)
    assert ok1 is True
    assert ok2 is False
    assert "jadwal" in reason2
    print("OK: DLB dgn jadwal kurang dari sks ditolak sbg kandidat")


def test_day_overflow_splits_across_days_same_lecturer():
    """STEP: 'if lecturer schedule not enough OR day ran out, find another
    day to fit the rest of sks, must be same lecturer'"""
    periods = make_periods(2)  # cuma 2 periode per hari -> course sks=5 pasti overflow
    course = Course(
        id="C1", name="Course Panjang", capacity=10, sks_count=5, lecturer_count=1, is_lab=False,
        is_odd=True, is_active=True, is_interdiscipline=False, category_id="p1", specialization_ids=set(),
    )
    lecturer = Lecturer(
        id="FT1", name="Dosen", category_id="p1", is_active=True, is_interdiscipline=False, is_dlb=False,
    )
    rooms = [Room(id="R1", name="R1", capacity=20)]

    sessions = schedule_course(course, [lecturer], rooms, periods, cfg.DAY_ORDER)
    # 1 chunk (blok periode kontigu per hari) = 1 sesi/course_schedule.
    # Dengan 2 periode/hari, sks=5 kepecah jadi chunk 2+2+1 = 3 sesi,
    # dan total sks_count di semua sesi harus tetap 5.
    days_used = sorted({s.day for s in sessions})
    assert len(days_used) >= 3, f"dengan 2 periode/hari, sks=5 harus dipecah ke >=3 hari, dapat {days_used}"
    assert len(sessions) == len(days_used), (
        f"tiap hari harus jadi TEPAT 1 course_schedule (bukan 1 per periode), "
        f"dapat {len(sessions)} sesi utk {len(days_used)} hari"
    )
    assert sum(s.sks_count for s in sessions) == 5, (
        f"total sks_count di semua sesi harus 5, dapat {sum(s.sks_count for s in sessions)}"
    )
    lecturer_ids = {a.lecturer_id for s in sessions for a in s.lecturer_assignments}
    assert lecturer_ids == {"FT1"}, "harus dosen yg SAMA di semua hari"
    print(f"OK: course sks=5 dgn 2 periode/hari terpecah ke hari: {days_used}, dosen tetap sama")


def test_co_teaching_lecturer_count():
    """STEP: 'find suitable schedule, scale with lecturer count (extra
    lecturer can have conflicting schedules)'"""
    periods = make_periods(4)
    course = Course(
        id="C1", name="Co-teach", capacity=10, sks_count=2, lecturer_count=2, is_lab=False,
        is_odd=True, is_active=True, is_interdiscipline=False, category_id="p1", specialization_ids=set(),
    )
    l1 = Lecturer(id="FT1", name="A", category_id="p1", is_active=True, is_interdiscipline=False, is_dlb=False)
    l2 = Lecturer(id="FT2", name="B", category_id="p1", is_active=True, is_interdiscipline=False, is_dlb=False)
    rooms = [Room(id="R1", name="R1", capacity=20)]

    candidates = build_candidates(course, {"FT1": l1, "FT2": l2})
    sessions = schedule_course(course, candidates, rooms, periods, cfg.DAY_ORDER)
    # sks=2, 4 periode tersedia di hari yg sama -> harus jadi 1
    # course_schedule dengan sks_count=2 (bukan 2 course_schedule terpisah).
    assert len(sessions) == 1
    assert sessions[0].sks_count == 2
    for s in sessions:
        assert len(s.lecturer_assignments) == 2, "tiap sesi harus ada 2 dosen (lecturer_count=2)"
        roles = {a.role_index for a in s.lecturer_assignments}
        assert roles == {0, 1}
    print("OK: co-teaching menghasilkan 2 lecturer_assignments per sesi")


def test_lab_capacity_prioritized_over_room_capacity():
    """STEP: 'prioritize lab capacity over room capacity e.g lab capacity
    is not enough, split, even though the room capacity is enough'"""
    periods = make_periods(6)
    course = Course(
        id="C1", name="Lab Kecil", capacity=30, sks_count=3, lecturer_count=1, is_lab=True,
        is_odd=True, is_active=True, is_interdiscipline=False, category_id="p1",
        specialization_ids={"spec-1"},
    )
    lecturer = Lecturer(
        id="FT1", name="A", category_id="p1", is_active=True, is_interdiscipline=False,
        specialization_ids={"spec-1"}, is_dlb=False,
    )
    rooms = [
        Room(id="R1", name="Ruang Besar", capacity=40),  # ruang teori cukup utk 30 org
        Room(id="LAB1", name="Lab Kecil", capacity=15, lab_group_id="LG1", lab_specialization_ids={"spec-1"}),
    ]
    sessions = schedule_course(course, [lecturer], rooms, periods, cfg.DAY_ORDER)
    indices = {s.course_index for s in sessions}
    # kapasitas 30 vs ruang teori 40 -> harusnya cukup 1 split kalau lihat
    # ruang teori saja, TAPI lab cuma muat 15 -> harus split jadi 2 (30/15)
    assert len(indices) == 2, f"harus split jadi 2 karena kapasitas lab (15) < kapasitas course (30), dapat {indices}"
    print(f"OK: split mengikuti kapasitas lab (bukan ruang teori) -> {indices}")


if __name__ == "__main__":
    test_dlb_rejected_when_schedule_not_enough()
    test_day_overflow_splits_across_days_same_lecturer()
    test_co_teaching_lecturer_count()
    test_lab_capacity_prioritized_over_room_capacity()
    print("\nSemua edge-case test lolos.")
