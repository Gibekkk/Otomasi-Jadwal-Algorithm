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

PRINSIP FALLBACK (PENTING -- lihat schedule_one_split untuk detail):
  - Jadwal (hari/periode) & ruang SELALU diusahakan dibuat untuk semua
    porsi course (teori & lab), bahkan kalau tidak ada dosen yang bisa
    diverifikasi bebas-bentrok untuk porsi itu. Course_schedule TIDAK
    boleh hilang dari output hanya karena dosennya tidak ketemu.
  - fallback_reason HANYA diisi pada porsi yang memang tidak dapat dosen
    ter-verifikasi bebas-bentrok (lecturer_id-nya None untuk porsi itu).
    Porsi lain di split yang sama yang berhasil dapat dosen asli TIDAK
    ikut ditandai fallback walaupun porsi lain (mis. lab) gagal.
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


def _day_split_cap(total_needed: int) -> int:
    """STEP (baru): 'kalau schedule sudah tidak cukup untuk memenuhi
    sks_count, course_schedule dipecah jadi 2 dengan sisa sks di hari
    lain, dosen sama'.

    Kalau `total_needed` (sks_count course) termasuk yang wajib
    diprioritaskan untuk displit (lihat `cfg.PRIORITIZE_DAY_SPLIT_FOR_SKS`,
    default {3, 4}), batasi maksimal periode yang boleh diambil DALAM SATU
    HARI jadi `ceil(total_needed / 2)` -- supaya course otomatis kepecah
    ke 2 hari (dosen yang sama) walaupun hari itu sebenarnya masih cukup
    periode buat menampung semuanya sekaligus. Ini mencegah 1 hari jadwal
    dosen habis dipakai 1 course besar (sks 3/4) saja.

    Untuk sks_count di luar set itu, tidak ada batas tambahan (`total_needed`
    dikembalikan apa adanya -- perilaku lama: ambil sebanyak mungkin dalam
    1 hari, baru pindah hari kalau memang kehabisan slot).
    """
    if total_needed in cfg.PRIORITIZE_DAY_SPLIT_FOR_SKS:
        return math.ceil(total_needed / 2)
    return total_needed


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
    + 'kalau jadwal dosen/hari habis, cari hari lain, dosen tetap sama'
    + 'kalau sks_count 3/4, prioritaskan split ke hari lain supaya tidak
    menghabiskan jadwal harian' (lihat `_day_split_cap`).

    Return (chunks, remaining) di mana chunks = list of
    {"day", "periods":[Period,...], "room": Room, "sks_count": int}
    dan remaining = sisa periode yang TIDAK dapat slot (0 kalau penuh
    terpenuhi). `sks_count` pada tiap chunk = jumlah periode NYATA yang
    berhasil dialokasikan untuk chunk (hari) tsb -- dipakai supaya
    `course_schedules.sks_count` mencerminkan porsi sks course yang benar2
    ada di hari itu, bukan selalu total sks_count course secara utuh.
    """
    chunks = []
    remaining = needed
    day_cap = _day_split_cap(needed)
    for day in day_order:
        if remaining <= 0:
            break
        # Batasi permintaan periode di hari ini ke `day_cap` (kalau
        # sks_count course termasuk yang diprioritaskan displit), supaya
        # tidak "menghabiskan" seluruh slot harian hanya untuk 1 course.
        want_this_day = min(remaining, day_cap)
        result = find_best_run_with_room(
            periods,
            day,
            want_this_day,
            lecturer,
            rooms,
            min_capacity=per_split_capacity,
            want_lab=False,
            required_specialization_ids=None,
            require_full_length=False,
        )
        if result is None:
            continue
        got = len(result["periods"])
        chunks.append(
            {"day": day, "periods": result["periods"], "room": result["room"], "sks_count": got}
        )
        remaining -= got
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
            return {
                "day": day,
                "periods": result["periods"],
                "room": result["room"],
                "sks_count": len(result["periods"]),
            }
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
    """Best-effort terakhir kalau BENAR-BENAR tidak ada dosen bebas-bentrok
    yang ketemu: tempatkan begitu saja di hari & ruang pertama yang
    kapasitasnya cukup dan bebas, TANPA cek bentrok dosen (karena memang
    tidak ada dosen yang bisa dipasang). Course_schedule tetap dibuat
    supaya tidak ada course yang hilang dari output; siapa yang mengajar
    (lecturer_id) ditandai oleh caller lewat fallback_reason.

    PENTING: fungsi ini mencoba SEMUA hari di `day_order` (bukan cuma
    hari pertama) dan mengambil periode kontigu SEBANYAK MUNGKIN per
    hari (bukan cuma 1 periode/hari untuk teori) supaya peluang dapat
    slot penuh jauh lebih besar -- termasuk untuk blok lab yang mesti
    kontigu 1 hari tapi boleh dicoba di hari lain kalau hari pertama
    penuh.
    """
    chunks: List[dict] = []
    remaining = needed
    for day in day_order:
        if remaining <= 0:
            break
        # Coba ambil window kontigu SEPANJANG MUNGKIN (maks `remaining`)
        # dulu, baru turun ke window lebih pendek -- supaya hemat hari
        # (mengisi 1 hari sepenuh mungkin sebelum pindah ke hari lain).
        # Untuk blok lab (want_lab=True), TIDAK boleh dipecah -> hanya
        # window sepanjang penuh `remaining` yang diterima (sesuai aturan
        # "blok lab kontigu dalam satu hari").
        lengths_to_try = [remaining] if want_lab else list(range(remaining, 0, -1))
        placed_this_day = False
        for length in lengths_to_try:
            if length > len(periods):
                continue
            for start in range(0, len(periods) - length + 1):
                window = periods[start : start + length]
                pids = [p.id for p in window]
                room = find_room_for_run(rooms, day, pids, per_split_capacity, want_lab, spec_ids)
                if room:
                    chunks.append(
                        {"day": day, "periods": list(window), "room": room, "sks_count": length}
                    )
                    remaining -= length
                    placed_this_day = True
                    break
            if placed_this_day:
                break
        # blok lab: begitu ketemu 1 hari yang muat, langsung selesai (blok
        # tidak boleh dipecah lintas hari). Kalau BELUM ketemu, lanjut
        # coba hari berikutnya di `day_order` -- JANGAN berhenti di hari
        # pertama saja.
        if want_lab and remaining <= 0:
            break
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
    bentrok jadwal.

    Jadwal & ruang tetap diusahakan terbentuk untuk SEMUA porsi (teori
    & lab) walau dosen utama tidak ketemu / tidak bisa dipasang di
    sebagian porsi -- fallback_reason hanya nempel di porsi yang memang
    tidak dapat dosen ter-verifikasi bebas-bentrok."""
    theory_needed, lab_needed = theory_and_lab_slots(course)

    primary: Optional[Lecturer] = None
    theory_chunks: List[dict] = []
    theory_remaining = theory_needed
    lab_chunk: Optional[dict] = None

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
        break

    # Book slot yang SUDAH TERVERIFIKASI bebas-bentrok (dosen & ruang),
    # supaya tidak dipakai split/course lain berikutnya.
    if primary is not None:
        for chunk in theory_chunks:
            for p in chunk["periods"]:
                primary.book(chunk["day"], p.id)
            chunk["room"].booked.setdefault(chunk["day"], set()).update(p.id for p in chunk["periods"])
        if lab_chunk:
            for p in lab_chunk["periods"]:
                primary.book(lab_chunk["day"], p.id)
            lab_chunk["room"].booked.setdefault(lab_chunk["day"], set()).update(
                p.id for p in lab_chunk["periods"]
            )
        primary.assigned_course_count += 1

    no_candidate_reason = (
        cfg.REASON_NO_FREE_SLOT_FOR_ANY_CANDIDATE if candidates else cfg.REASON_NO_ELIGIBLE_LECTURER
    )

    # ---- porsi TEORI: paksa cari SISA slot (kalau ada) tanpa cek dosen ----
    # Ini jalan baik ketika primary None sama sekali (semua kandidat gagal)
    # MAUPUN ketika primary ketemu tapi cuma dapat sebagian periode teori.
    theory_forced_chunks: List[dict] = []
    if theory_remaining > 0:
        theory_forced_chunks = _force_placement(
            rooms, periods, day_order, theory_remaining, per_split_capacity, False, None
        )
        for chunk in theory_forced_chunks:
            chunk["room"].booked.setdefault(chunk["day"], set()).update(p.id for p in chunk["periods"])
        theory_remaining -= sum(len(c["periods"]) for c in theory_forced_chunks)
    theory_forced_reason = no_candidate_reason if primary is None else cfg.REASON_FORCED_PLACEMENT

    # ---- porsi LAB: paksa cari (tanpa dosen) kalau dosen utama tidak
    # ketemu SAMA SEKALI, atau ketemu tapi blok lab-nya sendiri gagal cari
    # slot bebas-bentrok untuk dosen itu. JANGAN diam-diam tempelkan
    # primary ke slot yang belum diverifikasi bebas dari jadwalnya --
    # itu bisa jadi bentrok ganda yang tidak ketahuan.
    lab_forced = False
    if course.is_lab and lab_chunk is None:
        forced = _force_placement(
            rooms, periods, day_order, lab_needed, per_split_capacity, True, course.specialization_ids
        )
        if forced:
            lab_chunk = forced[0]
            lab_chunk["room"].booked.setdefault(lab_chunk["day"], set()).update(
                p.id for p in lab_chunk["periods"]
            )
            lab_forced = True
    lab_forced_reason = no_candidate_reason if primary is None else cfg.REASON_NO_LAB_SLOT

    # co-lecturer: eligibility saja, TIDAK dicek bentrok (sesuai flow).
    # Kalau kandidat co-lecturer yang tersedia cuma sebagian (mis. course
    # butuh 3 dosen tambahan tapi cuma 1-2 yang eligible), yang eligible
    # tetap dipasang -- hanya slot yang benar2 tidak dapat kandidat yang
    # ditandai fallback.
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

    # Sesi teori yang dapat dosen asli, bebas-bentrok -> TIDAK ada fallback.
    # PENTING: 1 chunk (periode kontigu hasil alokasi 1 hari) -> TEPAT 1
    # PlannedSession -> 1 baris course_schedules. `period_id` diisi periode
    # PERTAMA di chunk (titik mulai blok), dan `sks_count` menandakan
    # berapa banyak periode berturut-turut yang dicakup blok itu (dipakai
    # di sisi lain untuk menghitung end_time sebenarnya) -- BUKAN membuat
    # 1 course_schedule terpisah untuk tiap periode di dalam chunk yang
    # sama.
    for chunk in theory_chunks:
        session = PlannedSession(
            course_id=course.id,
            course_name=course.name,
            course_index=course_index,
            day=chunk["day"],
            period_id=chunk["periods"][0].id,
            room_id=chunk["room"].id,
            is_lab_block=False,
            sks_count=chunk["sks_count"],
        )
        session.lecturer_assignments.append(
            LecturerAssignment(role_index=0, lecturer_id=primary.id, fallback_reason=None)
        )
        session.lecturer_assignments.extend(extra_lecturers)
        sessions.append(session)

    # Sesi teori hasil paksa (dosen tidak ter-verifikasi bebas-bentrok)
    # -> lecturer_id None + fallback_reason. Sama seperti di atas: 1 chunk
    # -> 1 PlannedSession, period_id = periode pertama di chunk.
    for chunk in theory_forced_chunks:
        session = PlannedSession(
            course_id=course.id,
            course_name=course.name,
            course_index=course_index,
            day=chunk["day"],
            period_id=chunk["periods"][0].id,
            room_id=chunk["room"].id,
            is_lab_block=False,
            sks_count=chunk["sks_count"],
        )
        session.lecturer_assignments.append(
            LecturerAssignment(role_index=0, lecturer_id=None, fallback_reason=theory_forced_reason)
        )
        session.lecturer_assignments.extend(extra_lecturers)
        sessions.append(session)

    if course.is_lab and lab_chunk:
        lab_lecturer_id = primary.id if (primary is not None and not lab_forced) else None
        lab_reason = None if lab_lecturer_id is not None else lab_forced_reason
        session = PlannedSession(
            course_id=course.id,
            course_name=course.name,
            course_index=course_index,
            day=lab_chunk["day"],
            period_id=lab_chunk["periods"][0].id,
            room_id=lab_chunk["room"].id,
            is_lab_block=True,
            # PENTING: beda dgn teori -- utk blok lab, backend SUDAH punya
            # konvensi tetap "1 course_schedule lab = LAB_BLOCK_SKS_EQUIVALENT
            # (3) schedule slot berturut-turut dari period_id start", jadi
            # `sks_count` yang disimpan harus tetap 1 (bukan jumlah periode
            # nyata yang dicakup blok itu). Backend yang mengekspansi 1 jadi
            # 3 schedule sendiri saat dibaca.
            sks_count=1,
        )
        session.lecturer_assignments.append(
            LecturerAssignment(role_index=0, lecturer_id=lab_lecturer_id, fallback_reason=lab_reason)
        )
        session.lecturer_assignments.extend(extra_lecturers)
        sessions.append(session)
        # kalau lab_chunk None: blok lab benar2 tidak dapat ruang/slot sama
        # sekali (bahkan force-placement gagal, misal tidak ada ruang lab
        # sama sekali yang muat di hari manapun) -- tidak ada course_schedule
        # row lab yang bisa dibuat karena tidak ada room_id valid untuk
        # diisi (kolom room_id NOT NULL). Ini tercatat di stats "issues"
        # oleh generator.py.

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
