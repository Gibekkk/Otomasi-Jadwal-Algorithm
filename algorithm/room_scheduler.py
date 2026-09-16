"""
Module 4 - room_scheduler.py

Tugas modul ini: untuk tiap unit penjadwalan `non_priority_courses` hasil
module 5, CARI RUANGAN/LAB DAN BLOK JADWALNYA DULU (dari
suitable_rooms_or_labs, diurutkan dari yang paling cocok), BARU SETELAH
ITU cari dosen yang masih kosong di blok tsb -- kebalikan dari module 3
(lecturer_scheduler.py) yang mencari dosen dulu baru ruangan.

Modul ini memproses non_priority_courses SETELAH priority_courses selesai
dihabiskan module 3, berbagi objek `SchedulingState` yang sama.

Course yang "sepaket" (versi ruangan & versi lab dari course+index yang
sama) tetap wajib dosen sama walau salah satu versinya sudah diproses
module 3 -- ditangani lewat `resolve_forced_lecturer_id()`.

Catatan performa: pencarian di sini pada dasarnya
ruangan x hari x blok x dosen. Ketersediaan tiap dosen
(lecturer_availability) dihitung SEKALI di awal, bukan berulang di dalam
loop terdalam, dan blok jadwal dibangun sekali lewat build_day_blocks().
"""

import logging

from .scheduling_common import (
    WEEKDAYS,
    SchedulingState,
    build_assignment,
    build_day_blocks,
    lecturer_allows_block,
    lecturer_availability,
    resolve_forced_lecturer_id,
    session_duration,
    sort_lecturers_by_priority,
    sort_rooms_by_fit,
    sort_schedules,
)
from .scheduling_pairing import schedule_entries

logger = logging.getLogger("room_scheduler")


def _find_room_and_lecturer(sorted_rooms_or_labs, candidate_lecturers, blocks, state: "SchedulingState"):
    """
    Cari kombinasi (room, lecturer, day, block) pertama yang valid:
    ruangan/lab dicoba dari yang paling cocok dulu, tiap ruangan dicoba di
    semua hari x blok sampai ketemu blok yang seluruh periodenya kosong;
    begitu ketemu, baru dicari dosen kandidat yang juga kosong di blok itu
    dan blok itu masuk jam ketersediaannya.

    `candidate_lecturers` di sini sudah berbentuk list of
    (lecturer, availability) -- availability dihitung sekali oleh pemanggil.
    """
    for room_entry in sorted_rooms_or_labs:
        room = room_entry[0]
        for day in WEEKDAYS:
            for block in blocks:
                if not state.is_room_free_block(room.id, day, block):
                    continue
                for lecturer, availability in candidate_lecturers:
                    if not lecturer_allows_block(availability, day, block):
                        continue
                    if state.is_lecturer_free_block(lecturer.id, day, block):
                        return room, lecturer, day, block
    return None, None, None, None


def assign_room_first(course_schedule_entry, schedules, state: "SchedulingState", forced_lecturer_id=None):
    """
    Inti module 4, untuk SATU unit penjadwalan:

      1. Cari ruangan/lab dulu (urut dari paling cocok), lalu blok
         (day, [schedule...]) yang seluruh periodenya masih kosong.
      2. Setelah ruangan & blok didapat, baru cari dosen kandidat yang
         juga kosong di blok yang sama.

    Return dict hasil assignment, atau None kalau gagal.
    """
    course = course_schedule_entry["course"]
    index = course_schedule_entry["index"]
    isLab = course_schedule_entry["isLab"]
    suitable_lecturers = course_schedule_entry["suitable_lecturers"]
    suitable_rooms_or_labs = course_schedule_entry["suitable_rooms_or_labs"]

    ranked_lecturers = sort_lecturers_by_priority(suitable_lecturers)
    if forced_lecturer_id is not None:
        ranked_lecturers = [
            item for item in ranked_lecturers if item[0].id == forced_lecturer_id
        ]
        if not ranked_lecturers:
            logger.warning(
                "Dosen pasangan (id=%s) untuk course '%s' (index %s) tidak "
                "ada di daftar suitable_lecturers versi ini.",
                forced_lecturer_id, course.name, index,
            )

    # Hitung ketersediaan tiap dosen SEKALI di sini, bukan di dalam loop
    # terdalam _find_room_and_lecturer (yang bisa dieksekusi
    # ruangan x hari x blok kali).
    candidate_lecturers = [
        (lecturer, lecturer_availability(lecturer)) for lecturer, _priority in ranked_lecturers
    ]

    sorted_rooms = sort_rooms_by_fit(suitable_rooms_or_labs, isLab)
    duration = session_duration(course, isLab)
    blocks = build_day_blocks(sort_schedules(schedules), duration)
    if not blocks:
        logger.warning(
            "Course '%s' (index %s) butuh %d periode berurutan, tapi hanya ada %d periode.",
            course.name, index, duration, len(schedules),
        )
        return None

    room, lecturer, day, block = _find_room_and_lecturer(
        sorted_rooms, candidate_lecturers, blocks, state
    )
    if room is None:
        return None

    state.book_block(lecturer.id, room.id, day, block)
    return build_assignment(course_schedule_entry, lecturer, room, day, block)


def schedule_non_priority_courses(non_priority_course_schedules, schedules, state: "SchedulingState" = None):
    """
    Memproses non_priority_course_schedules setelah priority_courses
    dihabiskan module 3. `state` idealnya state lanjutan dari module 3
    supaya slot yang sudah dipakai tidak ditabrak.

    Entry yang sudah punya `entry["assignment"]` (sudah diproses lewat
    pairing dari module 3) dilewati -- tidak diproses ulang dan tidak
    dihitung dobel.

    Return (assigned, unscheduled, state).
    """
    if state is None:
        state = SchedulingState()

    return schedule_entries(
        non_priority_course_schedules,
        schedules,
        state,
        assign_fn=assign_room_first,
        resolve_forced_lecturer_id=resolve_forced_lecturer_id,
        failure_message=(
            "Gagal menjadwalkan course '%s' (index %s, isLab=%s): "
            "tidak ada kombinasi ruangan+slot+dosen yang kosong."
        ),
        logger_obj=logger,
        label="Non-priority courses",
    )
