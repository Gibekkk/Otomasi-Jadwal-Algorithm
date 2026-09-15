"""
scheduling_common.py

Utilitas & state yang dipakai BERSAMA oleh module 3 (lecturer_scheduler.py)
dan module 4 (room_scheduler.py), supaya keduanya "aware" terhadap slot
yang sama-sama sudah terpakai -- dosen yang sama atau ruangan/lab yang
sama tidak boleh dipakai bersamaan di slot yang sama, baik course yang
diproses module 3 (priority_courses) maupun module 4 (non_priority_courses).

Asumsi tentang model data (karena belum ada tabel "course schedule" final
di project ini):
- Satu SLOT penjadwalan = kombinasi (hari, Schedule). `Schedule` (lihat
  models/schedule.py) hanya berisi jam (timeStart/timeEnd), tidak ada
  kolom hari -- jadi harinya diambil dari enum hari yang sama dengan
  LecturerSchedule.day ('MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY',
  'FRIDAY').
- `lecturer.lecturerSchedules` dianggap sebagai hari-hari yang SUDAH jadi
  komitmen tetap dosen tsb. Kalau dosen belum punya komitmen hari sama
  sekali, semua hari kerja dianggap terbuka untuknya.
"""

from collections import defaultdict

# Sesuai enum day_enum pada model LecturerSchedule (algorithm/models/lecturer.py)
WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]


class SchedulingState:
    """
    Menyimpan slot (day, schedule_id) yang sudah terpakai selama proses
    penjadwalan berjalan -- dipakai bersama oleh module 3 & module 4
    (dioper sebagai objek yang sama / diteruskan) supaya dosen & ruangan
    yang sama tidak di-double-book di slot yang sama, mau course-nya
    diproses lewat jalur module 3 (dosen dulu) atau module 4 (ruangan
    dulu).
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


def lecturer_preferred_days(lecturer):
    """
    Hari-hari yang sudah jadi komitmen tetap dosen (dari
    lecturer.lecturerSchedules). Kalau dosen belum punya komitmen hari
    sama sekali, semua hari kerja dianggap terbuka.
    """
    fixed_days = {ls.day for ls in lecturer.lecturerSchedules}
    return list(fixed_days) if fixed_days else list(WEEKDAYS)


def sort_lecturers_by_priority(suitable_lecturers):
    """Dosen dengan priority_rate tertinggi (paling cocok) dicoba lebih dulu."""
    return sorted(suitable_lecturers, key=lambda item: item[1], reverse=True)


def sort_rooms_by_fit(suitable_rooms_or_labs, isLab: bool):
    """
    Ruangan/lab dengan priority_rate tertinggi dicoba lebih dulu (paling
    pas kapasitasnya / paling cocok spesialisasinya). Untuk lab, urutkan
    dari priority_rate_lab (kecocokan spesialisasi) dulu, baru
    priority_rate (kepasan kapasitas).
    """
    if isLab:
        return sorted(suitable_rooms_or_labs, key=lambda item: (item[2], item[1]), reverse=True)
    return sorted(suitable_rooms_or_labs, key=lambda item: item[1], reverse=True)


def resolve_forced_lecturer_id(course_schedule_entry):
    """
    Kalau course_schedule_entry punya pasangan (paired_with -- versi
    lab/non-lab dari course+index yang sama) yang SUDAH lebih dulu dapat
    dosen (entry["assignment"] terisi, tidak peduil itu diproses module 3
    atau module 4), kembalikan id dosen itu supaya entry ini dipaksa
    pakai dosen yang sama. Kalau pasangannya belum/tidak ada, return None.
    """
    paired_entry = course_schedule_entry.get("paired_with")
    if paired_entry is not None:
        paired_assignment = paired_entry.get("assignment")
        if paired_assignment is not None:
            return paired_assignment["lecturer"].id
    return None
