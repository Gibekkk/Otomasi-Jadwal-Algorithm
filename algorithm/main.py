import sys
import os

# Menyesuaikan path agar bisa mengimpor file dari luar folder
current_dir = os.path.dirname(os.path.abspath(__file__))
target_dir = os.path.abspath(os.path.join(current_dir, "../"))
sys.path.append(target_dir)

from .database import SessionLocal

from .filter import *
from .grouping import *


def display_grouped_courses(grouped_course):
    """
    Menampilkan hasil grouped_course ke console dengan format yang mudah dibaca.

    Setiap item pada grouped_course selalu berbentuk:
        [course, index, suitable_lecturers, suitable_rooms_or_labs, isLab]

    - suitable_lecturers     : list of (lecturer, priority_rate)
    - suitable_rooms_or_labs : bisa berupa dua bentuk berbeda, tergantung apakah
      course berhasil dikelompokkan langsung ke beberapa opsi ruangan/lab,
      atau sudah terpilih satu ruangan/lab tertentu (mis. hasil dari
      algorithm/splitter.py):
        1. list of (room, priority_rate)               -> jika bukan lab
           list of (lab, priority_rate, priority_rate_lab) -> jika lab
        2. objek Room/lab tunggal (bukan list)          -> satu ruangan/lab
           yang sudah terpilih untuk course tersebut
    """
    if not grouped_course:
        print("Tidak ada grouped course yang dihasilkan.")
        return

    print("\n" + "=" * 60)
    print(f"HASIL GROUPED COURSES ({len(grouped_course)} entri)")
    print("=" * 60)

    for i, entry in enumerate(grouped_course, start=1):
        course, index, suitable_lecturers, suitable_rooms_or_labs, isLab = entry

        print(f"\n[{i}] {course.name} ({index}) - {'Lab' if isLab else 'Regular'}")
        print(f"    Kapasitas dibutuhkan  : {course.capacity}")

        if suitable_lecturers:
            lecturer_str = ", ".join(
                f"{lecturer.name} (prio: {priority})"
                for lecturer, priority in suitable_lecturers
            )
            print(f"    Dosen yang cocok      : {lecturer_str}")
        else:
            print("    Dosen yang cocok      : -")

        if isinstance(suitable_rooms_or_labs, list):
            # Beberapa opsi ruangan/lab, masing-masing dengan skor prioritas
            if suitable_rooms_or_labs:
                if isLab:
                    room_str = ", ".join(
                        f"{room.name} (prio: {priority}, prio_lab: {priority_lab})"
                        for room, priority, priority_lab in suitable_rooms_or_labs
                    )
                    label = "Lab yang cocok        "
                else:
                    room_str = ", ".join(
                        f"{room.name} (prio: {priority})"
                        for room, priority in suitable_rooms_or_labs
                    )
                    label = "Ruangan yang cocok    "
                print(f"    {label}: {room_str}")
            else:
                print("    Ruangan/Lab yang cocok: -")
        else:
            # Satu ruangan/lab yang sudah terpilih langsung untuk course ini
            room = suitable_rooms_or_labs
            label = "Lab terpilih          " if isLab else "Ruangan terpilih      "
            print(f"    {label}: {room.name} (kapasitas: {room.capacity})")

    print("\n" + "=" * 60)


def generate_timeline(timeline_generation_id, isOdd):
    print(timeline_generation_id)
    print(isOdd)
    db = SessionLocal()

    try:
        courses, lecturers, rooms, labs, schedules, specializations = filter_data(db, isOdd)
        grouped_course = group_scheduling_data(courses, lecturers, rooms, labs, schedules, specializations)
        print(len(grouped_course), "Groups")

        display_grouped_courses(grouped_course)

    except Exception as e:
        print(f"Terjadi kesalahan saat pemrosesan data: {e}")

    finally:
        db.close()

if __name__ == "__main__":
    generate_timeline("generation_id_example", True)