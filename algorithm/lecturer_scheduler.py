"""
Module 3 - lecturer_scheduler.py

Tugas modul ini: untuk tiap unit penjadwalan hasil module 5
(schedule_controller.plan_schedules), CARI DOSEN DULU (dari
suitable_lecturers, diurutkan dari priority_rate tertinggi), temukan BLOK
hari + jam yang masih kosong untuk dosen itu, BARU SETELAH ITU cari
ruangan/lab yang kosong di blok yang sama.

Modul ini dipakai untuk menghabiskan `priority_courses` (course yang
dosennya sudah punya hari tetap/komitmen) sampai selesai, SEBELUM
`non_priority_courses` mulai diproses module 4 (room_scheduler.py) --
supaya slot dosen yang sudah "terkunci" hari tetapnya tidak keburu
kepakai/bentrok oleh course lain yang sebenarnya masih fleksibel harinya.

Module 3 & module 4 berbagi `SchedulingState` yang sama (lihat
scheduling_common.py) supaya dosen atau ruangan yang sama tidak dipakai
bersamaan di slot yang sama.

Satu sesi menempati BLOK periode berurutan sepanjang sksCount (lihat
scheduling_common.session_duration), bukan satu periode saja.
"""

import logging

from .scheduling_common import (
    WEEKDAYS,
    SchedulingState,
    build_assignment,
    build_day_blocks,
    lecturer_allows_block,
    lecturer_availability,
    lecturer_preferred_days,
    resolve_forced_lecturer_id,
    session_duration,
    sort_lecturers_by_priority,
    sort_rooms_by_fit,
    sort_schedules,
)
from .scheduling_pairing import schedule_entries

logger = logging.getLogger("lecturer_scheduler")


def _candidate_days(lecturer):
    """
    Hari yang dicoba untuk dosen ini: hari komitmen tetapnya dulu, baru
    hari lain sebagai fallback supaya dosen tetap kebagian jadwal selama
    masih memungkinkan.
    """
    preferred_days = lecturer_preferred_days(lecturer)
    fallback_days = [day for day in WEEKDAYS if day not in preferred_days]
    return preferred_days + fallback_days


def _find_room_for_block(sorted_rooms_or_labs, day, block, state: "SchedulingState"):
    """Ruangan/lab pertama (sudah terurut dari paling cocok) yang kosong di SELURUH blok."""
    for room_entry in sorted_rooms_or_labs:
        room = room_entry[0]
        if state.is_room_free_block(room.id, day, block):
            return room
    return None


def assign_lecturer_first(course_schedule_entry, schedules, state: "SchedulingState", forced_lecturer_id=None):
    """
    Inti module 3, untuk SATU unit penjadwalan:

      1. Cari dosen dulu (urut dari priority_rate tertinggi), lalu cari
         BLOK (day, [schedule...]) yang masih kosong untuk dosen itu DAN
         masuk jam ketersediaannya (lecturer_schedules_time).
      2. Setelah dosen & blok didapat, baru cari ruangan/lab yang kosong
         di seluruh blok yang sama.

    `forced_lecturer_id` dipakai untuk entry yang "sepaket" (paired_with):
    pencarian dosen dipersempit ke dosen itu saja, supaya versi ruangan &
    versi lab dari course yang sama benar-benar diajar dosen yang sama.

    Return dict hasil assignment, atau None kalau gagal.
    """
    course = course_schedule_entry["course"]
    index = course_schedule_entry["index"]
    isLab = course_schedule_entry["isLab"]
    suitable_lecturers = course_schedule_entry["suitable_lecturers"]
    suitable_rooms_or_labs = course_schedule_entry["suitable_rooms_or_labs"]

    candidate_lecturers = sort_lecturers_by_priority(suitable_lecturers)
    if forced_lecturer_id is not None:
        candidate_lecturers = [
            item for item in candidate_lecturers if item[0].id == forced_lecturer_id
        ]
        if not candidate_lecturers:
            logger.warning(
                "Dosen pasangan (id=%s) untuk course '%s' (index %s) tidak "
                "ada di daftar suitable_lecturers versi ini.",
                forced_lecturer_id, course.name, index,
            )

    sorted_rooms = sort_rooms_by_fit(suitable_rooms_or_labs, isLab)
    duration = session_duration(course, isLab)
    blocks = build_day_blocks(sort_schedules(schedules), duration)
    if not blocks:
        logger.warning(
            "Course '%s' (index %s) butuh %d periode berurutan, tapi hanya ada %d periode.",
            course.name, index, duration, len(schedules),
        )
        return None

    for lecturer, _priority in candidate_lecturers:
        availability = lecturer_availability(lecturer)
        for day in _candidate_days(lecturer):
            for block in blocks:
                if not lecturer_allows_block(availability, day, block):
                    continue
                if not state.is_lecturer_free_block(lecturer.id, day, block):
                    continue
                room = _find_room_for_block(sorted_rooms, day, block, state)
                if room is None:
                    continue
                state.book_block(lecturer.id, room.id, day, block)
                return build_assignment(course_schedule_entry, lecturer, room, day, block)

    return None


def schedule_priority_courses(priority_course_schedules, schedules, state: "SchedulingState" = None):
    """
    Memproses SELURUH priority_course_schedules (hasil module 5, sudah
    terurut dari jumlah dosen tersedia paling sedikit) sampai habis.

    Entry yang "sepaket" (`paired_with`) diproses berpasangan: begitu versi
    pertama dapat dosen, versi kedua dipaksa pakai dosen yang sama.

    Return (assigned, unscheduled, state).
    """
    if state is None:
        state = SchedulingState()

    return schedule_entries(
        priority_course_schedules,
        schedules,
        state,
        assign_fn=assign_lecturer_first,
        resolve_forced_lecturer_id=resolve_forced_lecturer_id,
        failure_message=(
            "Gagal menjadwalkan course '%s' (index %s, isLab=%s): "
            "tidak ada kombinasi dosen+slot+ruangan yang kosong."
        ),
        logger_obj=logger,
        label="Priority courses",
    )
