// Jenkinsfile - build & deploy startGenerate service
//
// Asumsi: Jenkins agent yang menjalankan pipeline ini ADALAH server tujuan
// deploy (atau punya akses docker ke server itu), karena port service
// sengaja hanya dibind ke 127.0.0.1 (lihat docker-compose.yml) dan tidak
// boleh diakses dari luar host.
//
// Env per-server disimpan sebagai Jenkins "Secret file" credential (isi
// file = isi .env, lihat .env.example untuk daftar variabelnya). Ganti
// ENV_CREDENTIAL_ID di parameters kalau nama credential berbeda per
// environment (staging/production).

pipeline {
    agent any

    parameters {
        string(
            name: 'ENV_CREDENTIAL_ID',
            defaultValue: 'startgenerate-env',
            description: 'ID Jenkins credential (Secret file) berisi .env untuk server tujuan'
        )
    }

    environment {
        IMAGE_NAME = 'startgenerate-service'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Prepare .env') {
            steps {
                withCredentials([file(credentialsId: params.ENV_CREDENTIAL_ID, variable: 'ENV_FILE')]) {
                    sh 'cp "$ENV_FILE" .env'
                }
            }
        }

        stage('Build Image') {
            steps {
                sh 'docker compose build'
            }
        }

        stage('Deploy') {
            steps {
                // "up -d" recreate container kalau image/env berubah, port tetap
                // hanya bind ke 127.0.0.1 sesuai docker-compose.yml.
                sh 'docker compose up -d --remove-orphans'
            }
        }

        stage('Health Check') {
            steps {
                sh '''
                    for i in $(seq 1 10); do
                        if curl -sf -X POST http://127.0.0.1:8082/startGenerate \
                            -H "Content-Type: application/json" \
                            -d '{"secretKey":"__healthcheck__"}' \
                            -o /dev/null -w "%{http_code}" | grep -qE "200|401"; then
                            echo "Service is up"
                            exit 0
                        fi
                        sleep 3
                    done
                    echo "Service did not respond in time"
                    exit 1
                '''
            }
        }
    }

    post {
        always {
            sh 'rm -f .env'
        }
        failure {
            sh 'docker compose logs --tail=100 || true'
        }
    }
}
