import logging
from collections import defaultdict
from math import floor

from .models.specialization import *
from .models.category import *
from .models.course import *
from .models.room import *
from .models.lecturer import *
from .models.schedule import *

logger = logging.getLogger("splitter")
tolerance_percentation = 10
indexes = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 
           'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']

def split_room_course(
    course: "Course",
    rooms: list["Room"],
    suitable_labs,
):
    resulted_courses = []
    target = course.capacity
    capacity_covered_room = 0
    capacity_covered_lab = 0
    capacity_covered_room_tolerance = 0
    split_count = 0
    expecting_lab = course.isLab
    expecting_room = (course.isLab and course.sksCount > 1) or not course.isLab
    suitable_labs.sort(key=lambda l: (l[1], l[0].capacity), reverse=True)
    rooms.sort(key=lambda r:r.capacity, reverse = True)

    while target > capacity_covered_room and target > capacity_covered_room_tolerance and expecting_room and not expecting_lab :
        current_room, currrent_capacity = rooms[0], rooms[0].capacity
        for room in rooms:
            if (currrent_capacity > (target - capacity_covered_room)) or (currrent_capacity > (target - capacity_covered_room_tolerance)):
                current_room, currrent_capacity = room, room.capacity
            else:
                break
        
        inserted_room = [(current_room, 0)]
        resulted_courses.append([course, indexes[split_count], inserted_room, False])
        capacity_covered_room += currrent_capacity
        capacity_covered_room_tolerance += floor(currrent_capacity + (currrent_capacity * tolerance_percentation / 100))
        split_count += 1
        
    while target > capacity_covered_lab and expecting_lab:
        current_room, current_capacity, lab_priority = suitable_labs[0][0], suitable_labs[0][0].capacity, suitable_labs[0][1]
        biggest_room_capacity = floor(rooms[0].capacity + (rooms[0].capacity * tolerance_percentation / 100))
        lab_capacity = current_capacity if current_capacity < biggest_room_capacity else biggest_room_capacity
        for lab in suitable_labs:
            if (current_capacity > (target - capacity_covered_lab)):
                current_room, current_capacity, lab_priority = lab[0], lab[0].capacity, lab[1]
            else:
                break
            
        inserted_room = [(current_room, 0, lab_priority)]
        resulted_courses.append([course, indexes[split_count], inserted_room, True])
        lab_capacity = current_capacity if current_capacity < biggest_room_capacity else biggest_room_capacity
        
        if expecting_room:
            current_room, current_capacity = rooms[0], rooms[0].capacity
            for room in rooms:
                if current_capacity > lab_capacity:
                    current_room, current_capacity = room, room.capacity
                else:
                    break
                
            inserted_room = [(current_room, 0)]
            resulted_courses.append([course, indexes[split_count], inserted_room, False])
        capacity_covered_lab += lab_capacity
        split_count += 1
        
    return resulted_courses
                
    