# startGenerate service

Local-only server, port 8082, satu endpoint: `POST /startGenerate`.

## Jalan manual (tanpa Docker)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # isi sesuai DB & Java backend
python app.py
```

## Jalan via Docker

```bash
cp .env.example .env   # isi sesuai server
docker compose up -d --build
```

`docker-compose.yml` publish port dengan `127.0.0.1:8082:8082` -- HANYA
bisa diakses dari host itu sendiri, tidak dari luar. Jangan ubah jadi
`8082:8082` saja (itu bind ke semua interface / bisa diakses dari luar).

## Deploy via Jenkins

`Jenkinsfile` build image lalu `docker compose up -d` di agent (agent =
server tujuan deploy, karena service ini local-only).

Env per-server disimpan sebagai Jenkins credential jenis **Secret file**
(isi file = isi `.env`), lalu di-inject lewat parameter `ENV_CREDENTIAL_ID`
(default `startgenerate-env`). Buat credential berbeda untuk tiap
environment (mis. `startgenerate-env-staging`, `startgenerate-env-prod`)
kalau perlu.

## Request

```bash
curl -X POST http://127.0.0.1:8082/startGenerate \
  -H "Content-Type: application/json" \
  -d '{"secretKey": "<secret dari kolom secret_key di free_tables>"}'
```

## Syarat

- Kolom `secret_key` (VARCHAR) harus ada di tabel `free_tables` (sudah
  ditambahkan di `FreeTable.java`).
- `JAVA_ADMIN_USERNAME` / `JAVA_ADMIN_PASSWORD` di `.env` harus akun dengan
  role SuperAdmin/BaaAdmin/ProdiAdmin, dipakai service ini login ke
  `{JAVA_BASE_URL}{API_PREFIX}/auth/login` untuk dapat Token.

## Alur

1. Validasi `secretKey` terhadap `free_tables.secret_key`.
2. Kalau valid: rotasi `secret_key` (UUID baru di-hash SHA-256), sleep
   `GENERATE_SLEEP_SECONDS` detik (simulasi generate).
3. Login sebagai admin, lalu POST secret key baru (raw text) + header
   `Token` ke `{JAVA_BASE_URL}{API_PREFIX}/timeline/generateComplete`.
   Endpoint itu yang men-set `is_generating = false` di backend Java.
4. Kalau secretKey tidak valid: balas 401.
