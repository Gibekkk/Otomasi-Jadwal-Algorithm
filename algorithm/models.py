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
    ketersediaan jadwal (`lecturer_schedules`)."""

    id: str
    name: str
    category_id: str
    is_active: bool
    is_interdiscipline: bool
    specialization_ids: Set[str] = field(default_factory=set)

    # None periods_id set kosong + is_dlb=False -> dosen full time
    # (tidak ada baris di lecturer_schedules), dianggap tersedia di SEMUA
    # periode/hari. is_dlb=True -> hanya tersedia di available_period_ids.
    available_period_ids: Set[str] = field(default_factory=set)
    is_dlb: bool = False

    # STEP (baru): "utamakan dosen yang pernah mengajar course tersebut
    # sebelum pindah ke dosen lain". Diisi dari histori `lecture_lecturers`
    # + `lectures` + `course_schedules` pada generation-generation
    # SEBELUMNYA (lihat repository.load_lecturer_course_history()).
    # Berisi kumpulan course_id yang PERNAH diampu dosen ini.
    taught_course_ids: Set[str] = field(default_factory=set)

    # --- state yang berubah selama proses generate (bukan dari DB) ---
    # booked[day] = set of period_id yang sudah dipakai dosen ini sebagai
    # dosen UTAMA pada generation yang sedang berjalan.
    booked: Dict[str, Set[str]] = field(default_factory=dict)
    assigned_course_count: int = 0

    def has_taught(self, course_id: str) -> bool:
        return course_id in self.taught_course_ids

    def schedule_count(self) -> Optional[int]:
        """None berarti 'unlimited' (dosen full time)."""
        if not self.is_dlb:
            return None
        return len(self.available_period_ids)

    def is_free(self, day: str, period_id: str) -> bool:
        if self.is_dlb and period_id not in self.available_period_ids:
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
