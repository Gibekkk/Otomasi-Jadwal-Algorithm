pipeline {
    agent any

    environment {
        IMAGE_NAME = 'startgenerate-service'
        IMAGE_TAG  = "${env.BUILD_NUMBER}"
        DEPLOY_DIR = '/opt/jadwal/startgenerate-service'
        HOST_IP    = '103.185.52.80'
        HOST_USER  = 'root'
        IMAGE_TAR  = "${IMAGE_NAME}-${IMAGE_TAG}.tar.gz"
    }

    stages {

        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build Image') {
            steps {
                sh '''
                    docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .
                    docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest
                '''
            }
        }

        stage('Save Image') {
            steps {
                sh '''
                    docker save ${IMAGE_NAME}:${IMAGE_TAG} | gzip > ${IMAGE_TAR}
                '''
            }
        }

        stage('Transfer & Deploy') {
            steps {
                withCredentials([
                    file(credentialsId: 'startgenerate-env', variable: 'ENV_FILE'),
                    sshUserPrivateKey(
                        credentialsId: 'jadwal-host-ssh',
                        keyFileVariable: 'SSH_KEY',
                        usernameVariable: 'SSH_USER'
                    )
                ]) {
                    sh '''
                        ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
                            "$SSH_USER@${HOST_IP}" "mkdir -p ${DEPLOY_DIR}"

                        scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
                            "${IMAGE_TAR}" \
                            "$SSH_USER@${HOST_IP}:${DEPLOY_DIR}/${IMAGE_TAR}"

                        scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
                            docker-compose.yml \
                            "$SSH_USER@${HOST_IP}:${DEPLOY_DIR}/docker-compose.yml"

                        scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
                            "$ENV_FILE" "$SSH_USER@${HOST_IP}:${DEPLOY_DIR}/.env"

                        # Catatan: dikirim lewat heredoc (bukan satu baris "a && b && c"
                        # seperti biasa) khusus supaya bagian health check ($i, $(seq...))
                        # AMAN -- tidak tereksekusi duluan di Jenkins agent. Semua variabel
                        # ${...} di bawah ini (DEPLOY_DIR, IMAGE_TAR, dst) tetap disubstitusi
                        # oleh shell Jenkins agent SEBELUM dikirim ke server tujuan, seperti
                        # command lain di stage ini -- cuma \$i dan \$(seq...) yang sengaja
                        # di-escape supaya dievaluasi di server tujuan, bukan di sini.
                        ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
                            "$SSH_USER@${HOST_IP}" bash -s <<EOF
set -e
cd ${DEPLOY_DIR}
docker compose down || true
gunzip -c ${IMAGE_TAR} | docker load
docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest
docker compose up -d

for i in \$(seq 1 10); do
    if curl -sf -X POST http://127.0.0.1:8082/startGenerate \
        -H "Content-Type: application/json" \
        -d '{"secretKey":"__healthcheck__"}' \
        -o /dev/null -w "%{http_code}" | grep -qE "200|401"; then
        echo "Service is up"
        break
    fi
    if [ "\$i" = "10" ]; then
        echo "Service did not respond in time"
        docker compose logs --tail=100
        exit 1
    fi
    sleep 3
done

rm -f ${IMAGE_TAR} .env
docker image prune -f
EOF
                    '''
                }
            }
        }
    }

    post {
        always {
            sh 'rm -f ${IMAGE_TAR} || true'
            sh 'docker rmi ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest || true'
        }
        success {
            echo 'Pipeline berhasil! startGenerate service jalan di port 8082 (local only, host 103.185.52.80).'
        }
        failure {
            echo 'Pipeline gagal! Periksa log di atas (log docker compose sudah ikut ditampilkan kalau health check yang gagal).'
        }
    }
}
