# `algorithm/` -- Algoritma Generate Jadwal Otomatis

Package Python murni (tidak ada framework/web di dalamnya) yang
mengimplementasikan flow generate jadwal yang sudah didiskusikan:

1. Ambil semua dosen, pisahkan **DLB** (punya baris di `lecturer_schedules`,
   berarti jadwalnya terbatas) vs **dosen full time** (tidak ada baris di
   `lecturer_schedules`, dianggap available di semua periode/hari).
2. Ambil course per semester (`is_odd` sesuai `timeline_generations`).
3. Cocokkan course ke kandidat dosen: `course.sks_count <= jumlah jadwal
   dosen` (khusus DLB), plus filter kategori/prodi & spesialisasi.
4. Urutkan kandidat: **DLB dulu**, ascending berdasar jumlah jadwal
   (paling sempit duluan), baru dosen full time.
5. Cari slot jadwal (hari + periode), di-scale sesuai `lecturer_count`
   (dosen tambahan boleh bentrok jadwal, cuma dosen utama yang dicek
   bentrok).
6. Cari ruang yang kapasitasnya cukup.
7. Kalau kapasitas course melebihi kapasitas ruang manapun -> otomatis
   pecah jadi beberapa `course_index` (A/B/C/...), masing-masing bisa
   dapat dosen berbeda.
8. Kalau course lab -> cari ruang lab yang sesuai spesialisasi, pakai
   "6-7 strategy" (lihat penjelasan di bawah), dan kapasitas LAB yang
   jadi acuan split (bukan kapasitas ruang kelas biasa).
9. Kalau jadwal dosen di satu hari habis / course butuh lebih banyak
   periode dari yang tersisa di hari itu -> lanjut ke hari lain, **dosen
   yang sama**.
10. Kalau tetap tidak ketemu dosen yang cocok -> course_schedule TETAP
    dibuat (best effort), `lectures.lecturer_id = NULL` dan
    `lectures.fallback_reason` diisi alasannya.

## Struktur file

```
algorithm/
  __init__.py            expose generate_timeline()
  config.py               semua konstanta/heuristik yang bisa di-tuning
  models.py                dataclass: Lecturer, Course, Room, Period,
                            PlannedSession, LecturerAssignment, dst
  repository.py             baca/tulis MySQL (pymysql) -> objek models.py
  matching.py                cari & urutkan kandidat dosen per course
  allocation.py               primitif: cari periode kontigu kosong +
                              ruang yang cocok
  scheduler.py                 orkestrasi 1 course -> list[PlannedSession]
                              (split kapasitas, teori, lab, fallback)
  generator.py                  entry point generate_timeline(conn, id)
  example_integration.py         contoh potongan kode utk app.py (referensi)
  tests/
    test_smoke.py               test end-to-end pakai data sintetis
    test_edge_cases.py           test overflow hari, co-teaching, dll
```

## Cara pakai

```python
from algorithm import generate_timeline

# conn = koneksi pymysql yang sudah ada (cursorclass=DictCursor, SAMA
# seperti get_connection() di app.py kamu)
result = generate_timeline(conn, timeline_generation_id, commit=True)
conn.commit()  # generate_timeline TIDAK auto-commit, caller yang commit
print(result.as_dict())
```

Lihat `example_integration.py` untuk contoh penuh cara menyambungkannya ke
endpoint `/startGenerate` yang sudah ada di `app.py` (menggantikan bagian
`time.sleep(GENERATE_SLEEP_SECONDS)` yang sekarang cuma simulasi).

**Syarat koneksi**: `conn` harus dibuat dengan
`cursorclass=pymysql.cursors.DictCursor` -- persis seperti
`get_connection()` yang sudah ada di `app.py` kamu sekarang, jadi tidak
perlu ubah apa-apa di situ.

**Dry-run** (hitung saja, tidak nulis ke DB): `generate_timeline(conn,
tg_id, commit=False)`.

## Cara menjalankan test (tanpa DB)

```bash
pip install pymysql --break-system-packages   # kalau belum ada
python -m algorithm.tests.test_smoke
python -m algorithm.tests.test_edge_cases
```

Test ini pakai data sintetis langsung di level `models.py`, jadi TIDAK
butuh koneksi database sungguhan -- cocok buat validasi logic sebelum
dicoba ke DB asli.

## ⚠️ Asumsi yang WAJIB dicek ulang

Beberapa aturan di spek tidak punya angka pasti, jadi saya isi dengan
interpretasi yang masuk akal dan **dijadikan konstanta di `config.py`**
supaya gampang diubah tanpa bongkar logic:

### 1. "6-7 strategy" untuk course lab (`config.py`)

```python
LAB_THEORY_SKS_REDUCTION = 1     # sks_count course dikurangi 1 utk porsi teori
LAB_BLOCK_SKS_EQUIVALENT = 3     # blok lab = 3 periode kontigu, di ruang lab
```

Jadi course lab dengan `sks_count=4` -> 3 periode teori (di ruang biasa)
+ 1 blok lab senilai 3 periode kontigu (di ruang lab yang match
spesialisasi). Kalau angka aslinya beda (misal reduction-nya bukan 1,
atau blok lab bukan selalu 3), tinggal ubah 2 konstanta ini di
`config.py`, tidak perlu sentuh `scheduler.py`.

### 2. Pencocokan kategori/prodi & interdiscipline

```python
REQUIRE_CATEGORY_MATCH_UNLESS_INTERDISCIPLINE = True
```

Course dengan `is_interdiscipline=False` cuma bisa diampu dosen dari
`category_id` (prodi) yang sama. Course `is_interdiscipline=True` boleh
lintas prodi. Kalau aturan aslinya tidak seketat ini, set jadi `False`.

### 3. Ruang teori vs ruang lab

```python
THEORY_USES_NON_LAB_ROOMS_ONLY = True
```

Sesi teori HANYA pakai ruang yang `lab_group_id IS NULL`; ruang
ber-`lab_group_id` direservasi khusus utk blok lab. Asumsinya: ruang lab
tidak dipakai untuk kelas teori biasa walaupun kapasitasnya cukup.

### 4. Urutan pemrosesan course

```python
SORT_COURSES_BY_SKS_DESC = True
PRIORITIZE_LAB_COURSES_FIRST = True
```

Course lab & course sks besar diproses lebih dulu (greedy: kerjakan yang
paling susah cari slot duluan selagi kapasitas ruang/dosen masih
longgar).

### 5. Strategi pencarian kandidat & slot

Algoritma ini **greedy**, bukan optimasi global / backtracking penuh:
begitu ketemu 1 kandidat dosen yang bisa dapat *sebagian* slot teori,
kandidat itu langsung dipakai (tidak coba semua kombinasi dosen x
hari x ruang untuk cari solusi paling optimal). Ini pilihan sadar demi
performa & kesederhanaan -- untuk jumlah course/dosen yang wajar (puluhan
-ratusan), ini biasanya cukup baik, tapi bukan jaminan solusi optimal
100%.

### 6. Best-effort placement kalau gagal total

Kalau BENAR-BENAR tidak ada dosen yang bisa dipasang (semua kandidat
gagal / tidak ada kandidat sama sekali), `course_schedules` **tetap**
dibuat (ruang & waktu dicari tanpa mempertimbangkan dosen), supaya tidak
ada course yang hilang begitu saja dari hasil generate. Baris `lectures`
terkait akan punya `lecturer_id = NULL` dan `fallback_reason` terisi.
Kalau kamu maunya course yang gagal total malah TIDAK usah dibuatkan
`course_schedules` sama sekali (murni skip), tinggal ubah bagian
"force placement" di `scheduler.py` (cari komentar `_force_placement`).

### 7. Generate ulang (retry)

`generate_timeline(..., replace_existing=True)` (default) akan
menghapus `lectures` + `course_schedules` LAMA milik
`timeline_generation_id` yang sama sebelum insert baru -- supaya kalau
`/startGenerate` dipanggil ulang untuk `timeline_generation` yang sama,
tidak numpuk data dobel. Set `replace_existing=False` kalau kamu mau
insert selalu nambah (bukan replace).

### 8. Bit(1) dari MySQL

`repository.py` sudah menangani gotcha `pymysql` yang mengembalikan
kolom `bit(1)` sebagai `bytes` mentah (`b'\x00'`/`b'\x01'`), bukan
`bool`/`int` -- kalau langsung `bool(...)` di Python hasilnya SELALU
`True` karena `bytes` non-kosong selalu truthy. Semua pembacaan bit
sudah lewat helper `to_bool()`. Kalau kamu nambah query baru yang baca
kolom `bit(1)`, pastikan tetap pakai `to_bool()`, jangan `bool()`
langsung.

## Skema tabel yang dipakai

Merujuk ke dump SQL (`jadwal_2_.sql`) yang kamu kasih:

- `lecturers`, `lecturer_schedules`, `lecturer_specializations`
- `courses`, `course_specializations`
- `rooms`, `lab_groups`, `lab_specializations`
- `schedules` (periode waktu, tidak terikat hari)
- `course_schedules` (output: 1 baris = 1 course_index + hari + periode +
  ruang)
- `lectures` (output: 1 baris = 1 dosen yang mengajar di 1
  `course_schedule`; `lecturer_id` nullable + `fallback_reason` sudah
  sesuai perubahan yang kamu buat)
- `timeline_generations`, `free_tables`

Tidak ada perubahan skema yang dibutuhkan di luar yang sudah kamu buat
(`lecturer_id` nullable + kolom `fallback_reason` di `lectures`).
