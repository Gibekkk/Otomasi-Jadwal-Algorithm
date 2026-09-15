import logging
from collections import defaultdict

from .models.specialization import *
from .models.category import *
from .models.course import *
from .models.room import *
from .models.lecturer import *
from .models.schedule import *
from .lecturer_scheduler import schedule_priority_courses
from .room_scheduler import schedule_non_priority_courses

logger = logging.getLogger("schedule_controller")


def _count_available_lecturers(grouped_course) -> int:
    """Jumlah dosen yang cocok/tersedia untuk grouped_course ini."""
    suitable_lecturers = grouped_course[2]
    return len(suitable_lecturers)


def _split_priority(grouped_courses):
    """
    Memisahkan grouped_courses menjadi tiga kelompok:
    - removal_indexes      : index course yang tidak punya ruangan/lab sama
                              sekali, jadi tidak bisa dijadwalkan.
    - priority_courses     : course yang dosen (kandidat pertamanya) sudah
                              punya jadwal tetap sebelumnya -- harus
                              diprioritaskan supaya tidak bentrok.
    - non_priority_courses : sisanya.
    """
    removal_indexes = []
    priority_courses = []
    non_priority_courses = []

    for index, grouped_course in enumerate(grouped_courses):
        suitable_lecturers = grouped_course[2]
        suitable_rooms_or_labs = grouped_course[3]

        if len(suitable_rooms_or_labs) == 0:
            removal_indexes.append(index)
            continue

        if len(suitable_lecturers) > 0 and len(suitable_lecturers[0][0].lecturerSchedules) > 0:
            priority_courses.append(grouped_course)
            continue

        non_priority_courses.append(grouped_course)

    return removal_indexes, priority_courses, non_priority_courses


def _build_lab_pairs(grouped_courses):
    """
    Mengelompokkan grouped_course berdasarkan (course_id, index).

    Course yang sama pada index yang sama bisa muncul dua kali di
    grouped_courses: satu versi ruangan biasa (isLab=False) dan satu versi
    lab (isLab=True) -- lihat grouping.group_scheduling_data() (course lab
    dengan sksCount > 1) dan splitter.split_room_course(). Keduanya
    "sepaket": harus diajar oleh dosen yang sama.

    Return dict {(course_id, index): [grouped_course, ...]} untuk lookup
    pasangannya.
    """
    pairs = defaultdict(list)
    for grouped_course in grouped_courses:
        course = grouped_course[0]
        course_index = grouped_course[1]
        pairs[(course.id, course_index)].append(grouped_course)
    return pairs


def _get_paired_entry(grouped_course, lab_pairs):
    """
    Mengambil pasangan lab/non-lab dari grouped_course (course & index yang
    sama), kalau ada. Return None kalau course ini berdiri sendiri (tidak
    ada versi lab/ruangan lainnya).
    """
    course = grouped_course[0]
    course_index = grouped_course[1]
    for sibling in lab_pairs[(course.id, course_index)]:
        if sibling is not grouped_course:
            return sibling
    return None


def _grouped_courses_to_entries(grouped_courses):
    """
    Mengubah grouped_course (list [course, index, lecturers, rooms, isLab])
    jadi representasi dict yang dipakai module 3 (lecturer_scheduler) dan
    module 4 (room_scheduler) untuk assignment. `paired_with` belum diisi
    di sini -- lihat _attach_pairs(). `assignment` diisi None dulu, nanti
    diisi module 3/4 begitu course ini berhasil dijadwalkan -- field ini
    yang dipakai kedua module untuk saling tahu course mana yang sudah
    selesai diproses (lihat scheduling_common.resolve_forced_lecturer_id).

    Sengaja dibangun sebagai objek terpisah (bukan menyisipkan field baru
    ke list grouped_course itu sendiri) supaya struktur
    [course, index, lecturers, rooms, isLab] yang dipakai bagian lain
    (mis. main.display_grouped_courses) tidak berubah/rusak.
    """
    entries = []
    for grouped_course in grouped_courses:
        course, course_index, suitable_lecturers, suitable_rooms_or_labs, isLab = grouped_course
        entries.append({
            "course": course,
            "index": course_index,
            "isLab": isLab,
            "suitable_lecturers": suitable_lecturers,
            "suitable_rooms_or_labs": suitable_rooms_or_labs,
            "paired_with": None,
            "assignment": None,
        })
    return entries


def _attach_pairs(grouped_courses, entries, lab_pairs):
    """
    Mengisi field `paired_with` tiap entry dengan entry dict pasangannya
    (versi lab/non-lab dari course+index yang sama), kalau ada.

    `grouped_courses` & `entries` harus urutan & panjangnya sama
    (index-matched, hasil dari _grouped_courses_to_entries di atas).
    """
    entry_by_grouped_course_id = {
        id(grouped_course): entry
        for grouped_course, entry in zip(grouped_courses, entries)
    }
    for grouped_course, entry in zip(grouped_courses, entries):
        paired_grouped_course = _get_paired_entry(grouped_course, lab_pairs)
        if paired_grouped_course is not None:
            entry["paired_with"] = entry_by_grouped_course_id.get(id(paired_grouped_course))


def plan_schedules(
    grouped_courses,
    schedules: list["Schedule"]
):
    removal_indexes, priority_courses, non_priority_courses = _split_priority(grouped_courses)

    if removal_indexes:
        logger.warning(
            "Melewati %d entri course karena tidak ada ruangan/lab yang cocok: %s",
            len(removal_indexes), removal_indexes,
        )

    # 1) Sortir dari jumlah lecturers yang tersedia paling sedikit
    #    (most-constrained-first). Course yang pilihan dosennya paling
    #    sedikit diproses lebih dulu, supaya dosennya tidak keburu terpakai
    #    oleh course lain yang sebenarnya masih punya banyak alternatif
    #    dosen lain.
    priority_courses.sort(key=_count_available_lecturers)
    non_priority_courses.sort(key=_count_available_lecturers)

    # 2) Tandai pasangan lab & non-lab dari course + index yang sama, biar
    #    module 3 & 4 tahu keduanya harus "sepaket" dengan dosen yang sama.
    #    Pairing dibangun dari gabungan priority + non_priority sekaligus,
    #    karena pasangan sebuah course bisa saja jatuh di kelompok yang
    #    berbeda (mis. versi ruangan masuk priority, versi lab masuk
    #    non_priority) -- dengan begitu `entry["paired_with"]` selalu
    #    merujuk ke objek dict yang sama persis dengan yang ada di list
    #    priority_entries / non_priority_entries, bukan salinan.
    all_courses = priority_courses + non_priority_courses
    lab_pairs = _build_lab_pairs(all_courses)

    all_entries = _grouped_courses_to_entries(all_courses)
    _attach_pairs(all_courses, all_entries, lab_pairs)

    priority_entries = all_entries[:len(priority_courses)]
    non_priority_entries = all_entries[len(priority_courses):]

    # 3) Habiskan priority_courses dulu (module 3: cari dosen -> slot ->
    #    ruangan).
    assigned_priority, unscheduled_priority, state = schedule_priority_courses(
        priority_entries, schedules
    )

    # 4) Baru proses non_priority_courses (module 4: cari ruangan -> slot
    #    -> dosen). `state` dioper LANJUT dari module 3 (objek yang sama,
    #    bukan yang baru) supaya slot yang sudah dipakai priority_courses
    #    tidak ditabrak di sini -- inilah bentuk "awareness" module 3 & 4
    #    terhadap jadwal yang sudah terpakai. Entry yang kebetulan sudah
    #    ke-assign lewat pairing dari module 3 otomatis dilewati oleh
    #    module 4 (lihat room_scheduler.schedule_non_priority_courses).
    assigned_non_priority, unscheduled_non_priority, state = schedule_non_priority_courses(
        non_priority_entries, schedules, state=state
    )

    course_schedules = assigned_priority + assigned_non_priority
    unscheduled = unscheduled_priority + unscheduled_non_priority

    # TODO(module berikutnya): tangani `unscheduled` di sini lewat re-split
    # ruangan/lab (module 3/splitter.py) atau re-grouping dosen (module
    # 2/grouping.py) untuk course yang masih gagal dijadwalkan, lalu ulangi
    # module 3 & 4 untuk sisa course tsb selama `state` yang sama.
    logger.info(
        "Module 5 selesai: %d unit penjadwalan berhasil (%d dari priority, %d dari non-priority), "
        "%d gagal dijadwalkan.",
        len(course_schedules), len(assigned_priority), len(assigned_non_priority), len(unscheduled),
    )

    return {
        "course_schedules": course_schedules,
        "unscheduled": unscheduled,
        "state": state,
    }
