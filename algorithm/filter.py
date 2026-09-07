from sqlalchemy import or_
from sqlalchemy.orm import joinedload

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
        # Opsional tapi SANGAT disarankan: 
        # joinedload memastikan data category dan submajor ditarik sekalian di query ini.
        # Sehingga saat Anda memanggil course.category.name nanti, Python tidak perlu nge-query database lagi.
        joinedload(Course.category),
        joinedload(Course.submajor)
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
        # Opsional: Lakukan Eager Loading jika Anda mendefinisikan relasi 'category' 
        # di dalam model Lecturer Anda.
        # joinedload(Lecturer.category)
    ).all()
    
    return lecturers

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
        LabGroup.deletedAt.is_(None)
    ).options(
        # Tarik semua data relasinya sekaligus (Eager Loading Berantai)
        # Room -> LabGroup -> LabSpecialization -> Specialization
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
    rooms = get_all_rooms(db)
    schedules = db.query(Schedule).all()
    return courses, lecturers, rooms, schedules
