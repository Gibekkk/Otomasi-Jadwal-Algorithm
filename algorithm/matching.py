"""
STEP: "match course to candidate lecturers" + "order candidates to dlb
first by schedule count (ascending)"
=========================================================================
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import config as cfg
from .models import Course, Lecturer


def required_lecturer_capacity_slots(course: Course) -> int:
    """Total slot periode yang HARUS tersedia di jadwal dosen supaya dia
    layak jadi kandidat -- dipakai buat cek 'course sks <= lecturer
    schedule count'. Untuk course lab, sudah termasuk porsi teori
    (setelah dikurangi LAB_THEORY_SKS_REDUCTION) + blok lab
    (LAB_BLOCK_SKS_EQUIVALENT). Lihat config.py bagian "6-7 strategy".
    """
    if not course.is_lab:
        return course.sks_count
    theory = max(course.sks_count - cfg.LAB_THEORY_SKS_REDUCTION, 0)
    return theory + cfg.LAB_BLOCK_SKS_EQUIVALENT


def theory_and_lab_slots(course: Course) -> Tuple[int, int]:
    """Return (jumlah_periode_teori, jumlah_periode_lab). jumlah_periode_lab
    = 0 kalau course bukan course lab."""
    if not course.is_lab:
        return course.sks_count, 0
    theory = max(course.sks_count - cfg.LAB_THEORY_SKS_REDUCTION, 0)
    return theory, cfg.LAB_BLOCK_SKS_EQUIVALENT


def is_eligible(course: Course, lecturer: Lecturer) -> Tuple[bool, Optional[str]]:
    """Cek eligibility dasar (bukan cek bentrok slot -- itu urusan
    scheduler). Dipakai untuk dosen utama MAUPUN co-lecturer."""
    if not lecturer.is_active:
        return False, "dosen tidak aktif"

    if cfg.REQUIRE_CATEGORY_MATCH_UNLESS_INTERDISCIPLINE:
        if not course.is_interdiscipline and lecturer.category_id != course.category_id:
            return False, "kategori/prodi dosen tidak sesuai dengan course"

    if cfg.REQUIRE_SPECIALIZATION_MATCH_IF_DEFINED and course.specialization_ids:
        if not (course.specialization_ids & lecturer.specialization_ids):
            return False, "spesialisasi dosen tidak sesuai dengan course"

    if lecturer.is_dlb:
        needed = required_lecturer_capacity_slots(course)
        if lecturer.schedule_count() < needed:
            return False, "jumlah slot jadwal DLB tidak mencukupi total sks course"

    return True, None


def build_candidates(course: Course, lecturers: Dict[str, Lecturer]) -> List[Lecturer]:
    """Bangun & urutkan daftar kandidat dosen untuk 1 course.

    Urutan (STEP: "order candidates to dlb first by schedule count
    ascending"):
      1. DLB dulu, ascending berdasar jumlah slot jadwal (paling sempit
         duluan).
      2. Full time di belakang, kalau BALANCE_FULLTIME_LOAD -> diurutkan
         berdasar jumlah course yang sudah dipegang (paling sedikit dulu)
         supaya beban merata.
    """
    candidates = []
    for lecturer in lecturers.values():
        ok, _ = is_eligible(course, lecturer)
        if ok:
            candidates.append(lecturer)

    def sort_key(l: Lecturer):
        if l.is_dlb:
            return (0, l.schedule_count(), l.assigned_course_count, l.id)
        load = l.assigned_course_count if cfg.BALANCE_FULLTIME_LOAD else 0
        return (1, 0, load, l.id)

    candidates.sort(key=sort_key)
    return candidates
