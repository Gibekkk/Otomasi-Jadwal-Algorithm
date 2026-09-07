# grouping.py

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models.course import Course
    from .models.lecturer import Lecturer
    from .models.room import Room

logger = logging.getLogger("grouping")


def group_scheduling_data(
    courses: list["Course"],
    lecturers: list["Lecturer"],
    rooms: list["Room"],
    schedules: list[dict],
) -> dict:
    """
    Transforms SQLAlchemy ORM objects (Course, Lecturer, Room -- loaded with
    their relationships, e.g. via db.query(Course).all()) into a grouped map
    keyed by course_id.

    Specialization data is read straight off the ORM relationships:
      - course.courseSpecializations
      - lecturer.lecturerSpecializations
      - room.labGroup.labSpecializations
    so there's no need to pass in separate join-table lists.

    lecturer_availabilities and schedules are still plain dicts (e.g. from a
    raw DictCursor/Core query), since there's no ORM model for them yet.
    Expected keys: 'lecturer_id', 'day', 'schedule_id' / 'id'.
    """

    # 1. Build O(1) lookup tables
    lecturer_avail_map = defaultdict(list)

    # 2. Main Grouping Logic
    grouped_data = {}

    for course in courses:
        c_id = course.id
        c_specs = {cs.specializationId for cs in course.courseSpecializations}

        is_lab_course = bool(course.isLab)
        is_interdiscipline_course = bool(course.isInterdiscipline)

        # -- A. Map Eligible Rooms --
        eligible_rooms = []
        for room in rooms:
            if room.capacity < course.capacity:
                continue  # Skip rooms that are too small

            if is_lab_course:
                if room.labGroup is None:
                    continue

                # Check if the room's lab group supports ANY of the course's specializations
                room_lab_specs = {
                    ls.specializationId for ls in room.labGroup.labSpecializations
                }

                if c_specs & room_lab_specs:
                    eligible_rooms.append(room)
            else:
                # Standard theory courses need rooms WITHOUT a lab group
                if room.labGroup is None:
                    eligible_rooms.append(room)

        # -- B. Map Eligible Lecturers --
        eligible_lecturers = []
        for lecturer in lecturers:
            is_l_interdiscipline = bool(lecturer.isInterdiscipline)

            # Must match category OR both must allow interdiscipline
            match_category = lecturer.categoryId == course.categoryId
            match_inter = is_interdiscipline_course and is_l_interdiscipline

            if match_category or match_inter:
                l_specs = {
                    ls.specializationId for ls in lecturer.lecturerSpecializations
                }

                # If course requires specializations, lecturer must possess AT LEAST ONE
                matched_specs = c_specs & l_specs
                has_matching_spec = bool(matched_specs) if c_specs else True

                if has_matching_spec:
                    eligible_lecturers.append({
                        "lecturer_id": lecturer.id,
                        "name": lecturer.name,
                        "matched_specializations": list(matched_specs),
                        "available_timeslots": lecturer_avail_map.get(lecturer.id, []),
                    })

        # -- C. Final Payload Assembly --
        grouped_data[c_id] = {
            "course": course,
            "required_specializations": list(c_specs),
            "eligible_rooms": eligible_rooms,
            "eligible_lecturers": eligible_lecturers,
        }

    return grouped_data