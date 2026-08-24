FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY algorithm ./algorithm

# Container jalan di bridge network (lihat docker-compose.yml) dengan port
# di-publish sebagai "127.0.0.1:8082:8082" -- HANYA bisa diakses dari host
# itu sendiri (loopback), tidak dari luar. Bind 0.0.0.0:8082 di bawah ini
# WAJIB (kalau di-bind ke 127.0.0.1 di dalam container, port publish Docker
# tidak akan bisa connect sama sekali karena traffic dari luar container
# masuk lewat interface eth0 container, bukan loopback-nya). Batas
# "local-only" dijaga oleh docker-compose.yml (127.0.0.1:8082:8082), BUKAN
# oleh bind address di sini -- jangan ubah publish port itu jadi "8082:8082"
# saja (itu akan membuka akses dari luar host).
EXPOSE 8082

CMD ["gunicorn", "--bind", "0.0.0.0:8082", "--workers", "2", "--timeout", "60", "app:app"]
