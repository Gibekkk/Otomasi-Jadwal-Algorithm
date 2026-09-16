"""
scheduling_common.py

Utilitas & state yang dipakai BERSAMA oleh module 3 (lecturer_scheduler.py)
dan module 4 (room_scheduler.py), supaya keduanya "aware" terhadap slot
yang sama-sama sudah terpakai -- dosen yang sama atau ruangan/lab yang
sama tidak boleh dipakai bersamaan di slot yang sama, baik course yang
diproses module 3 (priority_courses) maupun module 4 (non_priority_courses).

Model data:
- Satu SLOT = kombinasi (hari, Schedule). `Schedule` (models/schedule.py)
  hanya berisi jam (timeStart/timeEnd), tidak ada kolom hari -- harinya
  diambil dari enum hari yang sama dengan LecturerSchedule.day.
- Satu sesi kelas menempati BLOK periode BERURUTAN, panjangnya sesuai
  sksCount (lihat session_duration()). Blok inilah yang dibooking, bukan
  cuma satu periode -- kalau cuma satu periode yang dibooking, course lain
  bisa ikut dijadwalkan menimpa jam-jam berikutnya yang sebenarnya masih
  terpakai.
- `lecturer.lecturerSchedules` = komitmen hari tetap dosen, dan tiap baris
  punya jam-jam spesifik di `lecturer_schedules_time`. Kalau dosen sama
  sekali tidak punya baris lecturer_schedules, dia dianggap full-time
  (semua hari & jam terbuka).
"""

import logging
from collections import defaultdict

logger = logging.getLogger("scheduling_common")

# Sesuai enum day_enum pada model LecturerSchedule (algorithm/models/lecturer.py)
WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]


def sort_schedules(schedules):
    """Urutkan periode dari yang paling pagi -- dipakai supaya 'blok
    berurutan' benar-benar berurutan secara waktu, bukan urutan id."""
    return sorted(schedules, key=lambda s: s.timeStart)


def session_duration(course, isLab: bool) -> int:
    """
    Panjang blok (jumlah periode berurutan) untuk satu sesi.

    - Course non-lab            -> seluruh sksCount dipakai di ruang teori.
    - Course lab dengan sks > 1 -> 1 periode untuk blok lab, sisanya
                                   (sksCount - 1) untuk porsi teori di
                                   ruang biasa. Pembagian ini mengikuti
                                   splitter.split_room_course(), yang
                                   memang membuat dua entri (ruang + lab)
                                   untuk course lab ber-sks > 1.
    - Course lab dengan sks = 1 -> hanya blok lab, 1 periode.
    """
    sks = course.sksCount or 1
    if not course.isLab:
        return max(1, sks)
    if isLab:
        return 1
    return max(1, sks - 1)


class SchedulingState:
    """
    Menyimpan slot (day, schedule_id) yang sudah terpakai selama proses
    penjadwalan berjalan -- dipakai bersama module 3 & module 4 supaya
    dosen & ruangan yang sama tidak di-double-book.

    Penyimpanan memakai set of (day, schedule_id) per dosen/ruangan,
    sehingga pengecekan bentrok O(1) per periode.
    """

    def __init__(self):
        self.lecturer_bookings = defaultdict(set)  # lecturer_id -> {(day, schedule_id)}
        self.room_bookings = defaultdict(set)      # room_id -> {(day, schedule_id)}

    def is_lecturer_free(self, lecturer_id, day, schedule_id) -> bool:
        return (day, schedule_id) not in self.lecturer_bookings[lecturer_id]

    def is_room_free(self, room_id, day, schedule_id) -> bool:
        return (day, schedule_id) not in self.room_bookings[room_id]

    def is_lecturer_free_block(self, lecturer_id, day, block) -> bool:
        """Dosen kosong di SELURUH periode dalam `block`."""
        booked = self.lecturer_bookings[lecturer_id]
        return all((day, schedule.id) not in booked for schedule in block)

    def is_room_free_block(self, room_id, day, block) -> bool:
        """Ruangan kosong di SELURUH periode dalam `block`."""
        booked = self.room_bookings[room_id]
        return all((day, schedule.id) not in booked for schedule in block)

    def book_block(self, lecturer_id, room_id, day, block):
        """
        Booking SELURUH periode dalam blok sekaligus. `lecturer_id` boleh
        None (sesi yang dapat ruangan tapi tidak dapat dosen) -- ruangannya
        tetap dibooking supaya tidak dipakai course lain.
        """
        for schedule in block:
            if lecturer_id is not None:
                self.lecturer_bookings[lecturer_id].add((day, schedule.id))
            self.room_bookings[room_id].add((day, schedule.id))


def build_day_blocks(sorted_schedules, duration: int):
    """
    Semua kemungkinan blok berurutan sepanjang `duration` dari daftar
    periode yang sudah terurut. Dihitung sekali per (duration), lalu
    dipakai ulang untuk semua hari & semua kandidat -- jauh lebih murah
    daripada membangun ulang di dalam loop.

    Return list of tuple(Schedule, ...).
    """
    if duration <= 0:
        return []
    total = len(sorted_schedules)
    if duration > total:
        return []
    return [tuple(sorted_schedules[i:i + duration]) for i in range(total - duration + 1)]


def lecturer_availability(lecturer):
    """
    Ketersediaan dosen: dict {day -> set(schedule_id)} dari
    lecturer_schedules + lecturer_schedules_time.

    - Dosen TANPA baris lecturer_schedules sama sekali -> return None,
      artinya "full-time / semua hari & jam terbuka".
    - Dosen dengan baris lecturer_schedules tapi TANPA jam spesifik di
      hari itu -> hari itu dianggap terbuka seluruh jamnya (set kosong
      diperlakukan sebagai 'tidak dibatasi jam'), supaya data yang belum
      lengkap tidak diam-diam membuat dosen jadi tidak bisa dijadwalkan
      sama sekali.
    """
    schedules_of_lecturer = lecturer.lecturerSchedules
    if not schedules_of_lecturer:
        return None

    availability = {}
    unrestricted_days = set()
    for lecturer_schedule in schedules_of_lecturer:
        day = lecturer_schedule.day
        slot_ids = {st.scheduleId for st in lecturer_schedule.scheduleTimes}
        if not slot_ids:
            # Hari tercatat tapi jamnya belum diisi -> hari ini tidak
            # dibatasi jam sama sekali.
            unrestricted_days.add(day)
            availability.setdefault(day, set())
        else:
            availability[day] = availability.get(day, set()) | slot_ids

    for day in unrestricted_days:
        availability[day] = set()
    return availability


def lecturer_allows_block(availability, day, block) -> bool:
    """
    Cek apakah blok ini masuk ke jam ketersediaan dosen.

    `availability` None -> dosen full-time, semua blok boleh.
    Hari tidak ada di availability -> dosen tidak tersedia hari itu.
    Hari ada tapi set jamnya kosong -> hari itu tidak dibatasi jam.
    """
    if availability is None:
        return True
    if day not in availability:
        return False
    allowed_slots = availability[day]
    if not allowed_slots:
        return True
    return all(schedule.id in allowed_slots for schedule in block)


def lecturer_preferred_days(lecturer):
    """
    Hari-hari yang sudah jadi komitmen tetap dosen. Kalau dosen belum punya
    komitmen hari sama sekali, semua hari kerja dianggap terbuka.
    """
    fixed_days = {ls.day for ls in lecturer.lecturerSchedules}
    return list(fixed_days) if fixed_days else list(WEEKDAYS)


def sort_lecturers_by_priority(suitable_lecturers):
    """Dosen dengan priority_rate tertinggi (paling cocok) dicoba lebih dulu."""
    return sorted(suitable_lecturers, key=lambda item: item[1], reverse=True)


def sort_rooms_by_fit(suitable_rooms_or_labs, isLab: bool):
    """
    Ruangan/lab dengan priority_rate tertinggi dicoba lebih dulu. Untuk
    lab, urutkan dari priority_rate_lab (kecocokan spesialisasi) dulu,
    baru priority_rate (kepasan kapasitas).

    Entri lab yang berasal dari splitter bisa berbentuk tuple 2 elemen
    (tanpa priority_rate_lab), jadi indeks ke-3 diambil defensif.
    """
    if isLab:
        return sorted(
            suitable_rooms_or_labs,
            key=lambda item: (item[2] if len(item) > 2 else 0, item[1]),
            reverse=True,
        )
    return sorted(suitable_rooms_or_labs, key=lambda item: item[1], reverse=True)


def resolve_forced_lecturer_id(course_schedule_entry):
    """
    Kalau pasangan entry ini (versi lab/non-lab dari course+index yang
    sama) SUDAH lebih dulu dapat dosen, kembalikan id dosen itu supaya
    entry ini dipaksa pakai dosen yang sama. Return None kalau
    pasangannya belum/tidak ada.
    """
    paired_entry = course_schedule_entry.get("paired_with")
    if paired_entry is not None:
        paired_assignment = paired_entry.get("assignment")
        if paired_assignment is not None:
            paired_lecturer = paired_assignment.get("lecturer")
            if paired_lecturer is not None:
                return paired_lecturer.id
    return None


def build_assignment(entry, lecturer, room, day, block, fallback_reason=None):
    """
    Bentuk dict hasil assignment yang seragam untuk module 3 & 4, dan yang
    dibaca module 6 (persistence.py).

    `schedule` = periode PERTAMA blok (jam mulai sesi); `duration` =
    panjang blok, yang disimpan ke course_schedules.sks_count supaya
    backend Java bisa menghitung jam selesainya. `suitable_lecturers`
    ikut dibawa supaya persistence bisa memilih co-lecturer tanpa perlu
    mencari ulang entry-nya.
    """
    return {
        "course": entry["course"],
        "index": entry["index"],
        "isLab": entry["isLab"],
        "lecturer": lecturer,
        "room": room,
        "day": day,
        "schedule": block[0],
        "block": block,
        "duration": len(block),
        "suitable_lecturers": entry.get("suitable_lecturers") or [],
        "fallback_reason": fallback_reason,
    }
