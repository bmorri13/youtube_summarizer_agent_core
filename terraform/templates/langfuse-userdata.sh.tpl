#!/bin/bash
set -euo pipefail

# --- Install Docker + EC2 Instance Connect + ensure SSM agent runs ---
dnf install -y docker ec2-instance-connect
systemctl enable docker
systemctl start docker
systemctl enable amazon-ssm-agent
systemctl start amazon-ssm-agent

# --- Install Docker Compose v2 plugin ---
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# --- Write compose file ---
mkdir -p /opt/langfuse
cat > /opt/langfuse/docker-compose.yml << 'COMPOSE_EOF'
${compose_file}
COMPOSE_EOF

# --- Create systemd service for auto-restart on reboot ---
cat > /etc/systemd/system/langfuse.service << 'SYSTEMD_EOF'
[Unit]
Description=Langfuse v3 Docker Compose
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/langfuse
ExecStart=/usr/local/lib/docker/cli-plugins/docker-compose up -d
ExecStop=/usr/local/lib/docker/cli-plugins/docker-compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

systemctl daemon-reload
systemctl enable langfuse.service

# --- Start services ---
cd /opt/langfuse
docker compose up -d
