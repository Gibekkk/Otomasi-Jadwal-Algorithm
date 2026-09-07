from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from ..database import Base

class LabSpecialization(Base):
    __tablename__ = "lab_specializations"

    id = Column("id", String(255), primary_key=True, index=True)
    
    # Foreign Keys
    labGroupId = Column("lab_group_id", String(255), ForeignKey("lab_groups.id"), nullable=False, index=True)
    specializationId = Column("specialization_id", String(255), ForeignKey("specializations.id"), nullable=False, index=True)

class LabGroup(Base):
    __tablename__ = "lab_groups"

    id = Column("id", String(255), primary_key=True, index=True)
    name = Column("name", String(50), nullable=False)
    
    # Audit & Timestamps
    deletedAt = Column("deleted_at", DateTime, nullable=True)

    # Relationship ke LabSpecialization (Tabel Perantara)
    # Jika LabGroup dihapus, hapus juga mapping spesialisasinya
    labSpecializations = relationship(
        "LabSpecialization", 
        backref="lab_group",
        cascade="all, delete-orphan"
    )

class Room(Base):
    __tablename__ = "rooms"

    id = Column("id", String(255), primary_key=True, index=True)
    name = Column("name", String(50), nullable=False)
    capacity = Column("capacity", Integer, nullable=False)
    
    # Audit & Timestamps
    deletedAt = Column("deleted_at", DateTime, nullable=True)
    
    # Foreign Keys / Indexed Columns
    # Sesuai database, lab_group_id boleh NULL (ruangan biasa, bukan lab)
    labGroupId = Column("lab_group_id", String(255), ForeignKey("lab_groups.id"), nullable=True, index=True)

    # Relationship ke LabGroup
    # Memberikan properti .rooms pada LabGroup, dan properti .labGroup pada Room
    labGroup = relationship("LabGroup", backref="rooms")