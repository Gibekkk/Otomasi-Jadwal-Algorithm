"""
startGenerate service
======================
Local-only microservice. Satu-satunya endpoint: POST /startGenerate.

Alur:
1. Terima secretKey dari body request (JSON).
2. Validasi secretKey terhadap kolom `secret_key` di tabel `free_tables`.
3. Kalau valid:
   a. Simulasi generate key baru: UUID di-hash (SHA-256), simpan sebagai
      secret_key baru (rotasi, jadi key lama tidak bisa dipakai ulang).
   b. Jalankan algoritma generate jadwal sungguhan lewat
      `algorithm.generate_timeline()` untuk `timeline_generation_id` milik
      free_table ini (menggantikan simulasi sleep()).
   c. Kalau generate sukses -> commit transaksi (rotasi key + hasil generate
      jadi satu transaksi). Kalau gagal -> rollback semuanya (key TIDAK
      jadi dirotasi, biar caller bisa retry dengan secretKey yang sama).
   d. POST secret_key baru (raw text) ke TimelineController Java backend:
      {JAVA_BASE_URL}{API_PREFIX}/timeline/generateComplete
      dengan header Token, endpoint ini yang men-set is_generating = 0.
4. Kalau tidak valid -> 401.

Catatan: kolom `secret_key` (VARCHAR) harus ada di tabel `free_tables`, dan
akun admin (JAVA_ADMIN_USERNAME/PASSWORD) harus SuperAdmin/BaaAdmin/ProdiAdmin.

Konfigurasi lewat .env (lihat .env.example).
"""

import hashlib
import logging
import os
import uuid

import pymysql
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from algorithm import generate_timeline

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_NAME = os.environ.get("DB_NAME", "jadwal")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASS = os.environ.get("DB_PASS", "")

JAVA_BASE_URL = os.environ.get("JAVA_BASE_URL", "http://localhost:8080")
API_PREFIX = os.environ.get("API_PREFIX", "/api/v1")
GENERATE_COMPLETE_PATH = f"{API_PREFIX}/timeline/generateComplete"

SERVER_HOST = os.environ.get("SERVER_HOST", "127.0.0.1")  # local only
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8082"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("startGenerate")

app = Flask(__name__)


def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def find_free_table_by_secret(conn, secret_key):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT id, is_generating, secret_key, timeline_generation_id "
            "FROM free_tables WHERE secret_key = %s LIMIT 1",
            (secret_key,),
        )
        return cursor.fetchone()


def rotate_secret_key(conn, free_table_id):
    new_raw = uuid.uuid4().hex
    new_hashed = hashlib.sha256(new_raw.encode("utf-8")).hexdigest()
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE free_tables SET secret_key = %s WHERE id = %s",
            (new_hashed, free_table_id),
        )
    return new_hashed


def notify_generate_complete(new_secret_key):
    url = f"{JAVA_BASE_URL}{GENERATE_COMPLETE_PATH}"
    try:
        response = requests.post(
            url,
            data=new_secret_key,
            headers={"Content-Type": "text/plain"},
            timeout=10,
        )
        logger.info("POST %s -> %s", url, response.status_code)
        return response.status_code
    except requests.RequestException as exc:
        logger.error("Gagal fetch %s: %s", url, exc)
        return None


@app.post("/startGenerate")
def start_generate():
    body = request.get_json(silent=True) or {}
    secret_key = body.get("secretKey") or body.get("secret_key")

    if not secret_key:
        return jsonify({"message": "secretKey wajib diisi"}), 400

    try:
        conn = get_connection()
    except pymysql.MySQLError as exc:
        logger.error("Gagal konek ke database: %s", exc)
        return jsonify({"message": "Database error", "detail": str(exc)}), 500

    try:
        row = find_free_table_by_secret(conn, secret_key)
        if row is None:
            return jsonify({"message": "Secret key tidak valid"}), 401

        free_table_id = row["id"]
        timeline_generation_id = row.get("timeline_generation_id")
        logger.info("Secret key valid, free_table id=%s", free_table_id)

        if not timeline_generation_id:
            return jsonify({
                "message": "free_table ini belum terhubung ke timeline_generation"
            }), 400

        new_secret = rotate_secret_key(conn, free_table_id)
        logger.info("Key baru berhasil dibuat (rotasi secret_key, belum di-commit)")

        try:
            logger.info(
                "Menjalankan algoritma generate jadwal untuk timeline_generation_id=%s",
                timeline_generation_id,
            )
            result = generate_timeline(conn, timeline_generation_id, commit=True)
            conn.commit()
            logger.info("Generate selesai: %s", result.as_dict())
        except Exception as exc:  # noqa: BLE001 - mau tangkap semua error algoritma
            conn.rollback()
            logger.error("Gagal generate jadwal: %s", exc)
            return jsonify({"message": "Gagal generate jadwal", "detail": str(exc)}), 500

        callback_status = notify_generate_complete(new_secret)

        return jsonify({
            "message": "Generate selesai",
            "freeTableId": free_table_id,
            "timelineGenerationId": timeline_generation_id,
            "generateResult": result.as_dict(),
            "generateCompleteStatus": callback_status,
        }), 200
    except pymysql.MySQLError as exc:
        logger.error("Database error: %s", exc)
        return jsonify({"message": "Database error", "detail": str(exc)}), 500
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(host=SERVER_HOST, port=SERVER_PORT)
