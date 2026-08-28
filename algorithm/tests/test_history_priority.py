"""
Test STEP (baru): "utamakan dosen DLB terlebih dahulu" (regresi -- sudah
ada sebelumnya, dipastikan tetap benar) + "utamakan dosen yang pernah
mengajar course tersebut sebelum pindah ke dosen lain, kecuali dosen lain
itu jauh lebih cocok DAN sangat dibutuhkan di course lain".

Jalankan:
    python -m algorithm.tests.test_history_priority
"""

from __future__ import annotations

from .. import config as cfg
from ..matching import build_candidates
from ..models import Course, Lecturer


def make_course(**kwargs):
    base = dict(
        id="C1", name="Algoritma", capacity=40, sks_count=3, lecturer_count=1,
        is_lab=False, is_odd=True, is_active=True, is_interdiscipline=False,
        category_id="p1", specialization_ids=set(),
    )
    base.update(kwargs)
    return Course(**base)


def make_dlb(id_, available, taught=None, category_id="p1", specialization_ids=None):
    return Lecturer(
        id=id_, name=id_, category_id=category_id, is_active=True,
        is_interdiscipline=False, specialization_ids=specialization_ids or set(),
        available_period_ids=set(available), is_dlb=True,
        taught_course_ids=set(taught or set()),
    )


def make_fulltime(id_, taught=None, category_id="p1", specialization_ids=None):
    return Lecturer(
        id=id_, name=id_, category_id=category_id, is_active=True,
        is_interdiscipline=False, specialization_ids=specialization_ids or set(),
        available_period_ids=set(), is_dlb=False,
        taught_course_ids=set(taught or set()),
    )


def test_dlb_still_prioritized_over_fulltime_regardless_of_history():
    """DLB tetap harus selalu di depan full time, walaupun full time
    punya histori mengajar course ini dan DLB tidak."""
    course = make_course()
    dlb_no_history = make_dlb("DLB1", {"P1", "P2", "P3"})
    fulltime_with_history = make_fulltime("FT1", taught={"C1"})

    candidates = build_candidates(course, {
        "DLB1": dlb_no_history,
        "FT1": fulltime_with_history,
    })
    assert [c.id for c in candidates] == ["DLB1", "FT1"], candidates
    print("OK: DLB tetap didahulukan di atas full time, histori tidak mengubah tier DLB")


def test_history_lecturer_prioritized_within_same_tier():
    """Di dalam tier full time yang sama, dosen yang PERNAH mengajar
    course ini harus didahulukan dibanding yang belum, kalau kecocokan
    spesialisasi sama-sama tidak signifikan."""
    course = make_course()
    ft_with_history = make_fulltime("FT_HIST", taught={"C1"})
    ft_no_history = make_fulltime("FT_NEW")

    candidates = build_candidates(course, {
        "FT_NEW": ft_no_history,
        "FT_HIST": ft_with_history,
    })
    assert [c.id for c in candidates] == ["FT_HIST", "FT_NEW"], candidates
    print("OK: dosen full time dgn histori mengajar course ini didahulukan")


def test_history_lecturer_prioritized_within_same_tier_dlb():
    """Sama seperti di atas tapi untuk 2 dosen DLB dengan jumlah slot
    jadwal SAMA -- histori jadi pembeda urutan."""
    course = make_course()
    dlb_hist = make_dlb("DLB_HIST", {"P1", "P2", "P3"}, taught={"C1"})
    dlb_new = make_dlb("DLB_NEW", {"P1", "P2", "P3"})

    candidates = build_candidates(course, {
        "DLB_NEW": dlb_new,
        "DLB_HIST": dlb_hist,
    })
    assert [c.id for c in candidates] == ["DLB_HIST", "DLB_NEW"], candidates
    print("OK: dosen DLB dgn histori (jadwal setara) didahulukan dibanding yg belum pernah")


def test_no_history_lecturer_cannot_override_without_much_better_fit():
    """Dosen yang belum pernah mengajar TIDAK BOLEH menyalip dosen
    riwayat hanya karena kecocokan spesialisasinya sedikit lebih baik
    (di bawah HISTORY_OVERRIDE_MIN_FIT_SCORE)."""
    course = make_course(specialization_ids={"S1", "S2", "S3"})
    ft_hist_weak_fit = make_fulltime("FT_HIST", taught={"C1"}, specialization_ids={"S1"})
    # fit=1, MASIH DI BAWAH HISTORY_OVERRIDE_MIN_FIT_SCORE (2) -> tidak boleh menyalip
    ft_new_slightly_better_fit = make_fulltime("FT_NEW", specialization_ids={"S2"})

    candidates = build_candidates(course, {
        "FT_NEW": ft_new_slightly_better_fit,
        "FT_HIST": ft_hist_weak_fit,
    })
    assert candidates[0].id == "FT_HIST", candidates
    print("OK: kecocokan spesialisasi yg tidak signifikan tidak cukup utk menyalip dosen riwayat")


def test_fulltime_can_override_history_when_much_more_suitable():
    """Dosen full time BOLEH menyalip dosen riwayat kalau kecocokan
    spesialisasinya JAUH lebih baik (>= HISTORY_OVERRIDE_MIN_FIT_SCORE).
    Full time selalu dianggap 'tersedia' (jadwal unlimited) jadi syarat
    'sangat dibutuhkan' otomatis terpenuhi."""
    course = make_course(specialization_ids={"S1", "S2", "S3"})
    ft_hist_weak_fit = make_fulltime("FT_HIST", taught={"C1"}, specialization_ids={"S1"})
    ft_new_much_better_fit = make_fulltime(
        "FT_NEW", specialization_ids={"S1", "S2", "S3"}
    )  # irisan = 3 spesialisasi >= HISTORY_OVERRIDE_MIN_FIT_SCORE (2)

    candidates = build_candidates(course, {
        "FT_NEW": ft_new_much_better_fit,
        "FT_HIST": ft_hist_weak_fit,
    })
    assert candidates[0].id == "FT_NEW", candidates
    print("OK: dosen full time yg JAUH lebih cocok boleh menyalip dosen riwayat")


def test_dlb_override_requires_both_fit_and_tight_schedule():
    """Untuk DLB: menyalip dosen riwayat butuh DUA syarat sekaligus --
    jauh lebih cocok (spesialisasi) DAN sangat dibutuhkan (jadwal mepet
    persis sesuai kebutuhan course, slack <= HISTORY_OVERRIDE_MAX_SLACK).
    Kalau cuma cocok tapi jadwalnya masih longgar (slack besar) -> TIDAK
    boleh menyalip."""
    course = make_course(sks_count=3, specialization_ids={"S1", "S2", "S3"})
    dlb_hist = make_dlb("DLB_HIST", {"P1", "P2", "P3"}, taught={"C1"}, specialization_ids={"S1"})

    # Kandidat A: cocok sekali TAPI jadwalnya longgar (slack=2, > MAX_SLACK 0)
    dlb_fit_but_loose = make_dlb(
        "DLB_LOOSE", {"P1", "P2", "P3", "P4", "P5"},
        specialization_ids={"S1", "S2", "S3"},
    )
    candidates = build_candidates(course, {
        "DLB_HIST": dlb_hist,
        "DLB_LOOSE": dlb_fit_but_loose,
    })
    assert candidates[0].id == "DLB_HIST", candidates
    print("OK: DLB yg cocok tapi jadwalnya masih longgar TIDAK boleh menyalip dosen riwayat")

    # Kandidat B: cocok sekali DAN jadwalnya PAS (slack=0) -> baru boleh menyalip
    dlb_fit_and_tight = make_dlb(
        "DLB_TIGHT", {"P1", "P2", "P3"},  # persis 3, sama dgn sks_count=3
        specialization_ids={"S1", "S2", "S3"},
    )
    candidates2 = build_candidates(course, {
        "DLB_HIST": dlb_hist,
        "DLB_TIGHT": dlb_fit_and_tight,
    })
    assert candidates2[0].id == "DLB_TIGHT", candidates2
    print("OK: DLB yg jauh lebih cocok DAN jadwalnya sangat mepet/dibutuhkan boleh menyalip")


def test_history_toggle_off_falls_back_to_original_order():
    """Kalau PRIORITIZE_LECTURER_HISTORY dimatikan, urutan balik seperti
    semula (histori tidak berpengaruh sama sekali)."""
    course = make_course()
    ft_hist = make_fulltime("FT_HIST", taught={"C1"})
    ft_new = make_fulltime("FT_NEW")

    original = cfg.PRIORITIZE_LECTURER_HISTORY
    cfg.PRIORITIZE_LECTURER_HISTORY = False
    try:
        candidates = build_candidates(course, {"FT_NEW": ft_new, "FT_HIST": ft_hist})
        # tanpa histori, tie-break jatuh ke assigned_course_count lalu id
        # (keduanya 0), jadi urutan by id ascending: FT_HIST < FT_NEW
        assert [c.id for c in candidates] == ["FT_HIST", "FT_NEW"], candidates
    finally:
        cfg.PRIORITIZE_LECTURER_HISTORY = original
    print("OK: toggle PRIORITIZE_LECTURER_HISTORY=False mengembalikan ke urutan lama")


if __name__ == "__main__":
    test_dlb_still_prioritized_over_fulltime_regardless_of_history()
    test_history_lecturer_prioritized_within_same_tier()
    test_history_lecturer_prioritized_within_same_tier_dlb()
    test_no_history_lecturer_cannot_override_without_much_better_fit()
    test_fulltime_can_override_history_when_much_more_suitable()
    test_dlb_override_requires_both_fit_and_tight_schedule()
    test_history_toggle_off_falls_back_to_original_order()
    print("\nSemua test history-priority lolos.")
