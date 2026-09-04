"""
Primitif alokasi: cari periode kontigu yang kosong untuk dosen + ruang.
=========================================================================
Modul ini tidak tahu apa-apa soal "course" / "lab strategy" -- isinya
cuma fungsi generik "cari N periode kontigu yang free" dan "cari ruang
yang muat & free". Dipakai bareng oleh `scheduler.py`.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from . import config as cfg
from .models import Lecturer, Period, Room


def _contiguous_free_runs(
    periods: Sequence[Period], is_free_fn
) -> List[List[Period]]:
    """Pecah `periods` (urut waktu) jadi list of runs yang kontigu & free
    menurut `is_free_fn(period) -> bool`. Contoh: kalau periode 1,2,3 free
    lalu 4 tidak, lalu 5,6 free -> hasil [[1,2,3], [5,6]]."""
    runs: List[List[Period]] = []
    current: List[Period] = []
    for p in periods:
        if is_free_fn(p):
            current.append(p)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def find_room_for_run(
    rooms: Sequence[Room],
    day: str,
    period_ids: Sequence[str],
    min_capacity: int,
    want_lab: bool,
    required_specialization_ids: Optional[set] = None,
    fit_strategy: Optional[str] = None,
    is_slot_free_fn=None,
) -> Optional[Room]:
    """Cari 1 ruang yang: tipe-nya cocok (lab/non-lab sesuai `want_lab`),
    kapasitas >= min_capacity, dan free di SEMUA `period_ids` pada `day`
    tsb. Kalau `required_specialization_ids` diisi (untuk lab), ruang
    harus punya minimal 1 spesialisasi yang beririsan.

    `is_slot_free_fn(day, period_id) -> bool`, kalau diisi, dicek SEKALI
    di awal (independen dari ruang mana pun -- dipakai utk aturan yang
    tidak terikat ruang, mis. bentrok kohort major/semester). Kalau ada
    1 saja period yang gagal, window ini langsung ditolak tanpa perlu
    cek ruang sama sekali.

    Return ruang terbaik (sesuai fit_strategy) atau None kalau tidak ada.
    """
    if is_slot_free_fn is not None and not all(is_slot_free_fn(day, pid) for pid in period_ids):
        return None

    fit_strategy = fit_strategy or (cfg.LAB_FIT_STRATEGY if want_lab else cfg.ROOM_FIT_STRATEGY)

    candidates = []
    for room in rooms:
        if room.is_lab != want_lab:
            continue
        if room.capacity < min_capacity:
            continue
        if want_lab and required_specialization_ids and cfg.LAB_REQUIRE_SPECIALIZATION_MATCH:
            if not (room.lab_specialization_ids & required_specialization_ids):
                continue
        if all(room.is_free(day, pid) for pid in period_ids):
            candidates.append(room)

    if not candidates:
        return None

    if fit_strategy == "first_fit":
        return candidates[0]
    # best_fit: ruang paling kecil yang masih muat (hemat ruang besar)
    candidates.sort(key=lambda r: (r.capacity, r.id))
    return candidates[0]


def find_best_run_with_room(
    periods: Sequence[Period],
    day: str,
    needed: int,
    lecturer: Lecturer,
    rooms: Sequence[Room],
    min_capacity: int,
    want_lab: bool,
    required_specialization_ids: Optional[set] = None,
    require_full_length: bool = False,
    is_slot_free_fn=None,
) -> Optional[dict]:
    """Cari run kontigu terpanjang (maks `needed`) di hari `day` di mana
    dosen free DAN ada ruang yang muat+free untuk seluruh run tsb.

    Strategi: ambil semua run kontigu dosen-free, lalu untuk tiap run,
    coba potongan sepanjang mungkin (dari `needed` menurun ke 1) sampai
    ketemu ruang yang cocok untuk potongan itu.

    `require_full_length=True` -> hanya terima kalau dapat pas `needed`
    penuh (dipakai untuk blok lab yang tidak boleh dipecah).

    `is_slot_free_fn` diteruskan apa adanya ke `find_room_for_run` (lihat
    docstring di sana) -- dipakai utk aturan yang tidak terikat ruang
    (mis. bentrok kohort major/semester).

    Return dict {"periods": [Period,...], "room": Room} atau None.
    """
    lecturer_free_runs = _contiguous_free_runs(
        periods, lambda p: lecturer.is_free(day, p.id)
    )

    best_result = None
    for run in lecturer_free_runs:
        max_len = min(len(run), needed)
        lengths_to_try = [max_len] if require_full_length else list(range(max_len, 0, -1))
        for length in lengths_to_try:
            # Coba semua window kontigu sepanjang `length` di dalam run ini
            for start in range(0, len(run) - length + 1):
                window = run[start : start + length]
                period_ids = [p.id for p in window]
                room = find_room_for_run(
                    rooms,
                    day,
                    period_ids,
                    min_capacity,
                    want_lab,
                    required_specialization_ids,
                    is_slot_free_fn=is_slot_free_fn,
                )
                if room is not None:
                    result = {"periods": window, "room": room}
                    if best_result is None or len(window) > len(best_result["periods"]):
                        best_result = result
                    break
            if best_result is not None and len(best_result["periods"]) == max_len:
                break
        if require_full_length and best_result is not None:
            break

    return best_result
