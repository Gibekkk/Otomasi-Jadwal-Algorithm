// Jenkinsfile - build & deploy startGenerate service
//
// Alur: build image di Jenkins agent, lalu di-transfer (scp) ke server
// tujuan dan dijalankan di sana (ssh). Jenkins agent TIDAK harus sama
// dengan server tujuan lagi.
//
// PENTING: karena service sengaja hanya dibind ke 127.0.0.1 di server
// tujuan (lihat docker-compose.yml -- network_mode: host + gunicorn
// bind 127.0.0.1) dan tidak boleh diakses dari luar host, stage
// "Deploy on Server" dan "Health Check" dijalankan lewat SSH DI SERVER
// TUJUAN itu sendiri, bukan dari Jenkins agent.
//
// Kredensial yang dipakai:
// - 'startgenerate-env' (Secret file): isi = isi .env, lihat .env.example
//   untuk daftar variabelnya.
// - 'jadwal-host-ssh' (SSH Username with private key): private key untuk
//   SSH ke server tujuan. Public key-nya harus ada di authorized_keys
//   user tersebut di server tujuan, dan user itu harus punya akses ke
//   docker (masuk grup "docker" atau setara).

pipeline {
    agent any

    parameters {
        string(
            name: 'DEPLOY_HOST',
            defaultValue: '',
            description: 'Hostname/IP server tujuan deploy (WAJIB diisi)'
        )
        string(
            name: 'DEPLOY_PATH',
            defaultValue: '/opt/startgenerate-service',
            description: 'Direktori di server tujuan untuk docker-compose.yml, .env, dan image tar'
        )
    }

    environment {
        IMAGE_NAME = 'startgenerate-service'
        IMAGE_TAR  = "startgenerate-service-${env.BUILD_NUMBER}.tar.gz"
        // accept-new: host baru otomatis dipercaya & disimpan, host yang
        // sudah dikenal tetap diverifikasi (lebih aman daripada
        // StrictHostKeyChecking=no yang mematikan verifikasi sama sekali).
        SSH_OPTS   = '-o StrictHostKeyChecking=accept-new'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Preflight') {
            steps {
                script {
                    if (!params.DEPLOY_HOST?.trim()) {
                        error 'Parameter DEPLOY_HOST wajib diisi (hostname/IP server tujuan).'
                    }
                }
            }
        }

        stage('Prepare .env') {
            steps {
                withCredentials([file(credentialsId: 'startgenerate-env', variable: 'ENV_FILE')]) {
                    sh 'cp "$ENV_FILE" .env'
                }
            }
        }

        stage('Build Image') {
            steps {
                // Build & tag "startgenerate-service:latest" di Jenkins
                // agent -- TIDAK di server tujuan. .env di sini cuma
                // dipakai kalau ada build-arg/context yang butuh, image
                // build sendiri tidak butuh isi .env (env dibaca saat
                // container jalan, bukan saat build).
                sh 'docker compose build'
            }
        }

        stage('Save Image') {
            steps {
                // Export image ke tar.gz supaya bisa ditransfer ke server
                // tujuan tanpa lewat registry.
                sh 'docker save "$IMAGE_NAME:latest" | gzip > "$IMAGE_TAR"'
            }
        }

        stage('Transfer to Server') {
            steps {
                withCredentials([sshUserPrivateKey(
                    credentialsId: 'jadwal-host-ssh',
                    keyFileVariable: 'SSH_KEY',
                    usernameVariable: 'SSH_USER'
                )]) {
                    sh '''
                        ssh -i "$SSH_KEY" $SSH_OPTS "$SSH_USER@$DEPLOY_HOST" "mkdir -p '$DEPLOY_PATH'"
                        scp -i "$SSH_KEY" $SSH_OPTS "$IMAGE_TAR" docker-compose.yml .env \
                            "$SSH_USER@$DEPLOY_HOST:$DEPLOY_PATH/"
                    '''
                }
            }
        }

        stage('Deploy on Server') {
            steps {
                withCredentials([sshUserPrivateKey(
                    credentialsId: 'jadwal-host-ssh',
                    keyFileVariable: 'SSH_KEY',
                    usernameVariable: 'SSH_USER'
                )]) {
                    // Heredoc TIDAK di-quote ("<<EOF") supaya $DEPLOY_PATH
                    // dan $IMAGE_TAR di-substitusi oleh shell LOKAL (Jenkins
                    // agent) sebelum dikirim lewat ssh -- jadi shell di
                    // server tujuan cukup terima teks literal, tidak perlu
                    // tahu variabel Jenkins apapun.
                    // "docker compose up -d" tidak akan build ulang selama
                    // image "startgenerate-service:latest" sudah ada hasil
                    // "docker load" di atasnya -- jadi server tujuan TIDAK
                    // butuh Dockerfile/app.py, cukup docker-compose.yml + .env.
                    sh '''
                        ssh -i "$SSH_KEY" $SSH_OPTS "$SSH_USER@$DEPLOY_HOST" bash -s <<EOF
set -e
cd "$DEPLOY_PATH"
gunzip -c "$IMAGE_TAR" | docker load
docker compose up -d --remove-orphans
rm -f "$IMAGE_TAR"
EOF
                    '''
                }
            }
        }

        stage('Health Check') {
            steps {
                withCredentials([sshUserPrivateKey(
                    credentialsId: 'jadwal-host-ssh',
                    keyFileVariable: 'SSH_KEY',
                    usernameVariable: 'SSH_USER'
                )]) {
                    // Heredoc di-quote ("<<'EOF'") di sini karena SEMUA isi
                    // script (termasuk $(seq ...), $i, dan %{http_code})
                    // harus dievaluasi di server tujuan, bukan di Jenkins
                    // agent. Endpoint cuma bisa diakses dari 127.0.0.1 milik
                    // server tujuan sendiri, makanya curl-nya jalan di sana.
                    sh '''
                        ssh -i "$SSH_KEY" $SSH_OPTS "$SSH_USER@$DEPLOY_HOST" bash -s <<'EOF'
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
EOF
                    '''
                }
            }
        }
    }

    post {
        always {
            // Bersihkan file sensitif/sementara di Jenkins agent.
            sh 'rm -f .env "$IMAGE_TAR"'
        }
        failure {
            withCredentials([sshUserPrivateKey(
                credentialsId: 'jadwal-host-ssh',
                keyFileVariable: 'SSH_KEY',
                usernameVariable: 'SSH_USER'
            )]) {
                sh '''
                    ssh -i "$SSH_KEY" $SSH_OPTS "$SSH_USER@$DEPLOY_HOST" bash -s <<EOF || true
cd "$DEPLOY_PATH"
docker compose logs --tail=100
EOF
                '''
            }
        }
    }
}
