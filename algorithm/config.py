"""
Konfigurasi & konstanta algoritma generate jadwal
===================================================
Semua angka/aturan "bisnis" yang sifatnya asumsi (belum tentu 100% sama
dengan aturan institusi kamu) dikumpulkan di sini supaya gampang di-tuning
tanpa bongkar logic di modul lain.

Yang PALING perlu dicek ulang: bagian "LAB 6-7 STRATEGY" dan
"CANDIDATE MATCHING". Nilainya saya isi berdasarkan pemahaman dari flow yang
kamu kasih, tapi karena tidak ada angka pasti di spek, silakan sesuaikan.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Urutan hari yang dipakai untuk pencarian slot (Senin dulu, dst).
# Harus sama persis dengan enum `course_schedules.day` di DB.
# ---------------------------------------------------------------------------
DAY_ORDER = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]

# ---------------------------------------------------------------------------
# STEP: "get course per semester" -> urutan pemrosesan course.
# Course dengan sks besar / lab diproses lebih dulu karena paling sulit
# dapat slot (greedy: kerjakan yang susah dulu selagi slot masih longgar).
# ---------------------------------------------------------------------------
SORT_COURSES_BY_SKS_DESC = True
PRIORITIZE_LAB_COURSES_FIRST = True

# ---------------------------------------------------------------------------
# STEP: "match course to candidate lecturers"
# ---------------------------------------------------------------------------
# Kalau True: course yang is_interdiscipline=False hanya boleh diampu dosen
# dengan category_id (prodi) yang sama dengan course. Course
# is_interdiscipline=True boleh lintas prodi.
REQUIRE_CATEGORY_MATCH_UNLESS_INTERDISCIPLINE = True

# Kalau course punya baris di course_specializations, dosen kandidat WAJIB
# punya minimal 1 spesialisasi yang beririsan. Kalau course tidak punya
# spesialisasi terdaftar sama sekali, semua dosen (yang lolos filter lain)
# jadi kandidat.
REQUIRE_SPECIALIZATION_MATCH_IF_DEFINED = True

# ---------------------------------------------------------------------------
# STEP: "order candidates to dlb first by schedule count (ascending)"
# ---------------------------------------------------------------------------
# Urutan sort kandidat: DLB dulu (baris di lecturer_schedules ada),
# diurutkan ascending berdasar jumlah slot jadwal yang dia punya (paling
# sempit duluan supaya dosen yang jadwalnya longgar "disisakan" untuk
# course lain). Dosen full time (tidak ada baris lecturer_schedules,
# dianggap available di semua periode) ditaruh di belakang, diurutkan
# berdasar beban (jumlah course yang sudah dia pegang) supaya merata.
BALANCE_FULLTIME_LOAD = True

# ---------------------------------------------------------------------------
# STEP: "find suitable schedule, scale with lecturer count"
# ---------------------------------------------------------------------------
# lecturer_count di course = total dosen yang mengajar bareng (co-teaching).
# Dosen ke-1 (index 0 / "dosen utama") WAJIB dicek bentrok jadwalnya.
# Dosen ke-2 dst boleh bentrok dengan jadwal lain (sesuai flow: "extra
# lecturer can have conflicting schedules") -> hanya dicek eligibility
# (kategori/spesialisasi), TIDAK dicek ketersediaan slot / bentrok.
CHECK_CONFLICT_FOR_PRIMARY_ONLY = True

# ---------------------------------------------------------------------------
# STEP: "if lecturer schedule not enough OR day ran out, find another day,
# must be the same lecturer" (khusus porsi TEORI, bukan blok lab).
# ---------------------------------------------------------------------------
ALLOW_THEORY_SPLIT_ACROSS_DAYS = True
# Blok lab HARUS dalam satu hari (sesi lab tidak dipecah lintas hari).
ALLOW_LAB_SPLIT_ACROSS_DAYS = False

# ---------------------------------------------------------------------------
# STEP (baru): "kalau schedule sudah tidak cukup untuk memenuhi sks_count,
# course_schedule dipecah jadi 2 dengan sisa sks di hari lain, dosen sama".
# ---------------------------------------------------------------------------
# Sebelumnya `_allocate_theory` HANYA pindah ke hari lain kalau hari
# pertama BENAR-BENAR kehabisan slot kontigu (greedy: ambil sebanyak
# mungkin periode kontigu dalam 1 hari dulu). Ini bisa menghabiskan
# hampir seluruh jadwal harian dosen untuk 1 course saja kalau sks-nya
# lumayan besar (3 atau 4).
#
# Kalau `sks_count` course ada di set ini, alokasi teori PROAKTIF dibatasi
# maksimal `ceil(sks_count / 2)` periode per hari (lihat
# `scheduler._day_split_cap`), supaya course_schedule otomatis terpecah
# jadi 2 hari (dosen yang sama) walaupun sebenarnya hari itu masih cukup
# periode buat menampung semuanya sekaligus -- tujuannya supaya jadwal
# harian dosen tidak habis dipakai 1 course saja.
PRIORITIZE_DAY_SPLIT_FOR_SKS = {3, 4}

# ---------------------------------------------------------------------------
# STEP: "if lab, ... 6-7 strategy"
# ---------------------------------------------------------------------------
# Interpretasi yang dipakai di sini (SILAKAN SESUAIKAN):
#   - Untuk course is_lab=True, porsi TEORI = sks_count - LAB_THEORY_SKS_REDUCTION
#     (minimal 0).
#   - Ditambah SATU blok sesi lab yang kontigu, "setara" LAB_BLOCK_SKS_EQUIVALENT
#     periode/sks (default 3), dijadwalkan di ruang lab yang sesuai
#     spesialisasinya.
#   - Total periode yang harus tersedia di jadwal dosen (dipakai untuk cek
#     "course sks <= lecturer schedule count") = teori + blok lab.
LAB_THEORY_SKS_REDUCTION = 1
LAB_BLOCK_SKS_EQUIVALENT = 3

# Kalau True, ruang LAB wajib match spesialisasi (lab_specializations vs
# course_specializations). Kalau course tidak punya spesialisasi terdaftar,
# semua lab dianggap cocok.
LAB_REQUIRE_SPECIALIZATION_MATCH = True

# ---------------------------------------------------------------------------
# STEP: "find suitable rooms by capacity" / "auto scale rooms for split"
# ---------------------------------------------------------------------------
# "best_fit": pilih ruang berkapasitas cukup PALING KECIL (hemat ruang besar
# untuk course yang memang butuh). "first_fit": ruang pertama yang cukup.
ROOM_FIT_STRATEGY = "best_fit"
LAB_FIT_STRATEGY = "best_fit"

# Ruang non-lab (lab_group_id NULL) dipakai untuk sesi teori.
# Ruang ber-lab_group_id dipakai KHUSUS untuk blok sesi lab.
THEORY_USES_NON_LAB_ROOMS_ONLY = True

# ---------------------------------------------------------------------------
# STEP: "auto scale rooms for course split if capacity is over the room
# limit ... prioritize lab capacity over room capacity"
# ---------------------------------------------------------------------------
# Jumlah course_index (kelas paralel A/B/C/...) dihitung dari kapasitas
# course dibagi kapasitas ruang TERBESAR yang tersedia. Untuk course lab,
# turut dihitung juga dari kapasitas LAB terbesar yang match spesialisasi
# -- dan yang menghasilkan jumlah split TERBANYAK yang dipakai (lab
# diprioritaskan karena biasanya kapasitasnya lebih kecil dari ruang kelas).
COURSE_INDEX_LABELS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

# ---------------------------------------------------------------------------
# Fallback reasons (dipakai untuk mengisi lectures.fallback_reason)
# ---------------------------------------------------------------------------
REASON_NO_ELIGIBLE_LECTURER = "No eligible lecturer found (category/specialization/schedule capacity)"
REASON_NO_FREE_SLOT_FOR_ANY_CANDIDATE = "No candidate lecturer has a matching free schedule slot"
REASON_PARTIAL_THEORY = "Theory session not fully satisfied ({done}/{needed} periods scheduled), remaining periods could not get a slot"
REASON_NO_LAB_SLOT = "No suitable lab room slot found (capacity/specialization/schedule) within a single day"
REASON_NO_ROOM = "No room with sufficient capacity found for the selected slot"
REASON_NO_EXTRA_LECTURER = "No eligible additional (co-)lecturer found"
REASON_FORCED_PLACEMENT = "Forcibly scheduled (best-effort) because finding a conflict-free slot failed -- needs manual review"
