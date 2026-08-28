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


def specialization_fit_score(course: Course, lecturer: Lecturer) -> int:
    """Skor kecocokan spesialisasi sederhana -- jumlah irisan
    `specialization_ids` dosen & course. Dipakai HANYA sebagai sinyal
    "seberapa cocok" untuk keperluan override histori (STEP baru di
    bawah), bukan untuk eligibility (itu urusan `is_eligible`)."""
    if not course.specialization_ids or not lecturer.specialization_ids:
        return 0
    return len(course.specialization_ids & lecturer.specialization_ids)


def _history_rank(course: Course, lecturer: Lecturer, fit_score: int) -> int:
    """STEP (baru): "utamakan dosen yang pernah mengajar course ini
    sebelum pindah ke dosen lain, kecuali dosen lain itu jauh lebih cocok
    DAN sangat dibutuhkan di course lain".

    Return 0 (diprioritaskan di depan tier-nya) atau 1 (tetap di
    belakang tier-nya, tapi masih di depan tier DLB/full-time
    berikutnya -- lihat `sort_key`).

    - Kalau `PRIORITIZE_LECTURER_HISTORY` mati -> selalu 0 (tidak ada
      efek, balik ke urutan lama).
    - Dosen yang PERNAH mengajar course ini -> selalu 0 (diutamakan).
    - Dosen yang BELUM PERNAH mengajar course ini -> tetap dianggap
      "boleh menyalip" (0) HANYA kalau dia:
        (a) jauh lebih cocok: `fit_score >= HISTORY_OVERRIDE_MIN_FIT_SCORE`,
            DAN
        (b) sangat dibutuhkan DI SINI: untuk DLB, jadwalnya mepet sekali
            dengan kebutuhan course (slack <= HISTORY_OVERRIDE_MAX_SLACK);
            untuk full time (jadwal unlimited, jadi tidak pernah "mepet"),
            syarat (b) otomatis terpenuhi -- cukup syarat (a) saja.
      Kalau salah satu syarat tidak terpenuhi -> 1 (dosen riwayat-lah yang
      tetap didahulukan, dosen ini "menunggu" di belakang tier-nya --
      tetap bisa kepakai kalau tidak ada dosen riwayat yang eligible sama
      sekali untuk course ini).
    """
    if not cfg.PRIORITIZE_LECTURER_HISTORY:
        return 0
    if lecturer.has_taught(course.id):
        return 0

    much_more_suitable = fit_score >= cfg.HISTORY_OVERRIDE_MIN_FIT_SCORE
    if not much_more_suitable:
        return 1

    if lecturer.is_dlb:
        needed = required_lecturer_capacity_slots(course)
        slack = lecturer.schedule_count() - needed  # >= 0, sudah difilter is_eligible
        very_needed_here = slack <= cfg.HISTORY_OVERRIDE_MAX_SLACK
        return 0 if very_needed_here else 1

    # Full time: jadwal dianggap unlimited -> tidak pernah "mepet", jadi
    # syarat "sangat dibutuhkan" otomatis lolos begitu kecocokannya
    # (fit_score) memang jauh lebih tinggi.
    return 0


def build_candidates(course: Course, lecturers: Dict[str, Lecturer]) -> List[Lecturer]:
    """Bangun & urutkan daftar kandidat dosen untuk 1 course.

    Urutan (STEP: "order candidates to dlb first by schedule count
    ascending", + STEP baru "utamakan dosen yang pernah mengajar course
    ini"):
      1. DLB dulu, ascending berdasar jumlah slot jadwal (paling sempit
         duluan) -- TIDAK berubah, DLB tetap selalu didahulukan di atas
         full time apa pun histori/kecocokannya.
      2. Di dalam tier yang sama (DLB vs DLB, full time vs full time):
         dosen yang PERNAH mengajar course ini didahulukan dulu, baru
         dosen yang belum pernah -- KECUALI dosen yang belum pernah itu
         jauh lebih cocok (skor spesialisasi) DAN sangat dibutuhkan di
         course ini (khusus DLB: jadwalnya mepet sekali dgn kebutuhan
         course), baru dia boleh "menyalip" (lihat `_history_rank`).
      3. Tie-break lain seperti sebelumnya: DLB ascending jumlah slot
         jadwal; full time (kalau BALANCE_FULLTIME_LOAD) ascending jumlah
         course yang sudah dipegang.
    """
    candidates = []
    for lecturer in lecturers.values():
        ok, _ = is_eligible(course, lecturer)
        if ok:
            candidates.append(lecturer)

    def sort_key(l: Lecturer):
        fit = specialization_fit_score(course, l)
        history_rank = _history_rank(course, l, fit)
        if l.is_dlb:
            return (0, history_rank, l.schedule_count(), -fit, l.assigned_course_count, l.id)
        load = l.assigned_course_count if cfg.BALANCE_FULLTIME_LOAD else 0
        return (1, history_rank, 0, -fit, load, l.id)

    candidates.sort(key=sort_key)
    return candidates
