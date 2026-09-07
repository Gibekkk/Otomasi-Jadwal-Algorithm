# database.py

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base

# 1. Muat environment variables dari file .env
load_dotenv()

# 2. Ambil nilai-nilai database dari environment variables
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

# 3. Rakit URL Database untuk MySQL (menggunakan driver pymysql)
# Format URL: mysql+pymysql://user:password@host:port/database_name
SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# 4. Membuat Engine
# Kita tidak lagi butuh connect_args={"check_same_thread": False} karena itu khusus SQLite
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# 5. Membuat SessionLocal
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 6. Membuat Base Class
Base = declarative_base()

# 7. Helper Function / Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()