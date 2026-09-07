from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from ..database import Base

class LecturerSchedule(Base):
    __tablename__ = "lecturer_schedules"

    id = Column("id", String(255), primary_key=True, index=True)
    
    # Enum untuk hari sesuai dengan database
    day = Column(
        "day", 
        Enum('FRIDAY','MONDAY','THURSDAY','TUESDAY','WEDNESDAY', name="day_enum"), 
        nullable=False
    )
    
    # Foreign Key ke Lecturer
    lecturerId = Column("lecturer_id", String(255), ForeignKey("lecturers.id"), nullable=False, index=True)

class LecturerSpecialization(Base):
    __tablename__ = "lecturer_specializations"

    id = Column("id", String(255), primary_key=True, index=True)
    
    # Foreign Keys
    lecturerId = Column("lecturer_id", String(255), ForeignKey("lecturers.id"), nullable=False, index=True)
    specializationId = Column("specialization_id", String(255), ForeignKey("specializations.id"), nullable=False, index=True)

class Lecturer(Base):
    __tablename__ = "lecturers"

    # Primary Key
    id = Column("id", String(255), primary_key=True, index=True)
    
    # String & Enum Columns
    name = Column("name", String(50), nullable=False)
    
    # Menggunakan Enum bawaan SQLAlchemy untuk mencocokkan ENUM di MySQL
    religion = Column(
        "religion", 
        Enum('BUDDHISM','CATHOLIC','CHRISTIAN','CONFUCIANISM','HINDUISM','ISLAM', name="religion_enum"), 
        nullable=False
    )
    
    # Boolean / Bit Columns
    isActive = Column("is_active", Boolean, nullable=False)
    isInterdiscipline = Column("is_interdiscipline", Boolean, nullable=False)
    isMale = Column("is_male", Boolean, nullable=False)
    
    # DateTime Columns (Audit)
    deletedAt = Column("deleted_at", DateTime, nullable=True)
    
    # Foreign Keys / Indexed Columns
    categoryId = Column("category_id", String(255), ForeignKey("categories.id"), nullable=False, index=True)

    # Relationships
    lecturerSpecializations = relationship(
        "LecturerSpecialization", 
        backref="lecturer",
        cascade="all, delete-orphan"
    )

    lecturerSchedules = relationship(
        "LecturerSchedule",
        backref="lecturer",
        cascade="all, delete-orphan"
    )