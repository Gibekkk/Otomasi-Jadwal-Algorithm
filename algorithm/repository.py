"""
Layer akses database. Semua query mysql/pymysql ada di sini, supaya modul
lain (matching/allocation/scheduler) murni logic Python dan gampang
ditest tanpa DB sungguhan.

Dipakai dengan koneksi pymysql yang SUDAH ADA (dibuat oleh app.py lewat
`get_connection()`), bukan bikin koneksi baru sendiri -- supaya satu
transaksi konsisten dengan flow /startGenerate yang sudah berjalan.
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Sequence

import pymysql

from .models import Course, Lecturer, PlannedSession, Period, Room


def to_bool(value) -> bool:
    """Konversi nilai kolom `bit(1)` dari MySQL ke bool Python yang benar.

    PENTING: pymysql (default) mengembalikan kolom BIT sebagai `bytes`
    mentah (mis. b'\\x00' / b'\\x01'), BUKAN int/bool. Kalau langsung
    dipakai `bool(value)`, hasilnya SELALU True karena `bytes` non-kosong
    selalu truthy di Python -- walaupun isinya b'\\x00'. Semua pembacaan
    kolom bit(1) di repository ini WAJIB lewat fungsi ini, jangan
    `bool(row[...])` langsung.
    """
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray)):
        return value != b"\x00"
    return bool(value)


def new_id() -> str:
    """Generate id baru. Backend Java (Spring/Hibernate) pada umumnya
    pakai UUID string untuk kolom id varchar(255), jadi dipakai format
    yang sama di sini. Kalau backend kamu pakai skema id lain, sesuaikan
    fungsi ini saja -- semua pemanggil pakai fungsi ini."""
    return str(uuid.uuid4())


class Repository:
    def __init__(self, conn: pymysql.connections.Connection):
        self.conn = conn

    # ------------------------------------------------------------------
    # READ
    # ------------------------------------------------------------------
    def get_timeline_generation(self, timeline_generation_id: str) -> dict:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, academic_year, is_odd FROM timeline_generations WHERE id = %s",
                (timeline_generation_id,),
            )
            row = cur.fetchone()
        if row is None:
            raise ValueError(f"timeline_generation_id tidak ditemukan: {timeline_generation_id}")
        row["is_odd"] = to_bool(row["is_odd"])
        return row

    def load_periods(self) -> List[Period]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT id, time_start, time_end FROM schedules ORDER BY time_start")
            rows = cur.fetchall()
        periods = []
        for i, row in enumerate(rows):
            periods.append(
                Period(
                    id=row["id"],
                    time_start=str(row["time_start"]),
                    time_end=str(row["time_end"]),
                    order=i,
                )
            )
        return periods

    def load_lecturers(self) -> Dict[str, Lecturer]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, category_id, is_active, is_interdiscipline "
                "FROM lecturers WHERE is_active = 1 AND deleted_at IS NULL"
            )
            lecturer_rows = cur.fetchall()

            cur.execute(
                "SELECT ls.lecturer_id, ls.specialization_id "
                "FROM lecturer_specializations ls "
                "JOIN specializations s ON s.id = ls.specialization_id "
                "WHERE s.deleted_at IS NULL"
            )
            spec_rows = cur.fetchall()

            cur.execute("SELECT lecturer_id, schedule_id FROM lecturer_schedules")
            schedule_rows = cur.fetchall()

        specs_by_lecturer: Dict[str, set] = {}
        for r in spec_rows:
            specs_by_lecturer.setdefault(r["lecturer_id"], set()).add(r["specialization_id"])

        schedules_by_lecturer: Dict[str, set] = {}
        for r in schedule_rows:
            schedules_by_lecturer.setdefault(r["lecturer_id"], set()).add(r["schedule_id"])

        lecturers: Dict[str, Lecturer] = {}
        for row in lecturer_rows:
            lid = row["id"]
            available = schedules_by_lecturer.get(lid, set())
            # STEP: "split dlbs (dlb is a lecturer that has schedule, the
            # ones that doesn't have schedule is full time)"
            is_dlb = lid in schedules_by_lecturer and len(available) > 0
            lecturers[lid] = Lecturer(
                id=lid,
                name=row["name"],
                category_id=row["category_id"],
                is_active=to_bool(row["is_active"]),
                is_interdiscipline=to_bool(row["is_interdiscipline"]),
                specialization_ids=specs_by_lecturer.get(lid, set()),
                available_period_ids=available,
                is_dlb=is_dlb,
            )
        return lecturers

    def load_rooms(self) -> List[Room]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT r.id, r.name, r.capacity, r.lab_group_id "
                "FROM rooms r "
                "LEFT JOIN lab_groups lg ON lg.id = r.lab_group_id AND lg.deleted_at IS NULL "
                "WHERE r.deleted_at IS NULL "
                "AND (r.lab_group_id IS NULL OR lg.id IS NOT NULL)"
            )
            room_rows = cur.fetchall()

            cur.execute(
                "SELECT ls.lab_group_id, ls.specialization_id "
                "FROM lab_specializations ls "
                "JOIN lab_groups lg ON lg.id = ls.lab_group_id AND lg.deleted_at IS NULL "
                "JOIN specializations s ON s.id = ls.specialization_id AND s.deleted_at IS NULL"
            )
            lab_spec_rows = cur.fetchall()

        specs_by_lab_group: Dict[str, set] = {}
        for r in lab_spec_rows:
            specs_by_lab_group.setdefault(r["lab_group_id"], set()).add(r["specialization_id"])

        rooms = []
        for row in room_rows:
            lab_group_id = row["lab_group_id"]
            rooms.append(
                Room(
                    id=row["id"],
                    name=row["name"],
                    capacity=row["capacity"],
                    lab_group_id=lab_group_id,
                    lab_specialization_ids=specs_by_lab_group.get(lab_group_id, set())
                    if lab_group_id
                    else set(),
                )
            )
        return rooms

    def load_courses(self, is_odd: bool) -> List[Course]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, capacity, sks_count, lecturer_count, is_lab, is_odd, "
                "is_active, is_interdiscipline, category_id "
                "FROM courses WHERE is_active = 1 AND is_odd = %s AND deleted_at IS NULL",
                (1 if is_odd else 0,),
            )
            course_rows = cur.fetchall()

            cur.execute(
                "SELECT cs.course_id, cs.specialization_id "
                "FROM course_specializations cs "
                "JOIN specializations s ON s.id = cs.specialization_id "
                "WHERE s.deleted_at IS NULL"
            )
            spec_rows = cur.fetchall()

        specs_by_course: Dict[str, set] = {}
        for r in spec_rows:
            specs_by_course.setdefault(r["course_id"], set()).add(r["specialization_id"])

        courses = []
        for row in course_rows:
            courses.append(
                Course(
                    id=row["id"],
                    name=row["name"],
                    capacity=row["capacity"],
                    sks_count=row["sks_count"],
                    lecturer_count=max(row["lecturer_count"], 1),
                    is_lab=to_bool(row["is_lab"]),
                    is_odd=to_bool(row["is_odd"]),
                    is_active=to_bool(row["is_active"]),
                    is_interdiscipline=to_bool(row["is_interdiscipline"]),
                    category_id=row["category_id"],
                    specialization_ids=specs_by_course.get(row["id"], set()),
                )
            )
        return courses

    # ------------------------------------------------------------------
    # WRITE
    # ------------------------------------------------------------------
    def clear_previous_generation(self, timeline_generation_id: str) -> None:
        """Hapus lecture_lecturers + lectures + course_schedules milik
        timeline_generation ini kalau sebelumnya sudah pernah generate
        (mis. retry). Urutan hapus WAJIB ikut arah FK (tidak ada ON DELETE
        CASCADE di skema): lecture_lecturers dulu (FK ke lectures), baru
        lectures, baru course_schedules yang sudah tidak dipakai lecture
        manapun."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, course_schedule_id FROM lectures WHERE timeline_generation_id = %s",
                (timeline_generation_id,),
            )
            old_rows = cur.fetchall()
            old_lecture_ids = [r["id"] for r in old_rows]
            old_course_schedule_ids = list({r["course_schedule_id"] for r in old_rows})

            if old_lecture_ids:
                placeholders = ",".join(["%s"] * len(old_lecture_ids))
                cur.execute(
                    f"DELETE FROM lecture_lecturers WHERE lecture_id IN ({placeholders})",
                    old_lecture_ids,
                )

            cur.execute("DELETE FROM lectures WHERE timeline_generation_id = %s", (timeline_generation_id,))

            if old_course_schedule_ids:
                placeholders = ",".join(["%s"] * len(old_course_schedule_ids))
                cur.execute(
                    f"DELETE FROM course_schedules WHERE id IN ({placeholders}) "
                    f"AND id NOT IN (SELECT DISTINCT course_schedule_id FROM lectures)",
                    old_course_schedule_ids,
                )

    def persist(self, timeline_generation_id: str, sessions: Sequence[PlannedSession]) -> dict:
        """Simpan semua PlannedSession jadi baris course_schedules + lectures
        + lecture_lecturers. Dipanggil di dalam transaksi yang sama dengan
        koneksi yang dipakai endpoint /startGenerate (caller yang
        commit/rollback).

        Skema baru: `lectures` TIDAK punya kolom lecturer_id lagi -- 1
        PlannedSession -> TEPAT 1 baris `lectures` (mewakili sesi kelas itu
        sendiri), dan tiap dosen yang mengajar di situ (utama + co-lecturer)
        jadi 1 baris `lecture_lecturers` yang menunjuk ke lectures row yang
        sama, ditandai `is_main_lecturer`. Assignment yang lecturer_id-nya
        None (tidak ketemu kandidat sama sekali) tidak punya dosen valid
        untuk dicatat, jadi tidak menghasilkan baris lecture_lecturers.

        `lectures.fallback_reason` diisi dari status dosen UTAMA
        (role_index=0) saja -- sesuai aturan hanya dosen utama yang wajib
        bebas-bentrok (co-lecturer boleh bentrok, lihat
        cfg.CHECK_CONFLICT_FOR_PRIMARY_ONLY), jadi cuma fallback dosen utama
        yang relevan dicatat di level sesi/lecture.
        """
        course_schedule_rows = []
        lecture_rows = []
        lecture_lecturer_rows = []

        for session in sessions:
            course_schedule_id = new_id()
            session_name = f"{session.course_name} {session.course_index}"
            course_schedule_rows.append(
                (
                    course_schedule_id,
                    session.course_index,
                    session.day,
                    session_name[:50],
                    session.course_id,
                    session.room_id,
                    session.period_id,
                    session.sks_count,
                    session.is_lab_block,
                )
            )

            lecture_id = new_id()
            primary_assignment = next(
                (a for a in session.lecturer_assignments if a.role_index == 0), None
            )
            lecture_fallback_reason = primary_assignment.fallback_reason if primary_assignment else None
            lecture_rows.append(
                (
                    lecture_id,
                    lecture_fallback_reason,
                    course_schedule_id,
                    timeline_generation_id,
                )
            )

            for assignment in session.lecturer_assignments:
                if assignment.lecturer_id is None:
                    continue
                lecture_lecturer_rows.append(
                    (
                        new_id(),
                        assignment.role_index == 0,
                        lecture_id,
                        assignment.lecturer_id,
                    )
                )

        with self.conn.cursor() as cur:
            if course_schedule_rows:
                cur.executemany(
                    "INSERT INTO course_schedules "
                    "(id, course_index, day, name, course_id, room_id, schedule_id, sks_count, is_lab) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    course_schedule_rows,
                )
            if lecture_rows:
                cur.executemany(
                    "INSERT INTO lectures "
                    "(id, fallback_reason, course_schedule_id, timeline_generation_id) "
                    "VALUES (%s, %s, %s, %s)",
                    lecture_rows,
                )
            if lecture_lecturer_rows:
                cur.executemany(
                    "INSERT INTO lecture_lecturers "
                    "(id, is_main_lecturer, lecture_id, lecturer_id) "
                    "VALUES (%s, %s, %s, %s)",
                    lecture_lecturer_rows,
                )

        return {
            "course_schedules_inserted": len(course_schedule_rows),
            "lectures_inserted": len(lecture_rows),
            "lecture_lecturers_inserted": len(lecture_lecturer_rows),
        }
