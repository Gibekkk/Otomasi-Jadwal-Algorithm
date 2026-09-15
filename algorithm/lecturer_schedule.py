"""
Module 3 - lecturer_scheduler.py

Tugas modul ini: untuk tiap unit penjadwalan hasil module 5
(schedule_controller.plan_schedules), CARI DOSEN DULU (dari
suitable_lecturers, diurutkan dari priority_rate tertinggi), temukan slot
hari + jam yang masih kosong untuk dosen itu, BARU SETELAH ITU cari
ruangan/lab yang kosong di slot yang sama.

Modul ini dipakai untuk menghabiskan `priority_courses` (course yang
dosennya sudah punya hari tetap/komitmen) sampai selesai, SEBELUM
`non_priority_courses` mulai diproses -- supaya slot dosen yang sudah
"terkunci" hari tetapnya tidak keburu kepakai/bentrok oleh course lain
yang sebenarnya masih fleksibel harinya.

Asumsi tentang model data (karena belum ada tabel "course schedule"
final di project ini):
- Satu SLOT penjadwalan = kombinasi (hari, Schedule). `Schedule` (lihat
  models/schedule.py) hanya berisi jam (timeStart/timeEnd), tidak ada
  kolom hari -- jadi harinya diambil dari enum hari yang sama dengan
  LecturerSchedule.day ('MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY',
  'FRIDAY').
- `lecturer.lecturerSchedules` dianggap sebagai hari-hari yang SUDAH jadi
  komitmen tetap dosen tsb (makanya course ini masuk priority_courses).
  Kalau dosen belum punya komitmen hari sama sekali, semua hari kerja
  dianggap terbuka untuknya.
"""

import logging
from collections import defaultdict

logger = logging.getLogger("lecturer_scheduler")

# Sesuai enum day_enum pada model LecturerSchedule (algorithm/models/lecturer.py)
WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]


class SchedulingState:
    """
    Menyimpan slot (day, schedule_id) yang sudah terpakai selama proses
    penjadwalan berjalan, supaya dosen & ruangan yang sama tidak
    di-double-book di slot yang sama.

    Sengaja dipisah jadi objek tersendiri (bukan variabel lokal di dalam
    satu fungsi) supaya bisa dioper terus ke module berikutnya (mis.
    module 4 untuk non_priority_courses) tanpa kehilangan histori booking
    yang sudah dibuat di sini.
    """

    def __init__(self):
        self.lecturer_bookings = defaultdict(set)  # lecturer_id -> {(day, schedule_id)}
        self.room_bookings = defaultdict(set)       # room_id -> {(day, schedule_id)}

    def is_lecturer_free(self, lecturer_id, day, schedule_id) -> bool:
        return (day, schedule_id) not in self.lecturer_bookings[lecturer_id]

    def is_room_free(self, room_id, day, schedule_id) -> bool:
        return (day, schedule_id) not in self.room_bookings[room_id]

    def book(self, lecturer_id, room_id, day, schedule_id):
        self.lecturer_bookings[lecturer_id].add((day, schedule_id))
        self.room_bookings[room_id].add((day, schedule_id))


def _lecturer_preferred_days(lecturer):
    """
    Hari-hari yang sudah jadi komitmen tetap dosen (dari
    lecturer.lecturerSchedules). Kalau dosen belum punya komitmen hari
    sama sekali, semua hari kerja dianggap terbuka.
    """
    fixed_days = {ls.day for ls in lecturer.lecturerSchedules}
    return list(fixed_days) if fixed_days else list(WEEKDAYS)


def _find_lecturer_slot(lecturer, schedules, state: "SchedulingState"):
    """
    Mencari slot (day, schedule) pertama yang masih kosong untuk dosen
    ini. Diutamakan hari-hari yang sudah jadi komitmen tetapnya; kalau
    semua slot di hari-hari itu penuh, baru dicoba hari lain (fallback)
    supaya dosen tetap dapat kebagian jadwal selama masih memungkinkan.
    """
    preferred_days = _lecturer_preferred_days(lecturer)
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


def _sort_lecturers_by_priority(suitable_lecturers):
    """Dosen dengan priority_rate tertinggi (paling cocok) dicoba lebih dulu."""
    return sorted(suitable_lecturers, key=lambda item: item[1], reverse=True)


def _sort_rooms_by_fit(suitable_rooms_or_labs, isLab: bool):
    """
    Ruangan/lab dengan priority_rate tertinggi dicoba lebih dulu (paling
    pas kapasitasnya / paling cocok spesialisasinya). Untuk lab, urutkan
    dari priority_rate_lab (kecocokan spesialisasi) dulu, baru
    priority_rate (kepasan kapasitas).
    """
    if isLab:
        return sorted(suitable_rooms_or_labs, key=lambda item: (item[2], item[1]), reverse=True)
    return sorted(suitable_rooms_or_labs, key=lambda item: item[1], reverse=True)


def assign_lecturer_first(course_schedule_entry, schedules, state: "SchedulingState", forced_lecturer_id=None):
    """
    Inti module 3: untuk SATU unit penjadwalan (dict berisi course, index,
    isLab, suitable_lecturers, suitable_rooms_or_labs, paired_with -- lihat
    schedule_controller.py) --

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

    candidate_lecturers = _sort_lecturers_by_priority(suitable_lecturers)
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

    sorted_rooms = _sort_rooms_by_fit(suitable_rooms_or_labs, isLab)

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
    non_priority_courses mulai diproses di module lain.

    Entry yang "sepaket" (`paired_with` terisi -- versi ruangan & versi
    lab dari course+index yang sama) diproses berpasangan: begitu versi
    pertama dapat dosen, versi kedua dipaksa pakai dosen yang sama lewat
    `forced_lecturer_id`.

    Return (assigned, unscheduled, state):
    - assigned     : list hasil assignment yang berhasil (dict dengan
                      course, index, isLab, lecturer, room, day, schedule)
    - unscheduled  : list entry yang gagal dijadwalkan, untuk dilempar ke
                      module berikutnya (re-split/re-grouping)
    - state        : SchedulingState yang sudah berisi booking dari proses
                      ini, supaya bisa dilanjutkan module berikutnya tanpa
                      menabrak slot yang sudah dipakai di sini
    """
    if state is None:
        state = SchedulingState()

    assigned = []
    unscheduled = []
    processed_ids = set()

    for entry in priority_course_schedules:
        entry_id = id(entry)
        if entry_id in processed_ids:
            continue
        processed_ids.add(entry_id)

        result = assign_lecturer_first(entry, schedules, state)
        if result is None:
            unscheduled.append(entry)
            logger.warning(
                "Gagal menjadwalkan course '%s' (index %s, isLab=%s): "
                "tidak ada kombinasi dosen+slot+ruangan yang kosong.",
                entry["course"].name, entry["index"], entry["isLab"],
            )
            continue

        assigned.append(result)

        paired_entry = entry.get("paired_with")
        if paired_entry is not None and id(paired_entry) not in processed_ids:
            processed_ids.add(id(paired_entry))
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
                assigned.append(paired_result)

    logger.info(
        "Priority courses selesai diproses: %d berhasil dijadwalkan, %d gagal (menunggu module berikutnya).",
        len(assigned), len(unscheduled),
    )

    return assigned, unscheduled, state