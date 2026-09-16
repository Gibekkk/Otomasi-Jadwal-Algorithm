"""
models/timeline.py

Model untuk tabel HASIL generate (yang ditulis algoritma), bukan tabel
input akademik:

    course_schedules  -> 1 baris = 1 sesi kelas (course + index) yang sudah
                         dapat hari, jam mulai, dan ruangan.
    lectures          -> 1 baris per course_schedule, menandai sesi itu
                         milik timeline_generation yang mana. Tidak punya
                         kolom lecturer_id -- dosennya ada di tabel
                         lecture_lecturers (many-to-many).
    lecture_lecturers -> 1 baris per dosen yang mengajar di sebuah lecture,
                         dengan flag is_main_lecturer (dosen utama vs
                         co-lecturer/pendamping).

Catatan `course_schedules.sks_count` & `is_lab`: backend Java memakai dua
kolom ini untuk menghitung jam SELESAI sesi dari jam mulainya
(lihat TimelineController#getLectures -> resolveTimeEnd). Jadi satu baris
course_schedules mewakili SATU BLOK penuh (bukan per-jam), dan sks_count
menyatakan blok itu panjangnya berapa periode.
"""

from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ..database import Base

DAY_ENUM = Enum(
    "FRIDAY", "MONDAY", "THURSDAY", "TUESDAY", "WEDNESDAY", name="day_enum"
)


class TimelineGeneration(Base):
    __tablename__ = "timeline_generations"

    id = Column("id", String(255), primary_key=True, index=True)
    academicYear = Column("academic_year", Integer, nullable=False)
    isOdd = Column("is_odd", Boolean, nullable=False)
    generatedBy = Column("generated_by", String(255), nullable=False)


class CourseSchedule(Base):
    __tablename__ = "course_schedules"

    id = Column("id", String(255), primary_key=True, index=True)
    courseIndex = Column("course_index", String(1), nullable=False)
    day = Column("day", DAY_ENUM, nullable=False)
    isLab = Column("is_lab", Boolean, nullable=False)
    name = Column("name", String(50), nullable=False)
    sksCount = Column("sks_count", Integer, nullable=False)

    courseId = Column("course_id", String(255), ForeignKey("courses.id"), nullable=False, index=True)
    roomId = Column("room_id", String(255), ForeignKey("rooms.id"), nullable=False, index=True)
    scheduleId = Column("schedule_id", String(255), ForeignKey("schedules.id"), nullable=False, index=True)

    lectures = relationship("Lecture", backref="courseSchedule")


class Lecture(Base):
    __tablename__ = "lectures"

    id = Column("id", String(255), primary_key=True, index=True)
    fallbackReason = Column("fallback_reason", String, nullable=True)

    courseScheduleId = Column(
        "course_schedule_id", String(255), ForeignKey("course_schedules.id"), nullable=False, index=True
    )
    timelineGenerationId = Column(
        "timeline_generation_id", String(255), ForeignKey("timeline_generations.id"), nullable=False, index=True
    )

    lectureLecturers = relationship("LectureLecturer", backref="lecture")


class LectureLecturer(Base):
    __tablename__ = "lecture_lecturers"

    id = Column("id", String(255), primary_key=True, index=True)
    isMainLecturer = Column("is_main_lecturer", Boolean, nullable=False)

    # Kedua FK ini nullable di skema DB, tapi algoritma selalu mengisi
    # keduanya -- baris tanpa dosen tidak pernah dibuat (sesi tanpa dosen
    # cukup diwakili lectures.fallback_reason).
    lectureId = Column("lecture_id", String(255), ForeignKey("lectures.id"), nullable=True, index=True)
    lecturerId = Column("lecturer_id", String(255), ForeignKey("lecturers.id"), nullable=True, index=True)
