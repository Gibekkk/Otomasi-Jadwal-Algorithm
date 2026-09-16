"""
Test end-to-end: bangun database SQLite in-memory yang meniru skema
MariaDB, jalankan seluruh pipeline (filter -> grouping -> controller ->
module 3/4 -> persistence), lalu verifikasi barisnya benar-benar masuk ke
course_schedules / lectures / lecture_lecturers.

Dijalankan tanpa MariaDB supaya bisa diverifikasi cepat:
    python test_end_to_end.py
"""

import os
import sys
import uuid
from datetime import datetime, time

os.environ.setdefault("DB_USER", "x")
os.environ.setdefault("DB_PASS", "x")
os.environ.setdefault("DB_HOST", "x")
os.environ.setdefault("DB_PORT", "3306")
os.environ.setdefault("DB_NAME", "x")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import algorithm.database as database

# Ganti engine MySQL dengan SQLite in-memory SEBELUM model & modul lain diimpor.
test_engine = create_engine("sqlite://")
database.engine = test_engine
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

from algorithm.database import Base  # noqa: E402
from algorithm.models.category import Category, Submajor  # noqa: E402
from algorithm.models.course import Course, CourseSpecialization  # noqa: E402
from algorithm.models.lecturer import (  # noqa: E402
    Lecturer, LecturerSchedule, LecturerScheduleTime, LecturerSpecialization,
)
from algorithm.models.room import LabGroup, LabSpecialization, Room  # noqa: E402
from algorithm.models.schedule import Schedule  # noqa: E402
from algorithm.models.specialization import Specialization  # noqa: E402
from algorithm.models.timeline import (  # noqa: E402
    CourseSchedule, Lecture, LectureLecturer, TimelineGeneration,
)
from algorithm import main as algo_main  # noqa: E402

TIMELINE_ID = "tg-1"


def nid():
    return str(uuid.uuid4())


def seed():
    Base.metadata.create_all(test_engine)
    db = database.SessionLocal()

    db.add(TimelineGeneration(id=TIMELINE_ID, academicYear=2026, isOdd=True, generatedBy="u1"))

    cat_if = Category(id="cat-if", name="Informatika", isProdi=True, deletedAt=None)
    cat_umum = Category(id="cat-umum", name="Umum", isProdi=False, deletedAt=None)
    db.add_all([cat_if, cat_umum])

    spec_be = Specialization(id="spec-be", name="Backend", deletedAt=None)
    spec_net = Specialization(id="spec-net", name="Jaringan", deletedAt=None)
    db.add_all([spec_be, spec_net])

    # Periode 07:30 -> 12:30, 6 slot @50 menit
    slots = [
        ("p1", time(7, 30), time(8, 20)),
        ("p2", time(8, 20), time(9, 10)),
        ("p3", time(9, 10), time(10, 0)),
        ("p4", time(10, 0), time(10, 50)),
        ("p5", time(10, 50), time(11, 40)),
        ("p6", time(11, 40), time(12, 30)),
    ]
    for sid, ts, te in slots:
        db.add(Schedule(id=sid, timeStart=ts, timeEnd=te))

    # Ruangan biasa
    db.add(Room(id="r1", name="R101", capacity=40, deletedAt=None, labGroupId=None))
    db.add(Room(id="r2", name="R102", capacity=40, deletedAt=None, labGroupId=None))

    # Lab group + lab
    db.add(LabGroup(id="lg1", name="Lab Jaringan", deletedAt=None))
    db.add(LabSpecialization(id=nid(), labGroupId="lg1", specializationId="spec-net"))
    db.add(Room(id="lab1", name="LAB-NET", capacity=30, deletedAt=None, labGroupId="lg1"))

    # --- Dosen ---
    # Full-time (tidak punya lecturer_schedules sama sekali)
    db.add(Lecturer(id="L-full", name="Andi", religion="ISLAM", isActive=True,
                    isInterdiscipline=False, isMale=True, deletedAt=None, categoryId="cat-if"))
    db.add(LecturerSpecialization(id=nid(), lecturerId="L-full", specializationId="spec-be"))
    db.add(LecturerSpecialization(id=nid(), lecturerId="L-full", specializationId="spec-net"))

    # DLB: hanya SENIN, dan hanya jam p1..p3
    db.add(Lecturer(id="L-dlb", name="Budi", religion="ISLAM", isActive=True,
                    isInterdiscipline=False, isMale=True, deletedAt=None, categoryId="cat-if"))
    db.add(LecturerSpecialization(id=nid(), lecturerId="L-dlb", specializationId="spec-be"))
    ls = LecturerSchedule(id="ls-1", day="MONDAY", lecturerId="L-dlb")
    db.add(ls)
    for sid in ("p1", "p2", "p3"):
        db.add(LecturerScheduleTime(id=nid(), lecturerScheduleId="ls-1", scheduleId=sid))

    # Dosen SOFT-DELETED -> tidak boleh muncul sebagai kandidat
    db.add(Lecturer(id="L-deleted", name="Hantu", religion="ISLAM", isActive=True,
                    isInterdiscipline=False, isMale=True, deletedAt=datetime(2020, 1, 1),
                    categoryId="cat-if"))
    db.add(LecturerSpecialization(id=nid(), lecturerId="L-deleted", specializationId="spec-be"))

    # --- Course ---
    # 2 SKS, non-lab, butuh 2 dosen (main + 1 co-lecturer)
    db.add(Course(id="c-be", name="Pemrograman Web", capacity=30, lecturerCount=2, semester=3,
                  sksCount=2, isActive=True, isInterdiscipline=False, isLab=False, isOdd=True,
                  deletedAt=None, categoryId="cat-if", submajorId=None))
    db.add(CourseSpecialization(id=nid(), courseId="c-be", specializationId="spec-be"))

    # 3 SKS, LAB -> harus jadi 2 entri: teori (2 periode) + lab (1 periode)
    db.add(Course(id="c-net", name="Jaringan Komputer", capacity=30, lecturerCount=1, semester=3,
                  sksCount=3, isActive=True, isInterdiscipline=False, isLab=True, isOdd=True,
                  deletedAt=None, categoryId="cat-if", submajorId=None))
    db.add(CourseSpecialization(id=nid(), courseId="c-net", specializationId="spec-net"))

    # Course SOFT-DELETED -> tidak boleh dijadwalkan
    db.add(Course(id="c-del", name="Course Hantu", capacity=30, lecturerCount=1, semester=3,
                  sksCount=2, isActive=True, isInterdiscipline=False, isLab=False, isOdd=True,
                  deletedAt=datetime(2020, 1, 1), categoryId="cat-if", submajorId=None))
    db.add(CourseSpecialization(id=nid(), courseId="c-del", specializationId="spec-be"))

    # Course semester GENAP -> tidak boleh ikut saat isOdd=True
    db.add(Course(id="c-even", name="Course Genap", capacity=30, lecturerCount=1, semester=4,
                  sksCount=2, isActive=True, isInterdiscipline=False, isLab=False, isOdd=False,
                  deletedAt=None, categoryId="cat-if", submajorId=None))
    db.add(CourseSpecialization(id=nid(), courseId="c-even", specializationId="spec-be"))

    db.commit()
    db.close()


def check(label, cond):
    print(f"{'OK  ' if cond else 'FAIL'}: {label}")
    if not cond:
        raise AssertionError(label)


def run():
    seed()

    result = algo_main.generate_timeline(TIMELINE_ID, True)
    print("\n-- summary --")
    print(result)
    print()

    db = database.SessionLocal()
    cs_rows = db.query(CourseSchedule).all()
    lec_rows = db.query(Lecture).all()
    ll_rows = db.query(LectureLecturer).all()

    print("-- course_schedules --")
    for r in cs_rows:
        print(f"  {r.name:28} day={r.day:9} start={r.scheduleId} sks={r.sksCount} "
              f"isLab={bool(r.isLab)} room={r.roomId}")
    print()

    check("ada baris course_schedules tersimpan", len(cs_rows) > 0)
    check("jumlah lectures == jumlah course_schedules", len(lec_rows) == len(cs_rows))
    check("setiap lecture terikat ke timeline_generation yang benar",
          all(r.timelineGenerationId == TIMELINE_ID for r in lec_rows))

    # Soft-deleted & semester genap tidak boleh muncul
    names = {r.name for r in cs_rows}
    check("course soft-deleted TIDAK dijadwalkan",
          not any("Hantu" in n for n in names))
    check("course semester genap TIDAK dijadwalkan",
          not any("Genap" in n for n in names))

    # Dosen soft-deleted tidak boleh dipakai
    used_lecturers = {r.lecturerId for r in ll_rows}
    check("dosen soft-deleted TIDAK dipakai", "L-deleted" not in used_lecturers)

    # Tepat satu main lecturer per lecture
    by_lecture = {}
    for r in ll_rows:
        by_lecture.setdefault(r.lectureId, []).append(r)
    check("tiap lecture punya TEPAT 1 dosen utama",
          all(sum(1 for x in v if x.isMainLecturer) == 1 for v in by_lecture.values()))

    # lecturerCount=2 -> harus ada co-lecturer untuk Pemrograman Web
    web_cs = [r for r in cs_rows if r.courseId == "c-be"]
    check("Pemrograman Web terjadwal", len(web_cs) == 1)
    web_lecture = next(r for r in lec_rows if r.courseScheduleId == web_cs[0].id)
    web_ll = by_lecture[web_lecture.id]
    check("Pemrograman Web (lecturerCount=2) punya 1 utama + 1 pendamping",
          len(web_ll) == 2 and sum(1 for x in web_ll if not x.isMainLecturer) == 1)

    # sks_count tersimpan sebagai panjang blok
    check("Pemrograman Web sks_count=2 (2 periode)", web_cs[0].sksCount == 2)

    # Course lab 3 SKS -> 2 entri: teori 2 periode + lab 1 periode
    net_cs = [r for r in cs_rows if r.courseId == "c-net"]
    check("Jaringan Komputer menghasilkan 2 entri (teori + lab)", len(net_cs) == 2)
    theory = [r for r in net_cs if not r.isLab]
    lab = [r for r in net_cs if r.isLab]
    check("Jaringan: 1 entri teori & 1 entri lab", len(theory) == 1 and len(lab) == 1)
    check("Jaringan teori = 2 periode (sks 3 - 1 lab)", theory[0].sksCount == 2)
    check("Jaringan lab = 1 periode", lab[0].sksCount == 1)
    check("Jaringan entri lab memakai ruangan lab", lab[0].roomId == "lab1")

    # Pairing: teori & lab course yang sama harus dosen yang sama
    net_lectures = [r for r in lec_rows if r.courseScheduleId in {x.id for x in net_cs}]
    net_mains = {
        next(x.lecturerId for x in by_lecture[l.id] if x.isMainLecturer)
        for l in net_lectures if l.id in by_lecture
    }
    check("teori & lab dari course yang sama diajar dosen yang SAMA", len(net_mains) == 1)

    # Tidak ada bentrok ruangan/dosen di seluruh blok
    order = {"p1": 0, "p2": 1, "p3": 2, "p4": 3, "p5": 4, "p6": 5}
    rev = {v: k for k, v in order.items()}
    room_occupied = set()
    lect_occupied = set()
    conflict = False
    for r in cs_rows:
        start = order[r.scheduleId]
        lecture = next(x for x in lec_rows if x.courseScheduleId == r.id)
        mains = [x.lecturerId for x in by_lecture.get(lecture.id, []) if x.isMainLecturer]
        main_id = mains[0] if mains else None
        for k in range(r.sksCount):
            slot = (r.day, rev[start + k])
            if (r.roomId, slot) in room_occupied:
                print(f"  !! BENTROK RUANGAN {r.roomId} di {slot}")
                conflict = True
            room_occupied.add((r.roomId, slot))
            if main_id is not None:
                if (main_id, slot) in lect_occupied:
                    print(f"  !! BENTROK DOSEN {main_id} di {slot}")
                    conflict = True
                lect_occupied.add((main_id, slot))
    check("tidak ada bentrok ruangan/dosen di SELURUH periode blok", not conflict)

    # DLB hanya boleh kena Senin p1..p3
    for r in cs_rows:
        lecture = next(x for x in lec_rows if x.courseScheduleId == r.id)
        mains = [x.lecturerId for x in by_lecture.get(lecture.id, []) if x.isMainLecturer]
        if mains and mains[0] == "L-dlb":
            start = order[r.scheduleId]
            covered = {rev[start + k] for k in range(r.sksCount)}
            check(f"DLB dijadwalkan Senin saja (dapat {r.day})", r.day == "MONDAY")
            check(f"DLB hanya di jam tersedianya (dapat {sorted(covered)})",
                  covered <= {"p1", "p2", "p3"})

    db.close()

    # --- Idempotensi: generate ulang tidak boleh menumpuk ---
    before = len(cs_rows)
    algo_main.generate_timeline(TIMELINE_ID, True)
    db = database.SessionLocal()
    after_cs = db.query(CourseSchedule).count()
    after_lec = db.query(Lecture).count()
    db.close()
    check(f"generate ulang tidak menumpuk (course_schedules {before} -> {after_cs})",
          after_cs == before)
    check("generate ulang tidak menumpuk lectures", after_lec == before)

    print("\nSEMUA TEST LOLOS.")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    run()
