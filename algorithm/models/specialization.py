from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from ..database import Base

class Specialization(Base):
    __tablename__ = "specializations"

    id = Column("id", String(255), primary_key=True, index=True)
    name = Column("name", String(50), nullable=False)
    
    # Audit & Timestamps
    deletedAt = Column("deleted_at", DateTime, nullable=True)

    courseSpecializations = relationship("CourseSpecialization", backref="specialization")
    lecturerSpecializations = relationship("LecturerSpecialization", backref="specialization")