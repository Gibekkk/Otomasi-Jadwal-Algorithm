from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Integer
from sqlalchemy.orm import relationship
from ..database import Base

class Category(Base):
    __tablename__ = "categories"

    id = Column("id", String(255), primary_key=True, index=True)
    name = Column("name", String(50), nullable=False)
    isProdi = Column("is_prodi", Boolean, nullable=False)
    
    # Audit & Timestamps
    deletedAt = Column("deleted_at", DateTime, nullable=True)

    submajors = relationship("Submajor", backref="category")
    courses = relationship("Course", backref="category")
    lecturers = relationship("Lecturer", backref="category")

class Submajor(Base):
    __tablename__ = "submajors"

    id = Column("id", String(255), primary_key=True, index=True)
    name = Column("name", String(50), nullable=False)
    
    # Audit & Timestamps
    deletedAt = Column("deleted_at", DateTime, nullable=True)
    
    # Foreign Keys
    categoryId = Column("category_id", String(255), ForeignKey("categories.id"), nullable=False, index=True)

    # Relasi ke Course
    courses = relationship("Course", backref="submajor")