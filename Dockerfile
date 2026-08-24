FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Container jalan dengan network_mode: host (lihat docker-compose.yml),
# jadi gunicorn di-bind langsung ke 127.0.0.1 -- persis seperti kalau
# app.py dijalankan manual tanpa Docker. Ini yang membuat endpoint TIDAK
# bisa diakses dari luar host. JANGAN ganti ke 0.0.0.0:8082, itu akan
# membuat endpoint bisa diakses dari luar host (setara publish 8082:8082).
EXPOSE 8082

CMD ["gunicorn", "--bind", "0.0.0.0:8082", "--workers", "2", "--timeout", "60", "app:app"]
