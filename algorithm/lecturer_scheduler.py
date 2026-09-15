"""
Module 3 - lecturer_scheduler.py

Tugas modul ini: untuk tiap unit penjadwalan hasil module 5
(schedule_controller.plan_schedules), CARI DOSEN DULU (dari
suitable_lecturers, diurutkan dari priority_rate tertinggi), temukan slot
hari + jam yang masih kosong untuk dosen itu, BARU SETELAH ITU cari
ruangan/lab yang kosong di slot yang sama.

Modul ini dipakai untuk menghabiskan `priority_courses` (course yang
dosennya sudah punya hari tetap/komitmen) sampai selesai, SEBELUM
`non_priority_courses` mulai diproses module 4 (room_scheduler.py) --
supaya slot dosen yang sudah "terkunci" hari tetapnya tidak keburu
kepakai/bentrok oleh course lain yang sebenarnya masih fleksibel harinya.

Module 3 & module 4 berbagi `SchedulingState` yang sama (lihat
scheduling_common.py) supaya dosen atau ruangan yang sama tidak dipakai
bersamaan di slot yang sama, mau course-nya diproses lewat module 3
maupun module 4.
"""

import logging

from .scheduling_common import (
    WEEKDAYS,
    SchedulingState,
    lecturer_preferred_days,
    resolve_forced_lecturer_id,
    sort_lecturers_by_priority,
    sort_rooms_by_fit,
)

logger = logging.getLogger("lecturer_scheduler")


def _find_lecturer_slot(lecturer, schedules, state: "SchedulingState"):
    """
    Mencari slot (day, schedule) pertama yang masih kosong untuk dosen
    ini. Diutamakan hari-hari yang sudah jadi komitmen tetapnya; kalau
    semua slot di hari-hari itu penuh, baru dicoba hari lain (fallback)
    supaya dosen tetap dapat kebagian jadwal selama masih memungkinkan.
    """
    preferred_days = lecturer_preferred_days(lecturer)
    fallback_days = [day for day in WEEKDAYS if day not in preferred_days]

    for day in preferred_days + fallback_days:
        for schedule in schedules:
            if state.is_lecturer_free(lecturer.id, day, schedule.id):
                return day, schedule
    return None, None


def _find_room_slot(sorted_rooms_or_labs, day, schedule, state: "SchedulingState"):
    """Mencari ruangan/lab pertama (sudah terurut dari paling cocok) yang kosong di (day, schedule)."""
    for entry in sorted_rooms_or_labs:
        room = entry[0]
        if state.is_room_free(room.id, day, schedule.id):
            return room
    return None


def assign_lecturer_first(course_schedule_entry, schedules, state: "SchedulingState", forced_lecturer_id=None):
    """
    Inti module 3: untuk SATU unit penjadwalan (dict berisi course, index,
    isLab, suitable_lecturers, suitable_rooms_or_labs, paired_with,
    assignment -- lihat schedule_controller.py) --

      1. Cari dosen dulu (urut dari priority_rate tertinggi), lalu cari
         slot (day, schedule) yang masih kosong untuk dosen itu.
      2. Setelah dosen & slot didapat, baru cari ruangan/lab yang kosong
         di slot yang sama.

    `forced_lecturer_id` dipakai untuk entry yang "sepaket"
    (paired_with): pencarian dosen dipersempit ke dosen itu saja, supaya
    versi ruangan & versi lab dari course yang sama benar-benar diajar
    dosen yang sama.

    Return dict hasil assignment kalau berhasil, atau None kalau course
    ini gagal dijadwalkan (tidak ada kombinasi dosen+slot+ruangan yang
    kosong) -- entry yang gagal ini nantinya dilempar ke module
    berikutnya (re-split ruangan/lab, re-grouping dosen) untuk dicoba
    ulang.
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

    for lecturer, lecturer_priority in candidate_lecturers:
        day, schedule = _find_lecturer_slot(lecturer, schedules, state)
        if day is None:
            # Dosen ini sudah penuh di semua slot yang ada, coba kandidat berikutnya.
            continue

        room = _find_room_slot(sorted_rooms, day, schedule, state)
        if room is None:
            # Dosennya kosong, tapi tidak ada ruangan/lab kosong di slot itu.
            # Coba dosen lain (siapa tahu slotnya beda & ruangannya kosong).
            continue

        state.book(lecturer.id, room.id, day, schedule.id)

        return {
            "course": course,
            "index": index,
            "isLab": isLab,
            "lecturer": lecturer,
            "room": room,
            "day": day,
            "schedule": schedule,
        }

    return None


def schedule_priority_courses(priority_course_schedules, schedules, state: "SchedulingState" = None):
    """
    Memproses SELURUH priority_course_schedules (hasil module 5, sudah
    terurut dari jumlah dosen tersedia paling sedikit) sampai habis --
    inilah yang membuat priority_courses "dihabiskan" dulu sebelum
    non_priority_courses mulai diproses module 4.

    Entry yang "sepaket" (`paired_with` terisi -- versi ruangan & versi
    lab dari course+index yang sama) diproses berpasangan: begitu versi
    pertama dapat dosen, versi kedua dipaksa pakai dosen yang sama lewat
    `forced_lecturer_id`, dan keduanya ditandai lewat `entry["assignment"]`
    supaya module 4 tahu (dan tidak memproses ulang) kalau nanti ketemu
    salah satu entry ini lagi di non_priority_courses.

    Return (assigned, unscheduled, state):
    - assigned     : list hasil assignment yang berhasil (dict dengan
                      course, index, isLab, lecturer, room, day, schedule)
    - unscheduled  : list entry yang gagal dijadwalkan, untuk dilempar ke
                      module berikutnya (re-split/re-grouping)
    - state        : SchedulingState yang sudah berisi booking dari proses
                      ini, supaya bisa dilanjutkan module 4 tanpa
                      menabrak slot yang sudah dipakai di sini
    """
    if state is None:
        state = SchedulingState()

    assigned = []
    unscheduled = []

    for entry in priority_course_schedules:
        if entry.get("assignment") is not None:
            # Sudah diproses lebih dulu lewat pairing.
            continue

        forced_lecturer_id = resolve_forced_lecturer_id(entry)

        result = assign_lecturer_first(entry, schedules, state, forced_lecturer_id=forced_lecturer_id)
        if result is None:
            unscheduled.append(entry)
            logger.warning(
                "Gagal menjadwalkan course '%s' (index %s, isLab=%s): "
                "tidak ada kombinasi dosen+slot+ruangan yang kosong.",
                entry["course"].name, entry["index"], entry["isLab"],
            )
            continue

        entry["assignment"] = result
        assigned.append(result)

        paired_entry = entry.get("paired_with")
        if paired_entry is not None and paired_entry.get("assignment") is None:
            paired_result = assign_lecturer_first(
                paired_entry, schedules, state,
                forced_lecturer_id=result["lecturer"].id,
            )
            if paired_result is None:
                unscheduled.append(paired_entry)
                logger.warning(
                    "Gagal menjadwalkan pasangan lab/ruangan dari course '%s' "
                    "(index %s) dengan dosen yang sama (%s): tidak ada slot+ruangan kosong.",
                    paired_entry["course"].name, paired_entry["index"], result["lecturer"].name,
                )
            else:
                paired_entry["assignment"] = paired_result
                assigned.append(paired_result)

    logger.info(
        "Priority courses selesai diproses: %d berhasil dijadwalkan, %d gagal (menunggu module berikutnya).",
        len(assigned), len(unscheduled),
    )

    return assigned, unscheduled, state
