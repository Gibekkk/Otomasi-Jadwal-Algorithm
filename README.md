# Otomasi Jadwal — Algorithm Service (`startGenerate`)

Microservice Python yang menjalankan **algoritma penjadwalan kuliah** untuk sistem Otomasi Jadwal. Service ini **local-only** (hanya bisa diakses dari host tempat ia berjalan), dipicu oleh backend Java (**Otomasi-Jadwal-Backend**) setiap kali admin menekan tombol "Generate Jadwal", dan mengembalikan notifikasi selesai lewat callback HTTP ke backend tersebut.

---

## Daftar Isi

- [Peran dalam Sistem](#peran-dalam-sistem)
- [Tech Stack](#tech-stack)
- [Struktur Proyek](#struktur-proyek)
- [Arsitektur Algoritma](#arsitektur-algoritma)
- [Kontrak API](#kontrak-api)
- [Integrasi dengan Backend Java](#integrasi-dengan-backend-java)
- [Keterbatasan & Catatan Implementasi Saat Ini](#keterbatasan--catatan-implementasi-saat-ini)
- [Prasyarat](#prasyarat)
- [Konfigurasi Environment](#konfigurasi-environment)
- [Cara Menjalankan](#cara-menjalankan)
- [Deployment / CI-CD](#deployment--cicd)
- [Roadmap](#roadmap)

---

## Peran dalam Sistem

Backend Java (**Otomasi-Jadwal-Backend**) tidak menghitung jadwal kuliah sendiri. Saat admin memicu proses generate, backend Java memanggil service ini secara asynchronous, dan komputasi penjadwalan yang sesungguhnya (pencocokan dosen, ruangan/lab, dan slot waktu) dijalankan sepenuhnya di sini — dipisah dari proses backend utama agar tidak membebani proses tersebut.

Service ini membaca dan menulis langsung ke **database MariaDB yang sama** dengan backend Java, lewat model SQLAlchemy yang dipetakan ke tabel yang identik dengan entity JPA di backend (`categories`, `courses`, `lecturers`, `rooms`, `schedules`, `specializations`, dst).

---

## Tech Stack

| Komponen | Teknologi |
|---|---|
| Bahasa & Runtime | Python 3.12 |
| Web framework | Flask 3.x |
| ORM | SQLAlchemy 2.x (query data akademik untuk algoritma) |
| Akses DB langsung | PyMySQL (validasi & rotasi `secret_key`, di luar SQLAlchemy) |
| HTTP client | `requests` (callback ke backend Java) |
| Konfigurasi | `python-dotenv` |
| WSGI server (produksi) | Gunicorn — lihat [catatan](#keterbatasan--catatan-implementasi-saat-ini) |
| Container | Docker + Docker Compose |
| CI/CD | Jenkins (`Jenkinsfile`) |

---

## Struktur Proyek

```
Otomasi-Jadwal-Algorithm/
├── app.py                        # Entry point Flask, endpoint POST /startGenerate
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── Jenkinsfile
├── .env.example
└── algorithm/
    ├── database.py                # Engine & session SQLAlchemy (koneksi terpisah dari app.py)
    ├── main.py                    # generate_timeline() — orkestrator utama algoritma
    ├── filter.py                  # Module 1 — ambil & filter data akademik aktif dari DB
    ├── grouping.py                # Module 2 — kelompokkan course dengan kandidat dosen & ruangan/lab
    ├── splitter.py                # Helper — pecah kapasitas course ke beberapa ruangan/lab
    ├── schedule_controller.py     # Module 5 — orkestrasi prioritas & pairing lab/non-lab
    ├── lecturer_scheduler.py      # Module 3 — penjadwalan course prioritas (dosen dulu, baru ruangan)
    ├── room_scheduler.py          # Module 4 — penjadwalan course non-prioritas (ruangan dulu, baru dosen)
    ├── scheduling_common.py       # State bersama module 3 & 4 (cegah double-booking)
    ├── lecturer_schedule.py       # Berkas lama, sudah digantikan lecturer_scheduler.py (lihat catatan)
    └── models/                    # Model SQLAlchemy: category, course, lecturer, room, schedule, specialization
```

---

## Arsitektur Algoritma

Proses generate jadwal (`algorithm.main.generate_timeline`) berjalan dalam beberapa tahap berurutan:

1. **Module 1 — Filter (`filter.py`)**: mengambil data mata kuliah, dosen, ruangan, lab, dan spesialisasi yang aktif dari database, sesuai semester ganjil/genap (`isOdd`) yang diminta.
2. **Module 2 — Grouping (`grouping.py`)**: untuk tiap mata kuliah, menghitung skor kecocokan (*priority rate*) terhadap kandidat dosen (berdasarkan spesialisasi) dan kandidat ruangan/lab (berdasarkan kapasitas & spesialisasi), lalu memecah course berkapasitas besar ke beberapa ruangan/lab lewat `splitter.py` bila perlu.
3. **Module 5 — Orkestrasi (`schedule_controller.py`)**:
   - Memisahkan course yang tidak punya ruangan/lab sama sekali (di-skip), course *prioritas* (kandidat dosen utamanya sudah punya hari komitmen tetap), dan sisanya (*non-prioritas*).
   - Mengurutkan tiap kelompok dari jumlah kandidat dosen paling sedikit ("most-constrained-first").
   - Memasangkan entri ruangan biasa & lab dari course+index yang sama (harus diampu dosen yang sama).
4. **Module 3 — Lecturer Scheduler (`lecturer_scheduler.py`)**: menghabiskan course prioritas dengan strategi *dosen dulu, baru cari slot & ruangan*.
5. **Module 4 — Room Scheduler (`room_scheduler.py`)**: memproses course non-prioritas dengan strategi *ruangan/lab dulu, baru cari dosen yang kosong di slot tersebut*.
6. Module 3 & 4 berbagi objek `SchedulingState` (`scheduling_common.py`) yang sama, sehingga dosen atau ruangan yang sama tidak pernah dibooking dobel pada slot (hari + jam) yang sama, apa pun jalur pemrosesannya. Satu sesi menempati **blok periode berurutan** sepanjang `sksCount` — seluruh periode dalam blok itu yang dibooking, bukan hanya periode pertamanya.
7. **Module 6 — Persistence (`persistence.py`)**: menyimpan hasil penjadwalan ke `course_schedules`, `lectures`, dan `lecture_lecturers`. Hasil generate sebelumnya untuk `timeline_generation_id` yang sama dihapus lebih dulu (urut FK: `lecture_lecturers` → `lectures` → `course_schedules`), supaya generate ulang tidak menumpuk jadwal ganda.

---

## Kontrak API

Satu-satunya endpoint HTTP yang diekspos:

### `POST /startGenerate`

**Request:**
```json
{ "secretKey": "<nilai kolom secret_key di tabel free_tables>" }
```

**Alur pemrosesan:**
1. Validasi `secretKey` terhadap kolom `free_tables.secret_key`. Tidak cocok → `401`.
2. Ambil `timeline_generation_id` & `is_odd` terkait dari `free_tables` / `timeline_generations`.
3. Rotasi `secret_key` (UUID baru di-hash SHA-256) dan **commit langsung saat itu juga**, sebelum algoritma dijalankan — supaya `secretKey` lama langsung tidak berlaku sejak generate dimulai, bukan baru setelah generate (yang bisa berjalan lama) selesai.
4. Jalankan `algorithm.generate_timeline(timeline_generation_id, is_odd)`.
5. Kirim `secret_key` baru (raw text, header `Content-Type: text/plain`) ke backend Java: `POST {JAVA_BASE_URL}{API_PREFIX}/timeline/generateComplete`.
6. Response `200` berisi ringkasan (`freeTableId`, `timelineGenerationId`, status callback).

**Contoh:**
```bash
curl -X POST http://127.0.0.1:8082/startGenerate \
  -H "Content-Type: application/json" \
  -d '{"secretKey": "<secret dari kolom secret_key di free_tables>"}'
```

**Syarat data:**
- Kolom `secret_key` (VARCHAR) harus ada di tabel `free_tables`.
- `free_tables` yang dipakai harus sudah terhubung ke sebuah `timeline_generation_id` yang valid.

---

## Integrasi dengan Backend Java

| Arah | Endpoint | Keterangan |
|---|---|---|
| Java → service ini | `POST http://startgenerate-service:8082/startGenerate` | Dipicu backend Java secara asynchronous saat admin generate jadwal. |
| Service ini → Java | `POST {JAVA_BASE_URL}{API_PREFIX}/timeline/generateComplete` | Dipanggil setelah proses generate selesai, membawa `secret_key` baru sebagai body plain text. Endpoint ini yang men-set `is_generating = false` di backend Java. |
| Service ini → Java | `POST {JAVA_BASE_URL}{API_PREFIX}/timeline/stopGenerate` | Dipanggil saat terjadi error database di tengah proses. **Lihat catatan di bawah.** |

> **Catatan kontrak `stopGenerate`:** path dan payload endpoint ini masih berupa asumsi pada kode (`GENERATE_STOP_PATH`, dapat dikonfigurasi lewat env var) dan belum tentu benar-benar tersedia di `TimelineController` backend Java. Sebelum mengandalkan notifikasi kegagalan ini di production, pastikan endpoint tersebut memang diimplementasikan pada backend Java, atau sesuaikan path/payload di `notify_generate_stopped()` agar cocok dengan kontrak yang sebenarnya.

---

## Keterbatasan & Catatan Implementasi Saat Ini

1. **Kontrak `stopGenerate` ke backend Java masih asumsi.** Path & payload endpoint ini (`GENERATE_STOP_PATH`, dapat dikonfigurasi lewat env var) belum dikonfirmasi ada di `TimelineController` backend Java — lihat bagian [Integrasi](#integrasi-dengan-backend-java).
2. **Pemilihan co-lecturer tidak dicek bentrok.** Untuk course dengan `lecturer_count > 1`, dosen pendamping diambil dari sisa kandidat yang cocok tanpa memeriksa apakah jadwalnya bentrok — hanya dosen **utama** yang dijamin bebas bentrok. Ini disengaja (sesuai aturan "hanya jadwal dosen utama yang tidak boleh bentrok"), tapi perlu diingat saat membaca hasilnya.
3. **`unscheduled` belum ditangani ulang.** Course yang gagal dijadwalkan dilaporkan lewat log & `unscheduled_count`, tapi belum dicoba ulang lewat re-splitting ruangan/lab atau re-grouping dosen (TODO pada `schedule_controller.py`).
4. **Variabel environment yang dideklarasikan namun belum dipakai kode:** `JAVA_ADMIN_USERNAME`, `JAVA_ADMIN_PASSWORD`, dan `GENERATE_SLEEP_SECONDS` ada di `.env.example` tetapi tidak direferensikan di kode (tidak ada proses login ke backend Java, dan simulasi `sleep()` sudah dihapus).
5. **Pembagian porsi lab vs teori memakai asumsi tetap:** course lab dengan `sksCount > 1` dipecah jadi 1 periode blok lab + `sksCount - 1` periode teori (lihat `scheduling_common.session_duration`). Sesuaikan fungsi itu kalau aturan di kampus Anda berbeda.

### Sudah diperbaiki pada versi ini

- **Hasil generate kini disimpan ke database** lewat `persistence.py` (module 6) — sebelumnya hanya struktur data di memori, sehingga backend Java menerima "generate selesai" padahal tidak ada jadwal yang tersimpan.
- **Error algoritma tidak lagi ditelan.** `generate_timeline()` sekarang rollback lalu melempar ulang exception, sehingga `app.py` benar-benar mendeteksi kegagalan dan memanggil `stopGenerate`, bukan `generateComplete`.
- **SQL rusak di `app.py` diperbaiki** — query `free_tables` sempat tertulis `from .free_tables` (bukan `FROM free_tables`), yang membuat setiap request gagal.
- **`Dockerfile` diperbaiki** — baris pertama sempat tertulis `from .python:3.12-slim` (bukan `FROM python:3.12-slim`), yang membuat build gagal.
- **`gunicorn` ditambahkan ke `requirements.txt`** (dibutuhkan oleh `CMD` di Dockerfile).
- **Booking kini per-blok, bukan per-periode.** Sebelumnya course 3 SKS hanya membooking 1 periode, sehingga course lain bisa dijadwalkan menimpa jam-jam yang sebenarnya masih terpakai.
- **Ketersediaan dosen dibaca sampai level jam** lewat tabel `lecturer_schedules_time` yang sebelumnya tidak pernah dibaca kode (ketersediaan hanya dianggap per-hari).
- **Query N+1 dihilangkan** — `courseSpecializations`, `lecturerSpecializations`, dan `lecturerSchedules` kini di-eager-load; pencocokan spesialisasi memakai `set` id yang dihitung sekali, bukan membangun ulang list di setiap pasangan course × dosen.
- **`algorithm/lecturer_schedule.py` (berkas mati) dihapus**, dan loop pemrosesan yang terduplikasi di module 3 & 4 disatukan ke `scheduling_pairing.py`.

---

## Prasyarat

- **Python 3.12**
- **MariaDB** — database yang sama dengan yang dipakai backend Java (Otomasi-Jadwal-Backend)
- **Backend Java (Otomasi-Jadwal-Backend)** berjalan dan dapat diakses, untuk menerima callback `generateComplete`
- **Docker & Docker Compose** — opsional, untuk menjalankan lewat container

---

## Konfigurasi Environment

Salin `.env.example` menjadi `.env`:

```env
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=jadwal
DB_USER=root
DB_PASS=

JAVA_BASE_URL=http://localhost:8080
API_PREFIX=/api/v1

JAVA_ADMIN_USERNAME=
JAVA_ADMIN_PASSWORD=

GENERATE_SLEEP_SECONDS=10

SERVER_HOST=127.0.0.1
SERVER_PORT=8082
```

| Variabel | Keterangan |
|---|---|
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASS` | Kredensial database MariaDB — **harus mengarah ke database yang sama** dengan backend Java. |
| `JAVA_BASE_URL` | Base URL backend Java, dipakai untuk callback `generateComplete` / `stopGenerate`. |
| `API_PREFIX` | Prefix API backend Java (default `/api/v1`). |
| `JAVA_ADMIN_USERNAME` / `JAVA_ADMIN_PASSWORD` | Dideklarasikan untuk kebutuhan login ke backend Java, **belum digunakan pada kode saat ini** (lihat [Keterbatasan](#keterbatasan--catatan-implementasi-saat-ini)). |
| `GENERATE_SLEEP_SECONDS` | Dideklarasikan untuk simulasi durasi generate, **belum dibaca oleh kode saat ini**. |
| `SERVER_HOST` / `SERVER_PORT` | Host & port Flask/Gunicorn. Default `127.0.0.1:8082` (local-only). |

---

## Cara Menjalankan

Service ini didesain **local-only** — tidak dimaksudkan untuk diakses langsung dari luar host tempatnya berjalan.

### Opsi A — Manual (tanpa Docker)

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # sesuaikan isinya dengan DB & backend Java
python app.py
```

Server akan berjalan di `http://127.0.0.1:8082` (mode Flask development server).

### Opsi B — Docker Compose

```bash
cp .env.example .env          # sesuaikan isinya
docker compose up -d --build
```

`docker-compose.yml` mem-publish port sebagai **`127.0.0.1:8082:8082`** — hanya bisa diakses dari host itu sendiri (loopback), bukan dari jaringan luar. **Jangan** mengubahnya menjadi `8082:8082` saja, karena itu akan mem-bind ke semua interface dan membuka akses dari luar host.

Service juga tergabung ke Docker network eksternal `jadwal-network`, network yang sama dengan container backend Java, supaya dapat dipanggil lewat nama container (`startgenerate-service`).

> Sebelum menjalankan lewat Docker, tambahkan `gunicorn` ke `requirements.txt` — lihat [Keterbatasan](#keterbatasan--catatan-implementasi-saat-ini) poin 5.

### Verifikasi Service Berjalan

```bash
curl -X POST http://127.0.0.1:8082/startGenerate \
  -H "Content-Type: application/json" \
  -d '{"secretKey": "test"}'
```

Response `401` (`"Secret key tidak valid"`) berarti service sudah aktif dan berhasil terhubung ke database (bukan error koneksi). Response `200` menandakan generate berhasil dipicu.

---

## Deployment / CI-CD

Pipeline (`Jenkinsfile`) menjalankan: **Checkout → Build Docker Image → Simpan image sebagai `.tar.gz` → Transfer via SCP/SSH ke server tujuan → Deploy dengan `docker compose up -d`**, diikuti health-check otomatis ke `/startGenerate` di server tujuan. Environment per-server disimpan sebagai Jenkins credential jenis *Secret file* (isi = isi `.env`), di-inject lewat parameter `ENV_CREDENTIAL_ID` (default `startgenerate-env`) — gunakan credential terpisah untuk tiap environment (mis. `startgenerate-env-staging`, `startgenerate-env-prod`).

Karena service ini *local-only*, agent Jenkins yang menjalankan tahap deploy diasumsikan **adalah** (atau memiliki akses SSH langsung ke) server tujuan.

---

## Roadmap

- [ ] Menangani `unscheduled` (course yang gagal dijadwalkan) lewat re-splitting ruangan/lab atau re-grouping dosen.
- [ ] Mengonfirmasi/menyelaraskan kontrak endpoint `stopGenerate` dengan backend Java.
- [ ] Mempertimbangkan pengecekan bentrok untuk co-lecturer, kalau aturannya berubah.
