"""
CONTOH integrasi ke app.py -- file ini TIDAK dipanggil otomatis dari mana
pun, cuma referensi. Silakan copy bagian yang relevan ke app.py aslimu.

Di app.py sekarang, fungsi `start_generate()` cuma sleep()
(simulasi generate). Ganti bagian itu dengan panggilan ke
`generate_timeline()`.

Perlu ditambahkan: kolom `timeline_generation_id` di `free_tables` dipakai
untuk tahu timeline_generation mana yang mau di-generate (sudah ada di
skema kamu), jadi tinggal dipakai.

--------------------------------------------------------------------------
SEBELUM (app.py, potongan start_generate):

    new_secret = rotate_secret_key(conn, free_table_id)
    logger.info("Simulasi generate jadwal, sleep %s detik...", GENERATE_SLEEP_SECONDS)
    time.sleep(GENERATE_SLEEP_SECONDS)
    callback_status = notify_generate_complete(new_secret)

SESUDAH:

    from algorithm import generate_timeline

    new_secret = rotate_secret_key(conn, free_table_id)

    timeline_generation_id = row["timeline_generation_id"]  # dari free_tables
    if not timeline_generation_id:
        return jsonify({"message": "free_table ini belum terhubung ke timeline_generation"}), 400

    try:
        result = generate_timeline(conn, timeline_generation_id, commit=True)
        conn.commit()
        logger.info("Generate selesai: %s", result.as_dict())
    except Exception as exc:
        conn.rollback()
        logger.error("Gagal generate jadwal: %s", exc)
        return jsonify({"message": "Gagal generate jadwal", "detail": str(exc)}), 500

    callback_status = notify_generate_complete(new_secret)

--------------------------------------------------------------------------
CATATAN:
- `find_free_table_by_secret` query di app.py sekarang cuma SELECT
  `id, is_generating, is_odd, academic_year, secret_key` -- tambahkan
  `timeline_generation_id` ke SELECT list-nya juga.
- `generate_timeline()` TIDAK memanggil conn.commit()/rollback() sendiri
  (biar caller yang atur transaksi bareng rotate_secret_key), jadi WAJIB
  di-commit manual setelah sukses seperti contoh di atas.
- Kalau generate berat & lama, pertimbangkan jalankan di background
  thread/queue supaya endpoint tidak nge-block terlalu lama -- di luar
  scope algoritma ini.
"""
