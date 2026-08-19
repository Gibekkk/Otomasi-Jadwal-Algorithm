FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Gunicorn dibind ke 0.0.0.0 di DALAM container (wajib, kalau tidak port
# tidak bisa di-publish sama sekali). Isolasi "local only" dilakukan di
# LUAR container lewat docker run/compose: publish ke 127.0.0.1:8082 saja
# (lihat Jenkinsfile / docker run command), bukan 0.0.0.0:8082 -- supaya
# port TIDAK bisa diakses dari luar host.
EXPOSE 8082

CMD ["gunicorn", "--bind", "0.0.0.0:8082", "--workers", "2", "--timeout", "60", "app:app"]
