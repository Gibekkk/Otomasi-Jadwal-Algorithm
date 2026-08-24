"""
Orkestrasi penjadwalan 1 course -> list[PlannedSession].
===========================================================
Menggabungkan semua step dari flow:
  - find suitable schedule, scale with lecturer count
  - find suitable rooms by capacity
  - auto scale rooms for course split if capacity over the room limit
  - if lab: cari lab (6-7 strategy)
  - kalau jadwal dosen/hari habis -> lanjut ke hari lain (dosen sama)
  - fallback_reason kalau gagal cari dosen
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from . import config as cfg
from .allocation import find_best_run_with_room, find_room_for_run
from .matching import theory_and_lab_slots
from .models import (
    Course,
    Lecturer,
    LecturerAssignment,
    PlannedSession,
    Period,
    Room,
)


def _max_capacity(rooms: Sequence[Room], want_lab: bool, spec_ids) -> int:
    best = 0
    for r in rooms:
        if r.is_lab != want_lab:
            continue
        if want_lab and spec_ids and cfg.LAB_REQUIRE_SPECIALIZATION_MATCH:
            if not (r.lab_specialization_ids & spec_ids):
                continue
        best = max(best, r.capacity)
    return best


def _compute_splits(course: Course, rooms: Sequence[Room]) -> int:
    """STEP: 'auto scale rooms for course split if capacity is over the
    room limit' + 'prioritize lab capacity over room capacity'.

    Jumlah course_index paralel = kebutuhan terbesar antara kapasitas
    ruang kelas biasa vs kapasitas ruang lab (kalau course-nya lab).
    Lab diprioritaskan dalam artian: kalau kapasitas lab yang cocok lebih
    kecil dari ruang kelas, jumlah split ikut kapasitas lab (lebih
    banyak split), BUKAN kapasitas ruang kelas yang mungkin sebenarnya
    cukup.
    """
    max_room_cap = _max_capacity(rooms, want_lab=False, spec_ids=None)
    splits_by_room = math.ceil(course.capacity / max_room_cap) if max_room_cap > 0 else 1

    splits_by_lab = 1
    if course.is_lab:
        max_lab_cap = _max_capacity(rooms, want_lab=True, spec_ids=course.specialization_ids)
        splits_by_lab = math.ceil(course.capacity / max_lab_cap) if max_lab_cap > 0 else 1

    return max(splits_by_room, splits_by_lab, 1)


def _allocate_theory(
    course: Course,
    lecturer: Lecturer,
    needed: int,
    per_split_capacity: int,
    rooms: Sequence[Room],
    periods: Sequence[Period],
    day_order: Sequence[str],
) -> tuple:
    """STEP: 'find suitable schedule' + 'find suitable rooms by capacity'
    + 'kalau jadwal dosen/hari habis, cari hari lain, dosen tetap sama'.

    Return (chunks, remaining) di mana chunks = list of
    {"day", "periods":[Period,...], "room": Room} dan remaining = sisa
    periode yang TIDAK dapat slot (0 kalau penuh terpenuhi).
    """
    chunks = []
    remaining = needed
    for day in day_order:
        if remaining <= 0:
            break
        result = find_best_run_with_room(
            periods,
            day,
            remaining,
            lecturer,
            rooms,
            min_capacity=per_split_capacity,
            want_lab=False,
            required_specialization_ids=None,
            require_full_length=False,
        )
        if result is None:
            continue
        chunks.append({"day": day, "periods": result["periods"], "room": result["room"]})
        remaining -= len(result["periods"])
        if not cfg.ALLOW_THEORY_SPLIT_ACROSS_DAYS:
            break
    return chunks, remaining


def _allocate_lab(
    course: Course,
    lecturer: Lecturer,
    needed: int,
    per_split_capacity: int,
    rooms: Sequence[Room],
    periods: Sequence[Period],
    day_order: Sequence[str],
) -> Optional[dict]:
    """STEP: 'if lab, find suitable lab (6-7 strategy)'. Blok lab harus
    kontigu dalam SATU hari (tidak dipecah lintas hari), prioritas
    kapasitas lab dicek lewat `min_capacity=per_split_capacity` yang
    sudah dihitung dari `_compute_splits` (yang sudah memperhitungkan
    kapasitas lab)."""
    for day in day_order:
        result = find_best_run_with_room(
            periods,
            day,
            needed,
            lecturer,
            rooms,
            min_capacity=per_split_capacity,
            want_lab=True,
            required_specialization_ids=course.specialization_ids,
            require_full_length=True,
        )
        if result is not None:
            return {"day": day, "periods": result["periods"], "room": result["room"]}
        if not cfg.ALLOW_LAB_SPLIT_ACROSS_DAYS:
            continue
    return None


def _force_placement(
    rooms: Sequence[Room],
    periods: Sequence[Period],
    day_order: Sequence[str],
    needed: int,
    per_split_capacity: int,
    want_lab: bool,
    spec_ids,
) -> List[dict]:
    """Best-effort terakhir kalau BENAR-BENAR tidak ada dosen/slot bebas
    bentrok yang ketemu: tempatkan begitu saja di hari & ruang pertama
    yang kapasitasnya cukup, TANPA cek bentrok dosen (karena memang tidak
    ada dosen yang bisa dipasang). Course_schedule tetap dibuat supaya
    tidak ada course yang hilang dari output; masalah ditandai lewat
    fallback_reason oleh caller.
    """
    chunks = []
    remaining = needed
    for day in day_order:
        if remaining <= 0:
            break
        # cari window kontigu pertama yang ada ruangnya, tanpa cek dosen
        window_len = remaining if want_lab else 1
        for start in range(0, max(len(periods) - window_len + 1, 0)):
            window = periods[start : start + window_len]
            pids = [p.id for p in window]
            room = find_room_for_run(rooms, day, pids, per_split_capacity, want_lab, spec_ids)
            if room:
                chunks.append({"day": day, "periods": list(window), "room": room})
                remaining -= len(window)
                break
        if want_lab:
            break  # blok lab: 1 hari saja, berhasil/gagal langsung selesai
    return chunks


def schedule_one_split(
    course: Course,
    course_index: str,
    per_split_capacity: int,
    candidates: Sequence[Lecturer],
    rooms: Sequence[Room],
    periods: Sequence[Period],
    day_order: Sequence[str],
) -> List[PlannedSession]:
    """Jadwalkan 1 course_index (1 kelas paralel) dari sebuah course:
    cari dosen utama + slot teori (+ blok lab kalau perlu), lalu tempel
    dosen tambahan (co-lecturer, sesuai course.lecturer_count) yang boleh
    bentrok jadwal."""
    theory_needed, lab_needed = theory_and_lab_slots(course)

    primary: Optional[Lecturer] = None
    theory_chunks: List[dict] = []
    theory_remaining = theory_needed
    lab_chunk: Optional[dict] = None
    lab_failed = False

    # STEP: coba tiap kandidat sampai ketemu yang minimal bisa dapat
    # SEBAGIAN slot teori (greedy -- bukan cari solusi paling optimal
    # secara global, tapi kandidat pertama yang "cukup layak").
    for candidate in candidates:
        if theory_needed > 0:
            chunks, remaining = _allocate_theory(
                course, candidate, theory_needed, per_split_capacity, rooms, periods, day_order
            )
            if not chunks:
                continue  # kandidat ini tidak dapat slot sama sekali, coba berikutnya
        else:
            # Course full-lab (porsi teori 0 slot, misal sks_count == 1) --
            # tidak ada yang perlu dicari untuk teori, langsung dianggap "ok".
            chunks, remaining = [], 0
        primary = candidate
        theory_chunks = chunks
        theory_remaining = remaining
        if course.is_lab:
            lab_chunk = _allocate_lab(
                course, candidate, lab_needed, per_split_capacity, rooms, periods, day_order
            )
            lab_failed = lab_chunk is None
        break

    lecturer_fallback_reason = None
    lab_was_forced = False
    if primary is None:
        # Tidak ada satupun kandidat yang dapat slot -> paksa penempatan
        # ruang/waktu (best effort) tanpa dosen, supaya data tetap dibuat.
        lecturer_fallback_reason = (
            cfg.REASON_NO_FREE_SLOT_FOR_ANY_CANDIDATE
            if candidates
            else cfg.REASON_NO_ELIGIBLE_LECTURER
        )
        theory_chunks = _force_placement(
            rooms, periods, day_order, theory_needed, per_split_capacity, False, None
        )
        theory_remaining = theory_needed - sum(len(c["periods"]) for c in theory_chunks)
        if course.is_lab:
            forced_lab = _force_placement(
                rooms, periods, day_order, lab_needed, per_split_capacity, True, course.specialization_ids
            )
            lab_chunk = forced_lab[0] if forced_lab else None
            lab_failed = lab_chunk is None
            lab_was_forced = lab_chunk is not None
    else:
        # book slot punya dosen utama supaya tidak dipakai split/course lain
        for chunk in theory_chunks:
            for p in chunk["periods"]:
                primary.book(chunk["day"], p.id)
            chunk["room"].booked.setdefault(chunk["day"], set()).update(p.id for p in chunk["periods"])
        if course.is_lab and lab_chunk is None:
            # Dosen utama ketemu & teori aman, tapi blok lab-nya sendiri gagal
            # cari slot bebas-bentrok -> coba force-placement KHUSUS bagian
            # lab ini saja (tetap pakai dosen yg sudah ketemu), supaya
            # course_schedule lab-nya tetap tercatat (bukan hilang total).
            forced_lab = _force_placement(
                rooms, periods, day_order, lab_needed, per_split_capacity, True, course.specialization_ids
            )
            lab_chunk = forced_lab[0] if forced_lab else None
            lab_was_forced = lab_chunk is not None
        if lab_chunk:
            for p in lab_chunk["periods"]:
                primary.book(lab_chunk["day"], p.id)
            lab_chunk["room"].booked.setdefault(lab_chunk["day"], set()).update(
                p.id for p in lab_chunk["periods"]
            )
        primary.assigned_course_count += 1

    # susun pesan fallback gabungan (dosen / partial / lab) untuk role dosen utama
    reasons = []
    if lecturer_fallback_reason:
        reasons.append(lecturer_fallback_reason)
    if theory_remaining > 0:
        reasons.append(
            cfg.REASON_PARTIAL_THEORY.format(done=theory_needed - theory_remaining, needed=theory_needed)
        )
    if course.is_lab and lab_failed:
        reasons.append(cfg.REASON_NO_LAB_SLOT)
    if (primary is None and (theory_chunks or lab_chunk)) or lab_was_forced:
        reasons.append(cfg.REASON_FORCED_PLACEMENT)
    fallback_reason = "; ".join(reasons) if reasons else None

    # co-lecturer: eligibility saja, TIDAK dicek bentrok (sesuai flow)
    extra_lecturers: List[LecturerAssignment] = []
    if course.lecturer_count > 1:
        used_ids = {primary.id} if primary else set()
        pool = [c for c in candidates if c.id not in used_ids]
        for role_index in range(1, course.lecturer_count):
            if pool:
                extra = pool.pop(0)
                used_ids.add(extra.id)
                extra_lecturers.append(LecturerAssignment(role_index=role_index, lecturer_id=extra.id))
            else:
                extra_lecturers.append(
                    LecturerAssignment(
                        role_index=role_index,
                        lecturer_id=None,
                        fallback_reason=cfg.REASON_NO_EXTRA_LECTURER,
                    )
                )

    sessions: List[PlannedSession] = []
    for chunk in theory_chunks:
        for p in chunk["periods"]:
            session = PlannedSession(
                course_id=course.id,
                course_name=course.name,
                course_index=course_index,
                day=chunk["day"],
                period_id=p.id,
                room_id=chunk["room"].id,
                is_lab_block=False,
            )
            session.lecturer_assignments.append(
                LecturerAssignment(
                    role_index=0,
                    lecturer_id=primary.id if primary else None,
                    fallback_reason=fallback_reason,
                )
            )
            session.lecturer_assignments.extend(extra_lecturers)
            sessions.append(session)

    if course.is_lab:
        if lab_chunk:
            for p in lab_chunk["periods"]:
                session = PlannedSession(
                    course_id=course.id,
                    course_name=course.name,
                    course_index=course_index,
                    day=lab_chunk["day"],
                    period_id=p.id,
                    room_id=lab_chunk["room"].id,
                    is_lab_block=True,
                )
                session.lecturer_assignments.append(
                    LecturerAssignment(
                        role_index=0,
                        lecturer_id=primary.id if primary else None,
                        fallback_reason=fallback_reason,
                    )
                )
                session.lecturer_assignments.extend(extra_lecturers)
                sessions.append(session)
        # kalau lab_chunk None: blok lab benar2 tidak dapat slot/ruang sama
        # sekali (bahkan force-placement gagal, misal tidak ada ruang lab
        # sama sekali) -- tidak ada course_schedule row lab yang bisa
        # dibuat karena tidak ada room_id valid untuk diisi (kolom
        # room_id NOT NULL). Ini akan tercatat di stats "issues" oleh
        # generator.py.

    return sessions


def schedule_course(
    course: Course,
    candidates: Sequence[Lecturer],
    rooms: Sequence[Room],
    periods: Sequence[Period],
    day_order: Sequence[str],
) -> List[PlannedSession]:
    """STEP: 'auto scale rooms for course split ... can be assigned to
    different lecturer'. Hitung jumlah course_index (kelas paralel) lalu
    jadwalkan tiap split satu-satu, merotasi urutan kandidat supaya tiap
    split cenderung dapat dosen utama yang berbeda."""
    n_splits = _compute_splits(course, rooms)
    per_split_capacity = math.ceil(course.capacity / n_splits)

    sessions: List[PlannedSession] = []
    for i in range(n_splits):
        label = cfg.COURSE_INDEX_LABELS[i] if i < len(cfg.COURSE_INDEX_LABELS) else str(i)
        rotated = list(candidates[i:]) + list(candidates[:i])
        sessions.extend(
            schedule_one_split(course, label, per_split_capacity, rotated, rooms, periods, day_order)
        )
    return sessions
