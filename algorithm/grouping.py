import logging
from math import floor

from .models.specialization import *
from .models.category import *
from .models.course import *
from .models.room import *
from .models.lecturer import *
from .models.schedule import *
from .splitter import *

logger = logging.getLogger("grouping")


# ---------------------------------------------------------------------------
# Precompute spesialisasi
# ---------------------------------------------------------------------------
# Versi sebelumnya membangun ulang list spesialisasi course DAN dosen di
# dalam set_lecturer_priority_rates(), yang dipanggil untuk SETIAP pasangan
# (course x dosen) -- jadi list yang sama dibangun ribuan kali, lalu dicek
# dengan `spec in list` yang O(n). Di sini semuanya dihitung SEKALI di awal
# sebagai set of specialization_id, sehingga pengecekan irisan jadi operasi
# set O(1) rata-rata.
#
# Memakai ID (bukan objek ORM Specialization) juga membuat perbandingan
# tidak lagi bergantung pada identity-map SQLAlchemy.
# ---------------------------------------------------------------------------

def _course_specialization_ids(course) -> set:
    return {cs.specializationId for cs in course.courseSpecializations}


def _lecturer_specialization_ids(lecturer) -> set:
    return {ls.specializationId for ls in lecturer.lecturerSpecializations}


def _lab_specialization_ids(lab) -> set:
    if lab.labGroup is None:
        return set()
    return {ls.specializationId for ls in lab.labGroup.labSpecializations}


# Lecturer Grouping Logic
def count_lecturer_specializations_priority(course_spec_ids: set, lecturer_spec_ids: set) -> int:
    target = len(course_spec_ids)
    if target == 0:
        return 0
    suitable_specializations_count = len(course_spec_ids & lecturer_spec_ids)
    return floor(suitable_specializations_count / target * 100)


def set_lecturer_priority_rates(course_spec_ids: set, lecturer, lecturer_spec_ids: set, isInterdiciplinary: bool) -> int:
    if not (course_spec_ids & lecturer_spec_ids):
        return 0
    priority_rate = count_lecturer_specializations_priority(course_spec_ids, lecturer_spec_ids)
    if len(lecturer.lecturerSchedules) > 0:
        priority_rate += 1
    if isInterdiciplinary:
        priority_rate *= -1
    return int(priority_rate)


# Room Grouping Logic
def set_room_priority_rates(course: "Course", room: "Room") -> int:
    return int(course.capacity - room.capacity)


# Lab Grouping Logic
def count_lab_specializations_priority(course_spec_ids: set, lab_spec_ids: set) -> int:
    return int(len(course_spec_ids & lab_spec_ids) - len(lab_spec_ids))


def set_lab_priority_rates(course_spec_ids: set, lab_spec_ids: set, specializations_count: int) -> int:
    if not (course_spec_ids & lab_spec_ids):
        return 0
    priority_rate = specializations_count
    priority_rate += count_lab_specializations_priority(course_spec_ids, lab_spec_ids)
    return int(priority_rate)


# Main Function
def group_scheduling_data(
    courses: list["Course"],
    lecturers: list["Lecturer"],
    rooms: list["Room"],
    labs: list["Room"],
    specializations: list["Specialization"],
):
    """
    Untuk tiap course, hitung kandidat dosen & ruangan/lab beserta skor
    kecocokannya. Return list of
    [course, index, suitable_lecturers, suitable_rooms_or_labs, isLab].

    Mengembalikan list KOSONG (bukan None) kalau tidak ada data yang bisa
    diproses -- pemanggilnya mengiterasi hasil ini, jadi None akan bikin
    TypeError di main.py.
    """
    if not courses:
        logger.warning("No courses available for grouping.")
        return []
    if not lecturers:
        logger.warning("No lecturers available for grouping.")
        return []
    if not rooms:
        logger.warning("No rooms available for grouping.")
        return []

    # Precompute sekali untuk semua dosen & lab, dipakai ulang di seluruh
    # loop course.
    lecturer_spec_cache = {lecturer.id: _lecturer_specialization_ids(lecturer) for lecturer in lecturers}
    lab_spec_cache = {lab.id: _lab_specialization_ids(lab) for lab in labs}
    specializations_count = len(specializations)

    grouped_courses = []
    for course in courses:
        course_spec_ids = _course_specialization_ids(course)

        suitable_lecturers = []
        suitable_rooms = []
        suitable_labs_by_specialization = []
        suitable_labs = []
        expected_room = False
        expected_lab = False
        index = "A"

        for lecturer in lecturers:
            isInterdiciplinary = lecturer.categoryId != course.categoryId and lecturer.isInterdiscipline
            priority_rate = set_lecturer_priority_rates(
                course_spec_ids, lecturer, lecturer_spec_cache[lecturer.id], isInterdiciplinary
            )
            if priority_rate == 0:
                continue
            suitable_lecturers.append((lecturer, priority_rate))

        if (course.isLab and course.sksCount > 1) or not course.isLab:
            expected_room = True
            for room in rooms:
                if room.capacity < course.capacity:
                    continue
                suitable_rooms.append((room, set_room_priority_rates(course, room)))
            if len(suitable_rooms) > 0:
                grouped_courses.append([course, index, suitable_lecturers, suitable_rooms, False])

        if course.isLab:
            expected_lab = True
            for lab in labs:
                priority_rate_lab = set_lab_priority_rates(
                    course_spec_ids, lab_spec_cache[lab.id], specializations_count
                )
                if priority_rate_lab == 0:
                    continue
                suitable_labs_by_specialization.append((lab, priority_rate_lab))

                if lab.capacity < course.capacity:
                    continue
                suitable_labs.append((lab, set_room_priority_rates(course, lab), priority_rate_lab))
            if len(suitable_labs) > 0:
                grouped_courses.append([course, index, suitable_lecturers, suitable_labs, True])

        if (expected_room and not suitable_rooms) or (expected_lab and not suitable_labs):
            if not (expected_lab and not suitable_labs_by_specialization):
                split_courses = split_room_course(course, rooms, suitable_labs_by_specialization)
                for split_course in split_courses:
                    split_course_course, split_course_index, split_course_room, isLab = split_course
                    grouped_courses.append(
                        [split_course_course, split_course_index, suitable_lecturers, split_course_room, isLab]
                    )
            else:
                logger.warning(
                    "Course %s has no suitable rooms or labs available. It will be removed from scheduling.",
                    course.name,
                )

    return grouped_courses
