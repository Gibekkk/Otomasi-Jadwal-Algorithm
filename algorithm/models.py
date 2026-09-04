"""
Model domain (in-memory) untuk algoritma generate jadwal.
============================================================
Dipisah dari `repository.py` supaya logic inti (matching, alokasi slot,
dsb) bisa jalan/diuji tanpa perlu koneksi DB sungguhan -- repository yang
tugasnya mengubah row MySQL <-> objek-objek di file ini.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class Period:
    """Satu baris `schedules` -- periode waktu (tidak terikat hari)."""

    id: str
    time_start: str  # "HH:MM:SS"
    time_end: str
    order: int = 0  # index urut berdasarkan time_start, diisi repository


@dataclass
class Lecturer:
    """Satu baris `lecturers`, sudah digabung dengan spesialisasi &
    ketersediaan jadwal (`lecturer_schedules` + `lecturer_schedules_time`)."""

    id: str
    name: str
    category_id: str
    is_active: bool
    is_interdiscipline: bool
    specialization_ids: Set[str] = field(default_factory=set)

    # {} kosong + is_dlb=False -> dosen full time (tidak ada baris di
    # lecturer_schedules sama sekali), dianggap tersedia di SEMUA hari &
    # periode. is_dlb=True -> hanya tersedia di hari & periode yang
    # tercatat: available_periods_by_day[day] = set periode yang tersedia
    # HARI itu -- bisa beda-beda tiap hari (lecturer_schedules = 1 baris
    # per (dosen, hari), lecturer_schedules_time = fan-out ke periode
    # spesifik hari itu). Dosen yang punya baris lecturer_schedules tapi
    # nol periode ter-link (data tidak lengkap) tetap is_dlb=True dengan
    # available_periods_by_day kosong -> schedule_count()=0 -> otomatis
    # tidak lolos eligibility manapun, TIDAK dianggap full time.
    available_periods_by_day: Dict[str, Set[str]] = field(default_factory=dict)
    is_dlb: bool = False

    # --- state yang berubah selama proses generate (bukan dari DB) ---
    # booked[day] = set of period_id yang sudah dipakai dosen ini sebagai
    # dosen UTAMA pada generation yang sedang berjalan.
    booked: Dict[str, Set[str]] = field(default_factory=dict)
    assigned_course_count: int = 0

    # Dipakai KHUSUS utk aturan "dosen laki-laki + Islam tidak dijadwalkan
    # Jumat jam sholat" -- lihat generator.py (pre-booking sebelum loop
    # course jalan) & cfg.FRIDAY_PRAYER_BLOCK_*.
    is_male: bool = False
    religion: str = ""

    def schedule_count(self) -> Optional[int]:
        """None berarti 'unlimited' (dosen full time). Untuk DLB: total
        slot periode yang tersedia, dijumlah dari SEMUA hari."""
        if not self.is_dlb:
            return None
        return sum(len(periods) for periods in self.available_periods_by_day.values())

    def is_free(self, day: str, period_id: str) -> bool:
        if self.is_dlb and period_id not in self.available_periods_by_day.get(day, set()):
            return False
        return period_id not in self.booked.get(day, set())

    def book(self, day: str, period_id: str) -> None:
        self.booked.setdefault(day, set()).add(period_id)


@dataclass
class Room:
    """Satu baris `rooms`. lab_group_id terisi -> ini ruang lab."""

    id: str
    name: str
    capacity: int
    lab_group_id: Optional[str] = None
    lab_specialization_ids: Set[str] = field(default_factory=set)

    booked: Dict[str, Set[str]] = field(default_factory=dict)

    @property
    def is_lab(self) -> bool:
        return self.lab_group_id is not None

    def is_free(self, day: str, period_id: str) -> bool:
        return period_id not in self.booked.get(day, set())

    def book(self, day: str, period_id: str) -> None:
        self.booked.setdefault(day, set()).add(period_id)


@dataclass
class Course:
    """Satu baris `courses`, digabung dengan `course_specializations`."""

    id: str
    name: str
    capacity: int
    sks_count: int
    lecturer_count: int
    is_lab: bool
    is_odd: bool
    is_active: bool
    is_interdiscipline: bool
    category_id: str
    specialization_ids: Set[str] = field(default_factory=set)

    # Dipakai KHUSUS utk aturan "1 kohort (major+semester) tidak boleh
    # bentrok jadwal" -- lihat CohortTracker & cfg.ENFORCE_COHORT_CONFLICT.
    # submajor_id=None -> course ini tidak terikat submajor tertentu.
    semester: int = 0
    submajor_id: Optional[str] = None


@dataclass
class CohortTracker:
    """Melacak slot (day, period_id) yang sudah dipakai per 'kohort'
    mahasiswa (major + semester + submajor), supaya 2 course DI KOHORT
    YANG SAMA tidak dijadwalkan bentrok waktu -- mahasiswa yang sama
    tidak mungkin ikut 2 kelas sekaligus. Lihat cfg.ENFORCE_COHORT_CONFLICT
    utk toggle & penjelasan aturan lengkap.

    Aturan bentrok:
      - HANYA berlaku kalau category_id-nya "major" sungguhan (ada di
        `prodi_category_ids`, dari categories.is_prodi = 1).
      - Major + semester sama -> BENTROK, KECUALI submajor_id beda (None
        dianggap "beda" dari submajor_id manapun yang terisi).
      - Split course_index dari course yang SAMA (course_id sama) TIDAK
        dianggap bentrok satu sama lain.
    """

    prodi_category_ids: Set[str] = field(default_factory=set)
    _booked: Dict[str, List[tuple]] = field(default_factory=dict)

    def _conflicts(self, entry: tuple, other: tuple) -> bool:
        course_id_a, cat_a, sem_a, sub_a = entry
        course_id_b, cat_b, sem_b, sub_b = other
        if course_id_a == course_id_b:
            return False
        if cat_a not in self.prodi_category_ids or cat_b not in self.prodi_category_ids:
            return False
        if cat_a != cat_b or sem_a != sem_b:
            return False
        return sub_a == sub_b

    def is_free(
        self,
        day: str,
        period_id: str,
        course_id: str,
        category_id: str,
        semester: int,
        submajor_id: Optional[str],
    ) -> bool:
        key = f"{day}|{period_id}"
        entry = (course_id, category_id, semester, submajor_id)
        return all(not self._conflicts(entry, other) for other in self._booked.get(key, []))

    def book(
        self,
        day: str,
        period_id: str,
        course_id: str,
        category_id: str,
        semester: int,
        submajor_id: Optional[str],
    ) -> None:
        key = f"{day}|{period_id}"
        self._booked.setdefault(key, []).append((course_id, category_id, semester, submajor_id))


@dataclass
class LecturerAssignment:
    """Satu dosen yang mengajar di satu PlannedSession -> 1 baris
    `lecture_lecturers` (role_index=0 -> is_main_lecturer=True). Kalau
    lecturer_id None (tidak ketemu kandidat), tidak ada baris
    lecture_lecturers yang dibuat untuk assignment ini -- fallback_reason
    tetap disimpan di sini untuk dipakai sebagai `lectures.fallback_reason`
    kalau assignment ini adalah dosen utama (role_index=0)."""

    role_index: int  # 0 = dosen utama, 1..N-1 = co-lecturer
    lecturer_id: Optional[str] = None
    fallback_reason: Optional[str] = None


@dataclass
class PlannedSession:
    """Satu kombinasi (course_index, day, period, room) -> 1 baris
    `course_schedules` + TEPAT 1 baris `lectures`, plus daftar dosen yang
    mengajar di situ (masing2 jadi 1 baris `lecture_lecturers` yang
    menunjuk ke lecture yang sama, ditandai is_main_lecturer)."""

    course_id: str
    course_name: str
    course_index: str
    day: str
    period_id: str
    room_id: str
    is_lab_block: bool = False
    sks_count: int = 0
    lecturer_assignments: List[LecturerAssignment] = field(default_factory=list)


@dataclass
class GenerationStats:
    total_courses: int = 0
    total_sessions: int = 0
    fully_scheduled_splits: int = 0
    partial_splits: int = 0
    splits_without_room: int = 0
    lecturer_fallback_count: int = 0
    issues: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total_courses": self.total_courses,
            "total_sessions": self.total_sessions,
            "fully_scheduled_splits": self.fully_scheduled_splits,
            "partial_splits": self.partial_splits,
            "splits_without_room": self.splits_without_room,
            "lecturer_fallback_count": self.lecturer_fallback_count,
            "issues": self.issues,
        }
