# database.py

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from pymysql.constants import FIELD_TYPE
from pymysql.converters import conversions

load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# --- FIX: decode kolom BIT(1) MySQL menjadi int di level driver ---
def _decode_bit(value: bytes) -> int:
    # pymysql selalu mengirim BIT sebagai bytes mentah, mis. b'\x00' / b'\x01'
    return int.from_bytes(value, byteorder="big") if value else 0

bit_conversions = conversions.copy()
bit_conversions[FIELD_TYPE.BIT] = _decode_bit
# -------------------------------------------------------------------

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"conv": bit_conversions},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()