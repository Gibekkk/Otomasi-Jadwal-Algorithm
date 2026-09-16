"""
main.py -- orkestrator utama algoritma penjadwalan.

Alur:
    Module 1 (filter)      -> ambil data akademik aktif
    Module 2 (grouping)    -> kandidat dosen & ruangan/lab per course
    Module 5 (controller)  -> prioritas, pairing lab/non-lab, panggil module 3 & 4
    Module 6 (persistence) -> SIMPAN hasilnya ke database

Dua perubahan penting dibanding versi sebelumnya:

1. Hasil generate sekarang BENAR-BENAR DISIMPAN ke database (module 6).
   Sebelumnya hasil hanya berupa struktur data di memori, sehingga backend
   Java menerima notifikasi "generate selesai" padahal tidak ada jadwal
   baru yang tersimpan.

2. Exception TIDAK LAGI DITELAN. Versi sebelumnya membungkus semuanya
   dengan `except Exception as e: print(...)` tanpa re-raise, sehingga
   app.py selalu menganggap proses berhasil dan tetap memanggil
   generateComplete walau algoritmanya gagal total. Sekarang exception
   di-rollback lalu dilempar ulang, supaya app.py bisa menangkapnya dan
   memanggil stopGenerate.
"""

import logging

from .database import SessionLocal
from .filter import filter_data
from .grouping import group_scheduling_data
from .persistence import save_generated_schedules
from .schedule_controller import plan_schedules

logger = logging.getLogger("algorithm.main")


def format_grouped_courses(grouped_courses) -> str:
    """
    Ringkasan grouped_courses sebagai teks, untuk logging saat debugging.

    Sengaja dikembalikan sebagai string (bukan langsung print) dan hanya
    dipanggil kalau level log DEBUG aktif -- versi sebelumnya selalu
    mencetak SELURUH detail tiap course ke stdout di setiap run, yang
    berat dan sangat berisik pada data produksi.
    """
    if not grouped_courses:
        return "Tidak ada grouped course yang dihasilkan."

    lines = [f"HASIL GROUPED COURSES ({len(grouped_courses)} entri)"]
    for i, entry in enumerate(grouped_courses, start=1):
        course, index, suitable_lecturers, suitable_rooms_or_labs, isLab = entry
        lines.append(
            f"[{i}] {course.name} ({index}) - {'Lab' if isLab else 'Regular'} "
            f"| kapasitas {course.capacity} "
            f"| {len(suitable_lecturers)} dosen cocok "
            f"| {len(suitable_rooms_or_labs)} ruangan/lab cocok"
        )
    return "\n".join(lines)


def generate_timeline(timeline_generation_id, isOdd):
    """
    Jalankan seluruh proses generate untuk satu timeline_generation, lalu
    simpan hasilnya ke database.

    Return dict ringkasan (dipakai app.py untuk response). Melempar
    exception kalau prosesnya gagal -- caller yang menentukan
    rollback/notifikasi ke backend Java.
    """
    logger.info(
        "Mulai generate untuk timeline_generation_id=%s (isOdd=%s)",
        timeline_generation_id, isOdd,
    )
    db = SessionLocal()

    try:
        courses, lecturers, rooms, labs, schedules, specializations = filter_data(db, isOdd)
        logger.info(
            "Data dimuat: %d course, %d dosen, %d ruangan, %d lab, %d periode, %d spesialisasi.",
            len(courses), len(lecturers), len(rooms), len(labs), len(schedules), len(specializations),
        )

        if not schedules:
            raise ValueError(
                "Tabel `schedules` kosong -- tidak ada periode waktu yang bisa dipakai menjadwalkan."
            )

        grouped_courses = group_scheduling_data(courses, lecturers, rooms, labs, specializations)
        logger.info("Grouping menghasilkan %d unit penjadwalan.", len(grouped_courses))
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("\n%s", format_grouped_courses(grouped_courses))

        plan_result = plan_schedules(grouped_courses, schedules)

        summary = save_generated_schedules(db, timeline_generation_id, plan_result)
        db.commit()
        logger.info("Generate selesai & tersimpan: %s", summary)

        return {
            "timelineGenerationId": timeline_generation_id,
            "isOdd": bool(isOdd),
            "groupedUnits": len(grouped_courses),
            "scheduled": len(plan_result.get("course_schedules") or []),
            **summary,
        }

    except Exception:
        db.rollback()
        logger.exception("Generate gagal untuk timeline_generation_id=%s", timeline_generation_id)
        # Dilempar ulang supaya app.py tahu prosesnya GAGAL dan memanggil
        # stopGenerate, bukan generateComplete.
        raise

    finally:
        db.close()
