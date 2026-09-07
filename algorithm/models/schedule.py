from sqlalchemy import Column, String, Time
from ..database import Base

class Schedule(Base):
    __tablename__ = "schedules"

    # Primary Key
    id = Column("id", String(255), primary_key=True, index=True)
    
    # Time Columns
    timeStart = Column("time_start", Time, nullable=False)
    timeEnd = Column("time_end", Time, nullable=False)