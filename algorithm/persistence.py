"""
persistence.py

Module 6 -- menyimpan hasil penjadwalan (output module 3/4/5) ke database.

Sebelumnya hasil generate hanya berupa struktur data di memori dan tidak
pernah ditulis ke DB, sehingga backend Java tetap menerima notifikasi
"generate selesai" walau tidak ada jadwal baru yang benar-benar tersimpan.
Module ini yang menutup celah itu.

Bentuk data yang ditulis (lihat models/timeline.py):

    1 assignment (hasil module 3/4)
        -> 1 baris `course_schedules`  (sesi kelas: hari, jam mulai, ruangan)
        -> 1 baris `lectures`          (mengikat sesi itu ke timeline_generation)
        -> N baris `lecture_lecturers` (dosen utama + co-lecturer)

Aturan penting:
- `lectures` TIDAK punya kolom lecturer_id. Dosen disimpan di
  `lecture_lecturers` dengan flag `is_main_lecturer`; dosen hasil
  penjadwalan (assignment["lecturer"]) selalu jadi dosen UTAMA.
- Course yang butuh lebih dari satu dosen (`course.lecturerCount > 1`)
  ditambahi co-lecturer dari sisa kandidat yang cocok. Co-lecturer TIDAK
  dicek bentrok jadwalnya -- hanya dosen utama yang wajib bebas bentrok.
- Course yang GAGAL dijadwalkan (`unscheduled`) tidak punya hari/jam/
  ruangan, jadi tidak bisa dibuatkan baris `course_schedules` sama sekali
  (ketiga kolom itu NOT NULL). Course seperti ini dilewati dan hanya
  dilaporkan lewat return value + log, bukan disimpan sebagai baris kosong.
- Semua penulisan dilakukan lewat SATU session SQLAlchemy dan di-flush
  bertahap; caller yang memutuskan commit/rollback (lihat main.py).
"""

import logging
import uuid

from .models.timeline import CourseSchedule, Lecture, LectureLecturer

logger = logging.getLogger("persistence")

# Sesi yang dosen utamanya tidak ketemu tetap disimpan (jadwal & ruangannya
# valid), tapi ditandai lewat lectures.fallback_reason supaya admin tahu
# baris ini masih perlu ditinjau manual.
REASON_NO_LECTURER = (
    "Sesi terjadwal tanpa dosen utama yang terverifikasi bebas bentrok -- perlu ditinjau manual"
)


def _new_id() -> str:
    return str(uuid.uuid4())


def _clear_previous_generation(db, timeline_generation_id: str) -> int:
    """
    Hapus hasil generate SEBELUMNYA milik timeline_generation yang sama,
    supaya `/startGenerate` yang dipanggil ulang untuk timeline yang sama
    tidak menumpuk jadwal ganda (hasil lama + hasil baru muncul bersamaan
    di tampilan timeline).

    Urutan hapus WAJIB mengikuti arah foreign key (skema tidak memakai
    ON DELETE CASCADE): lecture_lecturers -> lectures -> course_schedules.
    course_schedules baru dihapus setelah tidak ada lecture manapun yang
    menunjuk ke sana -- termasuk lecture milik timeline_generation LAIN,
    supaya hasil generate timeline lain tidak ikut terhapus.
    """
    old_lectures = (
        db.query(Lecture.id, Lecture.courseScheduleId)
        .filter(Lecture.timelineGenerationId == timeline_generation_id)
        .all()
    )
    if not old_lectures:
        return 0

    old_lecture_ids = [row.id for row in old_lectures]
    old_course_schedule_ids = {row.courseScheduleId for row in old_lectures}

    db.query(LectureLecturer).filter(
        LectureLecturer.lectureId.in_(old_lecture_ids)
    ).delete(synchronize_session=False)

    db.query(Lecture).filter(
        Lecture.timelineGenerationId == timeline_generation_id
    ).delete(synchronize_session=False)
    db.flush()

    still_referenced = {
        row.courseScheduleId
        for row in db.query(Lecture.courseScheduleId)
        .filter(Lecture.courseScheduleId.in_(old_course_schedule_ids))
        .all()
    }
    deletable = old_course_schedule_ids - still_referenced
    if deletable:
        db.query(CourseSchedule).filter(
            CourseSchedule.id.in_(deletable)
        ).delete(synchronize_session=False)

    db.flush()
    logger.info(
        "Hasil generate sebelumnya dibersihkan: %d lectures, %d course_schedules.",
        len(old_lecture_ids), len(deletable),
    )
    return len(old_lecture_ids)


def _pick_co_lecturers(assignment, main_lecturer_id):
    """
    Pilih co-lecturer (dosen pendamping) untuk sebuah sesi, sebanyak
    `course.lecturerCount - 1`, diambil dari kandidat dosen yang cocok
    selain dosen utama, urut dari priority_rate tertinggi.

    Co-lecturer sengaja TIDAK dicek bentrok jadwalnya: hanya dosen utama
    yang jadwalnya wajib bebas bentrok, jadi co-lecturer tidak ikut
    di-book ke SchedulingState.
    """
    course = assignment["course"]
    needed = (course.lecturerCount or 1) - 1
    if needed <= 0:
        return []

    candidates = assignment.get("suitable_lecturers") or []
    ranked = sorted(candidates, key=lambda item: item[1], reverse=True)

    picked = []
    for lecturer, _priority in ranked:
        if lecturer.id == main_lecturer_id:
            continue
        picked.append(lecturer)
        if len(picked) >= needed:
            break
    return picked


def save_generated_schedules(db, timeline_generation_id: str, plan_result: dict) -> dict:
    """
    Tulis `plan_result` (hasil schedule_controller.plan_schedules) ke DB.

    Return ringkasan jumlah baris yang ditulis. Caller yang commit --
    fungsi ini hanya flush, supaya kegagalan di tengah bisa di-rollback
    utuh oleh pemanggilnya.
    """
    assignments = plan_result.get("course_schedules") or []
    unscheduled = plan_result.get("unscheduled") or []

    _clear_previous_generation(db, timeline_generation_id)

    course_schedule_rows = []
    lecture_rows = []
    lecture_lecturer_rows = []

    for assignment in assignments:
        course = assignment["course"]
        room = assignment["room"]
        schedule = assignment["schedule"]
        lecturer = assignment.get("lecturer")

        course_schedule_id = _new_id()
        # `name` di DB cuma varchar(50) -- dipotong supaya course dengan
        # nama panjang tidak bikin seluruh insert gagal.
        session_name = f"{course.name} {assignment['index']}"[:50]

        course_schedule_rows.append({
            "id": course_schedule_id,
            "courseIndex": assignment["index"],
            "day": assignment["day"],
            "isLab": bool(assignment["isLab"]),
            "name": session_name,
            # Panjang blok sesi ini dalam satuan periode -- dipakai backend
            # Java untuk menghitung jam selesai dari jam mulai.
            "sksCount": assignment.get("duration") or course.sksCount,
            "courseId": course.id,
            "roomId": room.id,
            "scheduleId": schedule.id,
        })

        lecture_id = _new_id()
        lecture_rows.append({
            "id": lecture_id,
            "fallbackReason": assignment.get("fallback_reason")
            or (None if lecturer is not None else REASON_NO_LECTURER),
            "courseScheduleId": course_schedule_id,
            "timelineGenerationId": timeline_generation_id,
        })

        if lecturer is not None:
            lecture_lecturer_rows.append({
                "id": _new_id(),
                "isMainLecturer": True,
                "lectureId": lecture_id,
                "lecturerId": lecturer.id,
            })
            for co_lecturer in _pick_co_lecturers(assignment, lecturer.id):
                lecture_lecturer_rows.append({
                    "id": _new_id(),
                    "isMainLecturer": False,
                    "lectureId": lecture_id,
                    "lecturerId": co_lecturer.id,
                })

    # bulk_insert_mappings: satu INSERT multi-row per tabel, jauh lebih
    # ringan daripada membuat ribuan objek ORM satu per satu. Urutan insert
    # mengikuti arah FK: course_schedules -> lectures -> lecture_lecturers.
    if course_schedule_rows:
        db.bulk_insert_mappings(CourseSchedule, course_schedule_rows)
        db.flush()
    if lecture_rows:
        db.bulk_insert_mappings(Lecture, lecture_rows)
        db.flush()
    if lecture_lecturer_rows:
        db.bulk_insert_mappings(LectureLecturer, lecture_lecturer_rows)
        db.flush()

    for entry in unscheduled:
        logger.warning(
            "Tidak disimpan (gagal dijadwalkan): course '%s' index %s (isLab=%s).",
            entry["course"].name, entry["index"], entry["isLab"],
        )

    summary = {
        "course_schedules_inserted": len(course_schedule_rows),
        "lectures_inserted": len(lecture_rows),
        "lecture_lecturers_inserted": len(lecture_lecturer_rows),
        "unscheduled_count": len(unscheduled),
    }
    logger.info(
        "Persistensi selesai: %d course_schedules, %d lectures, %d lecture_lecturers, %d gagal dijadwalkan.",
        summary["course_schedules_inserted"],
        summary["lectures_inserted"],
        summary["lecture_lecturers_inserted"],
        summary["unscheduled_count"],
    )
    return summary
