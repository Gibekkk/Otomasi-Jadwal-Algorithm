from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload

# Wajib import semua model yang ada agar SQLAlchemy bisa membaca relasinya
from .models.specialization import *
from .models.category import *
from .models.course import *
from .models.room import *
from .models.lecturer import *
from .models.schedule import *

def get_active_courses(db, isOdd):
    courses = db.query(Course).join(
        Category, Course.categoryId == Category.id
    ).outerjoin(
        Submajor, Course.submajorId == Submajor.id
    ).filter(
        # 1. Filter untuk tabel Course
        Course.deletedAt.is_(None),
        Course.isActive == True,
        Course.isOdd == isOdd,
        
        # 2. Filter untuk tabel Category (Wajib tidak terhapus)
        Category.deletedAt.is_(None),
        
        # 3. Filter untuk tabel Submajor (Boleh kosong, TAPI jika ada, tidak boleh terhapus)
        or_(
            Course.submajorId.is_(None),
            Submajor.deletedAt.is_(None)
        )
    ).options(
        # joinedload memastikan data category dan submajor ditarik sekalian di query ini.
        # Sehingga saat Anda memanggil course.category.name nanti, Python tidak perlu nge-query database lagi.
        joinedload(Course.category),
        joinedload(Course.submajor),
        # WAJIB: grouping.py membaca course.courseSpecializations untuk SETIAP
        # pasangan (course x lecturer). Tanpa eager load, tiap akses memicu
        # query lazy-load terpisah -- klasik N+1, dan jadi penyebab utama
        # lambatnya proses grouping saat datanya banyak.
        selectinload(Course.courseSpecializations)
        .joinedload(CourseSpecialization.specialization),
    ).all()
    
    return courses

def get_active_lecturers(db):
    lecturers = db.query(Lecturer).join(
        Category, Lecturer.categoryId == Category.id
    ).filter(
        # 1. Filter untuk tabel Lecturer (Aktif dan tidak dihapus)
        Lecturer.deletedAt.is_(None),
        Lecturer.isActive == True,
        
        # 2. Filter untuk tabel Category (Wajib tidak terhapus)
        Category.deletedAt.is_(None)
    ).options(
        # Sama seperti course: grouping.py & scheduler membaca
        # lecturer.lecturerSpecializations dan lecturer.lecturerSchedules
        # berkali-kali per dosen. Tanpa eager load ini, tiap akses jadi
        # query terpisah (N+1).
        selectinload(Lecturer.lecturerSpecializations)
        .joinedload(LecturerSpecialization.specialization),
        # lecturerSchedules -> scheduleTimes dipakai untuk mengetahui jam
        # spesifik ketersediaan dosen per hari.
        selectinload(Lecturer.lecturerSchedules)
        .selectinload(LecturerSchedule.scheduleTimes),
    ).all()
    
    return lecturers

def get_active_specializations(db):
    specializations = db.query(Specialization).filter(
        # 1. Filter untuk tabel Specialization (Aktif dan tidak dihapus)
        Specialization.deletedAt.is_(None),
    ).all()
    
    return specializations

def get_regular_rooms(db):
    rooms = db.query(Room).filter(
        Room.deletedAt.is_(None),
        Room.labGroupId.is_(None) # Pastikan bukan Lab
    ).all()
    
    return rooms


def get_labs(db):
    labs = db.query(Room).join(
        LabGroup, Room.labGroupId == LabGroup.id
    ).filter(
        # 1. Filter ruangan belum dihapus dan Tipe-nya adalah Lab
        Room.deletedAt.is_(None),
        Room.labGroupId.is_not(None),
        
        # 2. Pastikan LabGroup (master lab) juga belum dihapus
        LabGroup.deletedAt.is_(None),
        
        # 3. Pastikan labSpecializations TIDAK KOSONG (memiliki minimal 1 relasi)
        LabGroup.labSpecializations.any()
    ).options(
        # Tarik semua data relasinya sekaligus (Eager Loading Berantai)
        joinedload(Room.labGroup)
        .joinedload(LabGroup.labSpecializations)
        .joinedload(LabSpecialization.specialization)
    ).all()
    
    return labs

def get_all_rooms(db):
    rooms = db.query(Room).outerjoin(
        LabGroup, Room.labGroupId == LabGroup.id
    ).filter(
        # 1. Ruangan tidak boleh terhapus
        Room.deletedAt.is_(None),
        
        # 2. Jika dia bukan Lab, loloskan.
        #    Jika dia Lab, pastikan LabGroup-nya tidak terhapus.
        or_(
            Room.labGroupId.is_(None),
            LabGroup.deletedAt.is_(None)
        )
    ).options(
        # Tarik semua relasi labGroup ke bawah. 
        # Untuk ruang biasa, ini otomatis akan diabaikan (karena datanya kosong).
        joinedload(Room.labGroup)
        .joinedload(LabGroup.labSpecializations)
        .joinedload(LabSpecialization.specialization)
    ).all()
    
    return rooms

def filter_data(db, isOdd):
    courses = get_active_courses(db, isOdd)
    lecturers = get_active_lecturers(db)
    rooms = get_regular_rooms(db)
    labs = get_labs(db)
    schedules = db.query(Schedule).all()
    specializations = get_active_specializations(db)
    return courses, lecturers, rooms, labs, schedules, specializations
