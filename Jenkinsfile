pipeline {
    agent any
    environment {
        IMAGE_NAME    = 'startgenerate-service'
        IMAGE_TAG     = "${env.BUILD_NUMBER}"
        DEPLOY_DIR    = '/opt/jadwal/startgenerate-service'
        HOST_IP       = '172.17.0.1'
        HOST_USER     = 'root'
        IMAGE_TAR     = "${IMAGE_NAME}-${IMAGE_TAG}.tar.gz"
        REMOTE_SCRIPT = 'deploy_remote.sh'
    }
    stages {
        stage('Clean Workspace') {
            steps {
                // Buang seluruh isi workspace lama (source lama, tar.gz sisa build
                // sebelumnya, dll) SEBELUM checkout & build baru dimulai.
                deleteDir()
            }
        }
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        stage('Clean Local Docker') {
            steps {
                sh '''
                    echo ">>> Membersihkan sisa file & image build sebelumnya di agent..."
                    rm -f ${IMAGE_NAME}-*.tar.gz || true
                    docker images "${IMAGE_NAME}" -f "dangling=true" -q | xargs -r docker rmi -f || true
                    docker image prune -f || true
                '''
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
                    script {
                        // Script deploy ditulis ke FILE TERPISAH (bukan heredoc inline lewat ssh).
                        // Ini memperbaiki bug di build sebelumnya: heredoc "<<EOF" yang tidak
                        // di-quote membuat baris continuation "\" pada command curl ikut
                        // diproses oleh shell LOKAL (agent) sebelum dikirim ke server, sehingga
                        // script yang sampai di server jadi rusak -> "syntax error near
                        // unexpected token `2'". Dengan menulis file utuh lalu di-scp, tidak ada
                        // lagi percampuran ekspansi variabel lokal vs remote.
                        writeFile file: "${env.REMOTE_SCRIPT}", text: """#!/bin/bash
set -e
cd ${env.DEPLOY_DIR}

echo ">>> Membersihkan container & volume lama di server sebelum redeploy..."
docker compose down --remove-orphans -v || true

echo ">>> Membersihkan tar.gz sisa build sebelumnya (kecuali yang baru saja diupload)..."
find . -maxdepth 1 -name "${env.IMAGE_NAME}-*.tar.gz" ! -name "${env.IMAGE_TAR}" -delete || true

docker image prune -f || true

echo ">>> Loading image baru..."
gunzip -c ${env.IMAGE_TAR} | docker load
docker tag ${env.IMAGE_NAME}:${env.IMAGE_TAG} ${env.IMAGE_NAME}:latest

echo ">>> Menjalankan container baru..."
docker compose up -d

for i in \$(seq 1 10); do
    if curl -sf -X POST http://127.0.0.1:8082/startGenerate -H "Content-Type: application/json" -d '{"secretKey":"__healthcheck__"}' -o /dev/null -w "%{http_code}" | grep -qE "200|401"; then
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

rm -f ${env.IMAGE_TAR} .env
docker image prune -f
"""
                    }
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

                        scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
                            "${REMOTE_SCRIPT}" \
                            "$SSH_USER@${HOST_IP}:${DEPLOY_DIR}/${REMOTE_SCRIPT}"

                        ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
                            "$SSH_USER@${HOST_IP}" "bash ${DEPLOY_DIR}/${REMOTE_SCRIPT}"
                    '''
                }
            }
        }
    }
    post {
        always {
            sh '''
                rm -f ${IMAGE_TAR} ${REMOTE_SCRIPT} || true
                docker rmi ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest || true
                docker image prune -f || true
            '''
        }
        success {
            echo 'Pipeline berhasil! startGenerate service jalan di port 8082 (local only, host 103.185.52.80).'
        }
        failure {
            echo 'Pipeline gagal! Periksa log di atas (log docker compose sudah ikut ditampilkan kalau health check yang gagal).'
        }
    }
}
