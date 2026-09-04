"""
Entry point algoritma generate jadwal.
=========================================
Panggil `generate_timeline(conn, timeline_generation_id)` dari app.py
(lihat `example_integration.py` untuk contoh pemakaian di /startGenerate).

Urutan sesuai flow yang diminta:
  1. get lecturers, split DLB vs full time     -> repository.load_lecturers
  2. get course per semester                   -> repository.load_courses
  3. match course ke kandidat dosen             -> matching.build_candidates
  4. order kandidat: DLB dulu, ascending jml jadwal -> matching.build_candidates
  5. cari jadwal, scale dgn lecturer_count       -> scheduler.schedule_one_split
  6. cari ruang sesuai kapasitas                 -> allocation.find_room_for_run
  7. auto-scale ruang utk split kalau over kapasitas -> scheduler._compute_splits
  8. kalau lab: cari lab (6-7 strategy)           -> scheduler._allocate_lab
  9. kalau jadwal/hari habis: lanjut hari lain, dosen sama -> scheduler._allocate_theory
  10. gagal cari dosen -> fallback_reason          -> scheduler.schedule_one_split
  11. blokir jam istirahat (semua ruang) & Jumat jam sholat (dosen
      laki-laki + Islam), lalu cegah 1 kohort (major+semester, kecuali
      submajor beda) dijadwalkan bentrok -> _apply_global_schedule_blocks,
      models.CohortTracker
"""

from __future__ import annotations

import logging
from typing import Dict, List, Sequence

import pymysql

from . import config as cfg
from .matching import build_candidates, theory_and_lab_slots
from .models import CohortTracker, GenerationStats, Lecturer, PlannedSession, Period, Room
from .repository import Repository
from .scheduler import schedule_course

logger = logging.getLogger("algorithm.generator")


def _time_to_minutes(t: str) -> int:
    """Parse 'H:MM:SS' / 'HH:MM:SS' jadi menit-sejak-tengah-malam. Pakai
    split manual (bukan strptime) supaya tetap benar walau formatnya
    tidak selalu 2-digit (mis. pymysql kadang balikin kolom TIME sebagai
    representasi tanpa leading zero)."""
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _periods_overlapping(periods: Sequence[Period], start: str, end: str) -> List[Period]:
    """Semua Period yang IRISAN waktunya (bukan exact-match) kena rentang
    [start, end)."""
    start_m, end_m = _time_to_minutes(start), _time_to_minutes(end)
    return [
        p for p in periods
        if _time_to_minutes(p.time_start) < end_m and _time_to_minutes(p.time_end) > start_m
    ]


def _apply_global_schedule_blocks(
    periods: Sequence[Period], lecturers: Dict[str, Lecturer], rooms: Sequence[Room]
) -> None:
    """Pre-book slot yang MEMANG tidak boleh dipakai sama sekali, SEBELUM
    proses generate course dimulai -- supaya semua jalur alokasi (normal
    MAUPUN force-placement) otomatis menghindarinya lewat mekanisme
    booked/is_free yang sudah ada, tanpa perlu logic khusus tambahan di
    scheduler/allocation.

    - Jam istirahat (cfg.LUNCH_BREAK_START/END): di-block di level RUANG
      (semua ruang, semua hari) -- supaya force-placement (yang tidak
      cek dosen sama sekali, cuma ruang) tetap ikut menghindarinya.
    - Jumat jam sholat (cfg.FRIDAY_PRAYER_BLOCK_*): di-block KHUSUS di
      level DOSEN laki-laki + beragama sesuai cfg (bukan ruang), karena
      ini larangan personal per-dosen -- dosen lain tetap boleh pakai
      ruang/jam yang sama. Hanya berlaku ke dosen UTAMA (co-lecturer
      memang tidak pernah dicek bentrok jadwal sama sekali).
    """
    lunch_periods = _periods_overlapping(periods, cfg.LUNCH_BREAK_START, cfg.LUNCH_BREAK_END)
    if lunch_periods:
        for room in rooms:
            for day in cfg.DAY_ORDER:
                room.booked.setdefault(day, set()).update(p.id for p in lunch_periods)

    friday_periods = _periods_overlapping(
        periods, cfg.FRIDAY_PRAYER_BLOCK_START, cfg.FRIDAY_PRAYER_BLOCK_END
    )
    if friday_periods:
        blocked_lecturer_count = 0
        for lecturer in lecturers.values():
            if lecturer.is_male and lecturer.religion == cfg.FRIDAY_PRAYER_BLOCK_RELIGION:
                lecturer.booked.setdefault(cfg.FRIDAY_PRAYER_BLOCK_DAY, set()).update(
                    p.id for p in friday_periods
                )
                blocked_lecturer_count += 1
        logger.info(
            "Blokir jadwal Jumat %s-%s untuk %d dosen (laki-laki + %s)",
            cfg.FRIDAY_PRAYER_BLOCK_START,
            cfg.FRIDAY_PRAYER_BLOCK_END,
            blocked_lecturer_count,
            cfg.FRIDAY_PRAYER_BLOCK_RELIGION,
        )


class GenerationResult:
    def __init__(self, sessions: List[PlannedSession], stats: GenerationStats, persisted: dict | None = None):
        self.sessions = sessions
        self.stats = stats
        self.persisted = persisted or {}

    def as_dict(self) -> dict:
        return {"stats": self.stats.as_dict(), "persisted": self.persisted}


def order_courses(courses):
    def key(c):
        return (
            0 if (cfg.PRIORITIZE_LAB_COURSES_FIRST and c.is_lab) else 1,
            -c.sks_count if cfg.SORT_COURSES_BY_SKS_DESC else 0,
            c.id,
        )

    return sorted(courses, key=key)


def generate_timeline(
    conn: pymysql.connections.Connection,
    timeline_generation_id: str,
    commit: bool = True,
    replace_existing: bool = True,
) -> GenerationResult:
    """Jalankan seluruh algoritma untuk 1 timeline_generation dan (opsional)
    langsung simpan ke DB (course_schedules + lectures).

    - `commit=False` -> hanya hitung & kembalikan hasil di memori (dry-run),
      TIDAK menulis apa pun ke DB. Berguna untuk debug/preview.
    - `replace_existing=True` -> hapus lectures/course_schedules lama milik
      timeline_generation_id ini dulu sebelum insert baru (supaya generate
      ulang tidak numpuk data lama).
    """
    repo = Repository(conn)

    tg = repo.get_timeline_generation(timeline_generation_id)
    is_odd = tg["is_odd"]
    logger.info(
        "Mulai generate: timeline_generation_id=%s academic_year=%s is_odd=%s",
        timeline_generation_id,
        tg["academic_year"],
        is_odd,
    )

    lecturers = repo.load_lecturers()
    periods = repo.load_periods()
    rooms = repo.load_rooms()
    courses = repo.load_courses(is_odd=is_odd)
    prodi_category_ids = repo.load_prodi_category_ids()

    logger.info(
        "Data dimuat: %d dosen (%d DLB), %d ruang, %d periode, %d course, %d category prodi",
        len(lecturers),
        sum(1 for l in lecturers.values() if l.is_dlb),
        len(rooms),
        len(periods),
        len(courses),
        len(prodi_category_ids),
    )

    if not periods:
        raise ValueError("Tabel `schedules` kosong -- tidak ada periode waktu untuk dijadwalkan")

    _apply_global_schedule_blocks(periods, lecturers, rooms)

    cohort_tracker = CohortTracker(prodi_category_ids=prodi_category_ids) if cfg.ENFORCE_COHORT_CONFLICT else None

    stats = GenerationStats(total_courses=len(courses))
    all_sessions: List[PlannedSession] = []

    for course in order_courses(courses):
        candidates = build_candidates(course, lecturers)
        if not candidates:
            stats.issues.append(f"course '{course.name}' ({course.id}): tidak ada kandidat dosen sama sekali")

        sessions = schedule_course(course, candidates, rooms, periods, cfg.DAY_ORDER, cohort_tracker=cohort_tracker)
        all_sessions.extend(sessions)

        # --- stats per course (ringkasan, bukan per row) ---
        splits_seen = {s.course_index for s in sessions}
        for split in splits_seen:
            split_sessions = [s for s in sessions if s.course_index == split]
            has_fallback = any(
                a.fallback_reason for s in split_sessions for a in s.lecturer_assignments
            )
            if has_fallback:
                stats.partial_splits += 1
                stats.lecturer_fallback_count += sum(
                    1
                    for s in split_sessions
                    for a in s.lecturer_assignments
                    if a.fallback_reason
                )
            else:
                stats.fully_scheduled_splits += 1

        if course.is_lab:
            lab_indices_expected = {s.course_index for s in sessions}
            lab_sessions_present = {s.course_index for s in sessions if s.is_lab_block}
            missing = lab_indices_expected - lab_sessions_present
            for m in missing:
                stats.splits_without_room += 1
                stats.issues.append(
                    f"course '{course.name}' ({course.id}) split {m}: blok lab tidak dapat ruang sama sekali"
                )

        # --- catat split yang porsi teorinya tidak lengkap (sebagian
        # periode tidak dapat slot ruang sama sekali, termasuk lewat
        # force-placement) -- ini catatan level-course, TIDAK dipakai
        # sebagai fallback_reason per lecture (yang sudah benar hanya
        # nempel di porsi yang memang tidak dapat dosen ter-verifikasi). ---
        theory_needed, _lab_needed = theory_and_lab_slots(course)
        if theory_needed > 0:
            for split in splits_seen:
                theory_count = sum(
                    1 for s in sessions if s.course_index == split and not s.is_lab_block
                )
                if theory_count < theory_needed:
                    stats.issues.append(
                        f"course '{course.name}' ({course.id}) split {split}: sesi teori tidak lengkap "
                        f"({theory_count}/{theory_needed} periode dapat ruang)"
                    )

    stats.total_sessions = len(all_sessions)

    persisted = {}
    if commit:
        if replace_existing:
            repo.clear_previous_generation(timeline_generation_id)
        persisted = repo.persist(timeline_generation_id, all_sessions)
        logger.info(
            "Generate selesai & disimpan: %d course_schedules, %d lectures, %d lecture_lecturers",
            persisted.get("course_schedules_inserted", 0),
            persisted.get("lectures_inserted", 0),
            persisted.get("lecture_lecturers_inserted", 0),
        )
    else:
        logger.info("Dry-run (commit=False): %d session dihitung, tidak ditulis ke DB", len(all_sessions))

    return GenerationResult(all_sessions, stats, persisted)
