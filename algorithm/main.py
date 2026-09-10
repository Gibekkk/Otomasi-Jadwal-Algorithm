import sys
import os

# Menyesuaikan path agar bisa mengimpor file dari luar folder
current_dir = os.path.dirname(os.path.abspath(__file__))
target_dir = os.path.abspath(os.path.join(current_dir, "../"))
sys.path.append(target_dir)

from .database import SessionLocal

from .filter import *
from .grouping import *

def generate_timeline(timeline_generation_id, isOdd):
    print(timeline_generation_id)
    print(isOdd)
    db = SessionLocal()
    
    try:
        courses, lecturers, rooms, labs, schedules, specializations = filter_data(db, isOdd)
        grouped_course = group_scheduling_data(courses, lecturers, rooms, labs, schedules, specializations)
        print(len(grouped_course), "Groups")

    except Exception as e:
        print(f"Terjadi kesalahan saat pemrosesan data: {e}")
        
    finally:
        db.close()

if __name__ == "__main__":
    generate_timeline("generation_id_example", True)