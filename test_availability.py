"""
Test terfokus untuk dua perilaku yang baru:

1. Ketersediaan dosen dibaca sampai level JAM (lecturer_schedules_time),
   bukan cuma per-hari. Dosen DLB yang cuma tersedia Selasa p4-p6 tidak
   boleh dijadwalkan di hari/jam lain.

2. Course yang tidak mungkin dijadwalkan (blok lebih panjang dari jumlah
   periode yang tersedia) TIDAK disimpan sebagai baris course_schedules
   setengah jadi -- hanya dilaporkan lewat unscheduled_count.

    python test_availability.py
"""

import os
import uuid
from datetime import time

os.environ.setdefault("DB_USER", "x")
os.environ.setdefault("DB_PASS", "x")
os.environ.setdefault("DB_HOST", "x")
os.environ.setdefault("DB_PORT", "3306")
os.environ.setdefault("DB_NAME", "x")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import algorithm.database as database

test_engine = create_engine("sqlite://")
database.engine = test_engine
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

from algorithm.database import Base  # noqa: E402
from algorithm.models.category import Category  # noqa: E402
from algorithm.models.course import Course, CourseSpecialization  # noqa: E402
from algorithm.models.lecturer import (  # noqa: E402
    Lecturer, LecturerSchedule, LecturerScheduleTime, LecturerSpecialization,
)
from algorithm.models.room import Room  # noqa: E402
from algorithm.models.schedule import Schedule  # noqa: E402
from algorithm.models.specialization import Specialization  # noqa: E402
from algorithm.models.timeline import (  # noqa: E402
    CourseSchedule, Lecture, LectureLecturer, TimelineGeneration,
)
from algorithm import main as algo_main  # noqa: E402

TIMELINE_ID = "tg-av"
SLOTS = [("p1", 7, 30), ("p2", 8, 20), ("p3", 9, 10),
         ("p4", 10, 0), ("p5", 10, 50), ("p6", 11, 40)]


def nid():
    return str(uuid.uuid4())


def check(label, cond):
    print(f"{'OK  ' if cond else 'FAIL'}: {label}")
    if not cond:
        raise AssertionError(label)


def seed():
    Base.metadata.create_all(test_engine)
    db = database.SessionLocal()
    db.add(TimelineGeneration(id=TIMELINE_ID, academicYear=2026, isOdd=True, generatedBy="u1"))
    db.add(Category(id="cat-if", name="Informatika", isProdi=True, deletedAt=None))
    db.add(Specialization(id="spec-be", name="Backend", deletedAt=None))

    for sid, h, m in SLOTS:
        end_h, end_m = (h, m + 50) if m + 50 < 60 else (h + 1, m + 50 - 60)
        db.add(Schedule(id=sid, timeStart=time(h, m), timeEnd=time(end_h, end_m)))

    db.add(Room(id="r1", name="R101", capacity=40, deletedAt=None, labGroupId=None))

    # SATU-SATUNYA dosen: DLB, hanya SELASA, hanya jam p4 & p5.
    db.add(Lecturer(id="L-dlb", name="Budi", religion="ISLAM", isActive=True,
                    isInterdiscipline=False, isMale=True, deletedAt=None, categoryId="cat-if"))
    db.add(LecturerSpecialization(id=nid(), lecturerId="L-dlb", specializationId="spec-be"))
    ls = LecturerSchedule(id="ls-1", day="TUESDAY", lecturerId="L-dlb")
    db.add(ls)
    for sid in ("p4", "p5"):
        db.add(LecturerScheduleTime(id=nid(), lecturerScheduleId="ls-1", scheduleId=sid))

    # Course 2 SKS -> blok 2 periode, satu-satunya yang muat adalah Selasa p4-p5.
    db.add(Course(id="c-fit", name="Muat Pas", capacity=30, lecturerCount=1, semester=3,
                  sksCount=2, isActive=True, isInterdiscipline=False, isLab=False, isOdd=True,
                  deletedAt=None, categoryId="cat-if", submajorId=None))
    db.add(CourseSpecialization(id=nid(), courseId="c-fit", specializationId="spec-be"))

    db.commit()
    db.close()


def run():
    seed()
    result = algo_main.generate_timeline(TIMELINE_ID, True)
    print("\nsummary:", result, "\n")

    db = database.SessionLocal()
    cs_rows = db.query(CourseSchedule).all()
    lec_rows = db.query(Lecture).all()
    ll_rows = db.query(LectureLecturer).all()

    for r in cs_rows:
        print(f"  {r.name:14} day={r.day:9} start={r.scheduleId} sks={r.sksCount} room={r.roomId}")
    print()

    check("course terjadwal", len(cs_rows) == 1)
    row = cs_rows[0]
    check("dijadwalkan di hari ketersediaan DLB (SELASA)", row.day == "TUESDAY")
    check("dijadwalkan mulai p4 (bukan p1) -- jam dihormati", row.scheduleId == "p4")
    check("blok 2 periode", row.sksCount == 2)
    check("dosen DLB terpasang sebagai utama",
          len(ll_rows) == 1 and ll_rows[0].lecturerId == "L-dlb" and ll_rows[0].isMainLecturer)
    db.close()

    # --- Bagian 2: course yang mustahil dijadwalkan ---
    db = database.SessionLocal()
    db.add(Course(id="c-huge", name="Terlalu Panjang", capacity=30, lecturerCount=1, semester=3,
                  sksCount=99, isActive=True, isInterdiscipline=False, isLab=False, isOdd=True,
                  deletedAt=None, categoryId="cat-if", submajorId=None))
    db.add(CourseSpecialization(id=nid(), courseId="c-huge", specializationId="spec-be"))
    db.commit()
    db.close()

    result2 = algo_main.generate_timeline(TIMELINE_ID, True)
    print("\nsummary (dengan course mustahil):", result2, "\n")

    db = database.SessionLocal()
    names = {r.name for r in db.query(CourseSchedule).all()}
    db.close()

    check("course yang mustahil dijadwalkan dilaporkan sebagai unscheduled",
          result2["unscheduled_count"] >= 1)
    check("course mustahil TIDAK disimpan sebagai baris course_schedules",
          not any("Terlalu Panjang" in n for n in names))
    check("course yang valid tetap tersimpan", any("Muat Pas" in n for n in names))

    print("\nSEMUA TEST LOLOS.")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")
    run()
