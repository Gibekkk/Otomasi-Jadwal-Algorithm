from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer
from sqlalchemy.orm import relationship
from ..database import Base

class CourseSpecialization(Base):
    __tablename__ = "course_specializations"

    id = Column("id", String(255), primary_key=True, index=True)
    
    courseId = Column("course_id", String(255), ForeignKey("courses.id"), nullable=False, index=True)
    specializationId = Column("specialization_id", String(255), ForeignKey("specializations.id"), nullable=False, index=True)

class Course(Base):
    __tablename__ = "courses"

    # Primary Key
    id = Column("id", String(255), primary_key=True, index=True)
    
    # Integer Columns
    capacity = Column("capacity", Integer, nullable=False)
    lecturerCount = Column("lecturer_count", Integer, nullable=False)
    semester = Column("semester", Integer, nullable=False)
    sksCount = Column("sks_count", Integer, nullable=False)
    
    # String Columns
    name = Column("name", String(50), nullable=False)
    
    # Boolean / Bit Columns
    isActive = Column("is_active", Boolean, nullable=False)
    isInterdiscipline = Column("is_interdiscipline", Boolean, nullable=False)
    isLab = Column("is_lab", Boolean, nullable=False)
    isOdd = Column("is_odd", Boolean, nullable=False)
    
    # DateTime Columns
    deletedAt = Column("deleted_at", DateTime, nullable=True)
    
    # Foreign Keys / Indexed Columns
    categoryId = Column("category_id", String(255), ForeignKey("categories.id"), nullable=False, index=True)
    submajorId = Column("submajor_id", String(255), ForeignKey("submajors.id"), nullable=True, index=True)

    # Relationships
    courseSpecializations = relationship(
        "CourseSpecialization", 
        backref="course",
        cascade="all, delete-orphan"
    )