"""
scheduling_pairing.py

Loop pemrosesan entry yang SAMA PERSIS dipakai module 3
(lecturer_scheduler) dan module 4 (room_scheduler): iterasi entry, lewati
yang sudah ke-assign lewat pairing, panggil fungsi assignment yang sesuai,
lalu paksa pasangannya (versi lab/non-lab dari course+index yang sama)
memakai dosen yang sama.

Sebelumnya blok ini disalin dua kali dengan isi identik kecuali nama
fungsi assignment-nya; disatukan di sini supaya perubahan aturan pairing
cukup diubah di satu tempat dan tidak bisa lagi menyimpang antar modul.
"""


def schedule_entries(
    entries,
    schedules,
    state,
    assign_fn,
    resolve_forced_lecturer_id,
    failure_message,
    logger_obj,
    label,
):
    """
    `assign_fn(entry, schedules, state, forced_lecturer_id=...)` adalah
    strategi spesifik tiap modul (dosen-dulu vs ruangan-dulu). Sisanya --
    skip entry yang sudah ke-assign, pairing dosen, pencatatan gagal --
    identik untuk kedua modul.

    Return (assigned, unscheduled, state).
    """
    assigned = []
    unscheduled = []

    for entry in entries:
        if entry.get("assignment") is not None:
            # Sudah diproses lebih dulu lewat pairing.
            continue

        forced_lecturer_id = resolve_forced_lecturer_id(entry)

        result = assign_fn(entry, schedules, state, forced_lecturer_id=forced_lecturer_id)
        if result is None:
            unscheduled.append(entry)
            logger_obj.warning(
                failure_message,
                entry["course"].name, entry["index"], entry["isLab"],
            )
            continue

        entry["assignment"] = result
        assigned.append(result)

        paired_entry = entry.get("paired_with")
        if paired_entry is not None and paired_entry.get("assignment") is None:
            paired_lecturer = result.get("lecturer")
            paired_result = assign_fn(
                paired_entry, schedules, state,
                forced_lecturer_id=paired_lecturer.id if paired_lecturer is not None else None,
            )
            if paired_result is None:
                unscheduled.append(paired_entry)
                logger_obj.warning(
                    "Gagal menjadwalkan pasangan lab/ruangan dari course '%s' "
                    "(index %s) dengan dosen yang sama (%s): tidak ada slot+ruangan kosong.",
                    paired_entry["course"].name, paired_entry["index"],
                    paired_lecturer.name if paired_lecturer is not None else "-",
                )
            else:
                paired_entry["assignment"] = paired_result
                assigned.append(paired_result)

    logger_obj.info(
        "%s selesai diproses: %d berhasil dijadwalkan, %d gagal.",
        label, len(assigned), len(unscheduled),
    )

    return assigned, unscheduled, state
