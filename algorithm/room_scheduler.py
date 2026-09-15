"""
Module 4 - room_scheduler.py

Tugas modul ini: untuk tiap unit penjadwalan `non_priority_courses` hasil
module 5, CARI RUANGAN/LAB DAN JADWALNYA DULU (dari suitable_rooms_or_labs,
diurutkan dari yang paling cocok), BARU SETELAH ITU cari dosen yang tepat
yang masih kosong di slot ruangan tsb -- kebalikan dari module 3
(lecturer_scheduler.py) yang mencari dosen dulu baru ruangan.

Modul ini dipakai untuk memproses non_priority_courses, SETELAH
priority_courses selesai dihabiskan module 3. Module 3 & module 4 berbagi
objek `SchedulingState` yang sama (lihat scheduling_common.py) supaya
dosen atau ruangan yang sama tidak dipakai bersamaan di slot yang sama,
baik antar course yang diproses module 3 maupun module 4.

Course yang "sepaket" (versi ruangan & versi lab dari course+index yang
sama, field `paired_with`) tetap wajib dosen sama, walau salah satu
versinya kebetulan sudah diproses lebih dulu oleh module 3 (mis. karena
versi ruangannya masuk priority_courses sementara versi labnya masuk
non_priority_courses) -- ditangani lewat `resolve_forced_lecturer_id()`
dari scheduling_common.py, yang mengecek `entry["assignment"]` pasangannya
tanpa peduli itu diisi oleh module 3 atau module 4.
"""

import logging

from .scheduling_common import (
    WEEKDAYS,
    SchedulingState,
    resolve_forced_lecturer_id,
    sort_lecturers_by_priority,
    sort_rooms_by_fit,
)

logger = logging.getLogger("room_scheduler")


def _find_room_and_lecturer(sorted_rooms_or_labs, candidate_lecturers, schedules, state: "SchedulingState"):
    """
    Mencari kombinasi (room, lecturer, day, schedule) pertama yang valid:
    ruangan/lab dicoba dari yang paling cocok dulu (sorted_rooms_or_labs
    sudah terurut). Untuk tiap ruangan, dicoba semua slot (hari x jam)
    sampai ketemu yang kosong; begitu slot ruangan kosong ditemukan, baru
    dicari dosen kandidat yang juga masih kosong di slot yang sama.
    """
    for room_entry in sorted_rooms_or_labs:
        room = room_entry[0]
        for day in WEEKDAYS:
            for schedule in schedules:
                if not state.is_room_free(room.id, day, schedule.id):
                    continue
                for lecturer, lecturer_priority in candidate_lecturers:
                    if state.is_lecturer_free(lecturer.id, day, schedule.id):
                        return room, lecturer, day, schedule
    return None, None, None, None


def assign_room_first(course_schedule_entry, schedules, state: "SchedulingState", forced_lecturer_id=None):
    """
    Inti module 4: untuk SATU unit penjadwalan (dict berisi course, index,
    isLab, suitable_lecturers, suitable_rooms_or_labs, paired_with,
    assignment -- lihat schedule_controller.py) --

      1. Cari ruangan/lab dulu (urut dari priority_rate paling cocok),
         lalu untuk ruangan itu cari slot (day, schedule) yang masih
         kosong.
      2. Setelah ruangan & slot didapat, baru cari dosen kandidat yang
         juga masih kosong di slot yang sama.

    `forced_lecturer_id` dipakai untuk entry yang "sepaket" (paired_with)
    supaya versi ruangan & versi lab dari course yang sama benar-benar
    diajar dosen yang sama.

    Return dict hasil assignment kalau berhasil, atau None kalau course
    ini gagal dijadwalkan (tidak ada kombinasi ruangan+slot+dosen yang
    kosong).
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

    room, lecturer, day, schedule = _find_room_and_lecturer(
        sorted_rooms, candidate_lecturers, schedules, state
    )
    if room is None:
        return None

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


def schedule_non_priority_courses(non_priority_course_schedules, schedules, state: "SchedulingState" = None):
    """
    Memproses non_priority_course_schedules (hasil module 5, setelah
    priority_courses dihabiskan module 3). `state` idealnya adalah state
    yang sama/lanjutan dari module 3 (dioper langsung dari return
    schedule_priority_courses), supaya slot yang sudah dipakai
    priority_courses tidak ditabrak di sini.

    Entry yang sudah punya `entry["assignment"]` terisi (artinya sudah
    diproses lebih dulu lewat pairing dari module 3) dilewati -- tidak
    diproses ulang, dan tidak dimasukkan ke `assigned` di sini supaya
    tidak dobel dihitung dengan hasil module 3.

    Return (assigned, unscheduled, state) -- format sama dengan module 3
    (lecturer_scheduler.schedule_priority_courses).
    """
    if state is None:
        state = SchedulingState()

    assigned = []
    unscheduled = []

    for entry in non_priority_course_schedules:
        if entry.get("assignment") is not None:
            # Sudah diproses lebih dulu lewat pairing (mis. dari module 3).
            continue

        forced_lecturer_id = resolve_forced_lecturer_id(entry)

        result = assign_room_first(entry, schedules, state, forced_lecturer_id=forced_lecturer_id)
        if result is None:
            unscheduled.append(entry)
            logger.warning(
                "Gagal menjadwalkan course '%s' (index %s, isLab=%s): "
                "tidak ada kombinasi ruangan+slot+dosen yang kosong.",
                entry["course"].name, entry["index"], entry["isLab"],
            )
            continue

        entry["assignment"] = result
        assigned.append(result)

        paired_entry = entry.get("paired_with")
        if paired_entry is not None and paired_entry.get("assignment") is None:
            paired_result = assign_room_first(
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
        "Non-priority courses selesai diproses: %d berhasil dijadwalkan, %d gagal.",
        len(assigned), len(unscheduled),
    )

    return assigned, unscheduled, state
