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
        courses, lecturers, rooms, schedules = filter_data(db, isOdd)
        print(group_scheduling_data(courses, lecturers, rooms, schedules))

    except Exception as e:
        print(f"Terjadi kesalahan saat pemrosesan data: {e}")
        
    finally:
        db.close()

if __name__ == "__main__":
    generate_timeline("generation_id_example", True)