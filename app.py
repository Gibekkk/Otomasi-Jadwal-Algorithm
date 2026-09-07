"""
startGenerate service
======================
Local-only microservice. Satu-satunya endpoint: POST /startGenerate.

Alur:
1. Terima secretKey dari body request (JSON).
2. Validasi secretKey terhadap kolom `secret_key` di tabel `free_tables`.
3. Kalau valid:
   a. Rotasi secret_key (UUID di-hash SHA-256) DAN COMMIT SEKARANG JUGA,
      SEBELUM algoritma generate jalan -- bukan dibundel dengan commit
      hasil generate di akhir. secretKey lama langsung invalid begitu
      generate dimulai (bukan baru setelah generate, yang bisa berjalan
      lama, selesai).
   b. Jalankan algoritma generate jadwal sungguhan lewat
      `algorithm.generate_timeline()` untuk `timeline_generation_id` milik
      free_table ini.
   c. Kalau generate sukses -> commit transaksi generate, lalu POST
      secret_key baru (raw text) ke TimelineController Java backend:
      {JAVA_BASE_URL}{API_PREFIX}/timeline/generateComplete
      dengan header Token, endpoint ini yang men-set is_generating = 0.
   d. Kalau generate GAGAL (exception apa pun) -> rollback perubahan
      algoritma (secret_key yang sudah dirotasi di langkah (a) TETAP
      dirotasi, tidak ikut rollback karena sudah di-commit terpisah), lalu
      POST ke {JAVA_BASE_URL}{API_PREFIX}/timeline/stopGenerate supaya
      backend tahu proses berhenti dan bisa reset is_generating alih-alih
      stuck. Endpoint & payload stopGenerate ini masih ASUMSI -- sesuaikan
      dengan TimelineController Java yang sebenarnya kalau berbeda.
4. Kalau tidak valid -> 401.

Catatan: kolom `secret_key` (VARCHAR) harus ada di tabel `free_tables`, dan
akun admin (JAVA_ADMIN_USERNAME/PASSWORD) harus SuperAdmin/BaaAdmin/ProdiAdmin.

Konfigurasi lewat .env (lihat .env.example).
"""

import hashlib
import logging
import os
from time import sleep
import uuid

import pymysql
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from algorithm.main import generate_timeline

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_NAME = os.environ.get("DB_NAME", "jadwal")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASS = os.environ.get("DB_PASS", "")

JAVA_BASE_URL = os.environ.get("JAVA_BASE_URL", "http://localhost:8080")
API_PREFIX = os.environ.get("API_PREFIX", "/api/v1")
GENERATE_COMPLETE_PATH = f"{API_PREFIX}/timeline/generateComplete"
# NOTE: endpoint & payload di bawah ini ASUMSI (belum ada di spesifikasi
# awal) -- kalau TimelineController Java kamu pakai path/kontrak beda,
# sesuaikan GENERATE_STOP_PATH & body JSON di notify_generate_stopped().
GENERATE_STOP_PATH = os.environ.get("GENERATE_STOP_PATH", f"{API_PREFIX}/timeline/stopGenerate")

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
            "from .free_tables WHERE secret_key = %s LIMIT 1",
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


def notify_generate_stopped(free_table_id, timeline_generation_id, secret_key, error_detail):
    """Beri tahu backend Java kalau proses generate BERHENTI/GAGAL (exception
    apa pun setelah kita tahu free_table/timeline mana yang terlibat),
    supaya backend bisa reset status `is_generating` alih-alih stuck
    seakan-akan masih generate padahal prosesnya sudah mati."""
    if free_table_id is None and timeline_generation_id is None:
        # Belum sempat tahu free_table/timeline mana yang terlibat (mis.
        # gagal sebelum secretKey divalidasi) -- tidak ada yang bisa
        # diberitahu ke backend.
        return None
    url = f"{JAVA_BASE_URL}{GENERATE_STOP_PATH}"
    try:
        response = requests.post(
            url,
            json={
                "freeTableId": free_table_id,
                "timelineGenerationId": timeline_generation_id,
                "secretKey": secret_key,
                "error": error_detail,
            },
            timeout=10,
        )
        logger.info("POST %s -> %s", url, response.status_code)
        return response.status_code
    except requests.RequestException as exc:
        logger.error("Gagal fetch %s: %s", url, exc)
        return None

def get_timeline_is_odd(conn, timeline_generation_id):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT is_odd FROM timeline_generations WHERE id = %s LIMIT 1",
            (timeline_generation_id,)
        )
        row = cursor.fetchone()
        
        if row is not None:
            val = row["is_odd"]
            # Konversi dari bytes b'\x01' ke boolean jika diperlukan
            if isinstance(val, bytes):
                return ord(val) == 1
            return bool(val)
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

    free_table_id = None
    timeline_generation_id = None
    new_secret = None

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

        # AMBIL DATA IS_ODD DI SINI
        is_odd = get_timeline_is_odd(conn, timeline_generation_id)
        
        if is_odd is None:
            return jsonify({
                "message": "Data timeline_generation tidak ditemukan di database"
            }), 404
            
        logger.info("Timeline ID: %s | is_odd: %s", timeline_generation_id, is_odd)

        # Rotasi secret key & COMMIT SEKARANG
        new_secret = rotate_secret_key(conn, free_table_id)
        conn.commit()
        logger.info("Secret key dirotasi & di-commit di awal (sebelum generate jalan)")

        logger.info(
            "Menjalankan algoritma generate jadwal untuk timeline_generation_id=%s",
            timeline_generation_id,
        )
        
        # SEKARANG ANDA BISA MEMASUKKAN is_odd KE DALAM ALGORITMA
        result = generate_timeline(timeline_generation_id, is_odd)
        # sleep(60)  # Simulasi generate lama
        conn.commit()
        # logger.info("Generate selesai: %s", result.as_dict())

        callback_status = notify_generate_complete(new_secret)

        return jsonify({
            "message": "Generate selesai",
            "freeTableId": free_table_id,
            "timelineGenerationId": timeline_generation_id,
            # "generateResult": result.as_dict(),
            "generateCompleteStatus": callback_status,
        }), 200

    except pymysql.MySQLError as exc:
        conn.rollback()
        logger.error("Database error: %s", exc)
        stop_status = notify_generate_stopped(free_table_id, timeline_generation_id, new_secret, str(exc))
        return jsonify({
            "message": "Database error",
            "detail": str(exc),
            "generateStoppedStatus": stop_status,
        }), 500
    except Exception as exc:  # noqa: BLE001 - mau tangkap SEMUA error algoritma/lainnya
        conn.rollback()
        logger.error("Gagal generate jadwal: %s", exc)
        stop_status = notify_generate_stopped(free_table_id, timeline_generation_id, new_secret, str(exc))
        return jsonify({
            "message": "Gagal generate jadwal",
            "detail": str(exc),
            "generateStoppedStatus": stop_status,
        }), 500
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(host=SERVER_HOST, port=SERVER_PORT)
