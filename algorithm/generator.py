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
"""

from __future__ import annotations

import logging
from typing import List

import pymysql

from . import config as cfg
from .matching import build_candidates, theory_and_lab_slots
from .models import GenerationStats, PlannedSession
from .repository import Repository
from .scheduler import schedule_course

logger = logging.getLogger("algorithm.generator")


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
        "Starting generation: timeline_generation_id=%s academic_year=%s is_odd=%s",
        timeline_generation_id,
        tg["academic_year"],
        is_odd,
    )

    lecturers = repo.load_lecturers()
    periods = repo.load_periods()
    rooms = repo.load_rooms()
    courses = repo.load_courses(is_odd=is_odd)

    logger.info(
        "Data loaded: %d lecturers (%d DLB), %d rooms, %d periods, %d courses",
        len(lecturers),
        sum(1 for l in lecturers.values() if l.is_dlb),
        len(rooms),
        len(periods),
        len(courses),
    )

    if not periods:
        raise ValueError("`schedules` table is empty -- no time periods available to schedule")

    stats = GenerationStats(total_courses=len(courses))
    all_sessions: List[PlannedSession] = []

    for course in order_courses(courses):
        candidates = build_candidates(course, lecturers)
        if not candidates:
            stats.issues.append(f"course '{course.name}' ({course.id}): no lecturer candidates at all")

        sessions = schedule_course(course, candidates, rooms, periods, cfg.DAY_ORDER)
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
                    f"course '{course.name}' ({course.id}) split {m}: lab block could not get a room at all"
                )

        # --- catat split yang porsi teorinya tidak lengkap (sebagian
        # periode tidak dapat slot ruang sama sekali, termasuk lewat
        # force-placement) -- ini catatan level-course, TIDAK dipakai
        # sebagai fallback_reason per lecture (yang sudah benar hanya
        # nempel di porsi yang memang tidak dapat dosen ter-verifikasi). ---
        theory_needed, _lab_needed = theory_and_lab_slots(course)
        if theory_needed > 0:
            for split in splits_seen:
                # NOTE: sejak 1 chunk (blok periode kontigu) = 1
                # PlannedSession, jumlah periode teori yang benar2 dapat
                # slot dihitung dari SUM `sks_count` tiap sesi teori
                # (bukan jumlah sesi teori itu sendiri, karena 1 sesi
                # sekarang bisa mewakili beberapa periode sekaligus).
                theory_count = sum(
                    s.sks_count for s in sessions if s.course_index == split and not s.is_lab_block
                )
                if theory_count < theory_needed:
                    stats.issues.append(
                        f"course '{course.name}' ({course.id}) split {split}: theory session incomplete "
                        f"({theory_count}/{theory_needed} periods got a room)"
                    )

    stats.total_sessions = len(all_sessions)

    persisted = {}
    if commit:
        if replace_existing:
            repo.clear_previous_generation(timeline_generation_id)
        persisted = repo.persist(timeline_generation_id, all_sessions)
        logger.info(
            "Generation finished & saved: %d course_schedules, %d lectures, %d lecture_lecturers",
            persisted.get("course_schedules_inserted", 0),
            persisted.get("lectures_inserted", 0),
            persisted.get("lecture_lecturers_inserted", 0),
        )
    else:
        logger.info("Dry-run (commit=False): %d sessions computed, nothing written to DB", len(all_sessions))

    return GenerationResult(all_sessions, stats, persisted)
