import logging
from collections import defaultdict
from math import floor

from .models.specialization import *
from .models.category import *
from .models.course import *
from .models.room import *
from .models.lecturer import *
from .models.schedule import *
from .splitter import *

logger = logging.getLogger("grouping")

# Lecturer Grouping Logic
def count_lecturer_specializations_priority(course_specializations, lecturer_specializations) -> int:
    target = len(course_specializations)
    suitable_specializations_count = len([spec for spec in course_specializations if spec in lecturer_specializations])
    match = suitable_specializations_count / target * 100 if target > 0 else 0
    return floor(match)

def set_lecturer_priority_rates(course: "Course", lecturer: "Lecturer", isInterdiciplinary: bool) -> int:
    course_specializations = [cs.specialization for cs in course.courseSpecializations]
    lecturer_specializations = [ls.specialization for ls in lecturer.lecturerSpecializations]
    if not any(spec in course_specializations for spec in lecturer_specializations):
        return 0
    else:
        priority_rate = 0
        priority_rate += count_lecturer_specializations_priority(course_specializations, lecturer_specializations)
        if len(lecturer.lecturerSchedules) > 0: priority_rate += 1
        if isInterdiciplinary: priority_rate *= -1
        return int(priority_rate)


# Room Grouping Logic
def set_room_priority_rates(course: "Course", room: "Room") -> int:
    priority_rate = 0
    priority_rate += (course.capacity - room.capacity)
    return int(priority_rate)


# Lab Grouping Logic
def count_lab_specializations_priority(course_specializations, lab_specializations) -> int:
    suitable_specializations_count = len([spec for spec in course_specializations if spec in lab_specializations])
    match = suitable_specializations_count - len(lab_specializations)
    return int(match)

def set_lab_priority_rates(course: "Course", lab: "Room", specializations_count: int) -> int:
    course_specializations = [cs.specialization for cs in course.courseSpecializations]
    lab_specializations = [ls.specialization for ls in lab.labGroup.labSpecializations]
    if not any(spec in course_specializations for spec in lab_specializations):
        return 0
    else:
        priority_rate = specializations_count
        priority_rate += count_lab_specializations_priority(course_specializations, lab_specializations)
        return int(priority_rate)


# Main Function
def group_scheduling_data(
    courses: list["Course"],
    lecturers: list["Lecturer"],
    rooms: list["Room"],
    labs: list["Room"],
    specializations: list["Specialization"],
):
    if not courses:
        logger.warning("No courses available for grouping.")
        return
    if not lecturers:
        logger.warning("No lecturers available for grouping.")
        return
    if not rooms:
        logger.warning("No rooms available for grouping.")
        return
    
    grouped_courses = []
    for course in courses:
        suitable_lecturers = []
        suitable_rooms = []
        suitable_labs_by_specialization = []
        suitable_labs = []
        expected_room = False
        expected_lab = False
        index = "A"
        
        for lecturer in lecturers:
            isInterdiciplinary = lecturer.categoryId != course.categoryId and lecturer.isInterdiscipline
            priority_rate = set_lecturer_priority_rates(course, lecturer, isInterdiciplinary)
            if priority_rate == 0:
                continue
            else:
                suitable_lecturers.append((lecturer, priority_rate))
        
        if (course.isLab and course.sksCount > 1) or not course.isLab:
            expected_room = True
            for room in rooms:
                if room.capacity < course.capacity:
                    continue
                else:
                    priority_rate = set_room_priority_rates(course, room)
                    suitable_rooms.append((room, priority_rate))
            if len(suitable_rooms) > 0:
                grouped_courses.append([course, index, suitable_lecturers, suitable_rooms, False])
        
        if course.isLab:
            expected_lab = True
            for lab in labs:
                priority_rate_lab = set_lab_priority_rates(course, lab, len(specializations))
                if priority_rate_lab == 0:
                    continue
                else:
                    suitable_labs_by_specialization.append((lab, priority_rate_lab))
                    
                if lab.capacity < course.capacity:
                    continue
                else:
                    priority_rate = set_room_priority_rates(course, lab)
                    suitable_labs.append((lab, priority_rate, priority_rate_lab))
            if len(suitable_labs) > 0:
                grouped_courses.append([course, index, suitable_lecturers, suitable_labs, True])
        
        # print(f"Course: {course.name} ({"Lab" if course.isLab else "Regular"}), Suitable Lecturers: {[f'{lecturer.name} ({priority_rate})' for lecturer, priority_rate in suitable_lecturers]}, Suitable Rooms: {[f'{room.name} ({priority_rate})' for room, priority_rate in suitable_rooms]} ({'Expected' if expected_room else 'Not Expected'}), Suitable Labs: {[f'{lab.name} ({priority_rate}, {priority_rate_lab})' for lab, priority_rate, priority_rate_lab in suitable_labs]} ({'Expected' if expected_lab else 'Not Expected'})")
        if (expected_room and not suitable_rooms) or (expected_lab and not suitable_labs):
            if not (expected_lab and not suitable_labs_by_specialization):
                split_courses = split_room_course(course, rooms, suitable_labs_by_specialization)
                for split_course in split_courses:
                    split_course_course, split_course_index, split_course_room, isLab = split_course
                    grouped_courses.append([split_course_course, split_course_index, suitable_lecturers, split_course_room, isLab])
            else:
                logger.warning(f"Course {course.name} has no suitable rooms or labs available. It will be removed from scheduling.")
            
    return grouped_courses