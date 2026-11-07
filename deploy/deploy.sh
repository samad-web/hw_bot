#!/usr/bin/env bash
# Deploy the Blinkit Hot Wheels bot to a Hostinger VPS.
#
#   ./deploy/deploy.sh [user@host] [remote_dir]
#
# Defaults to the Mumbai box. Run it from the repo root, after:
#   python main.py --login            (OTP once, set the delivery address)
#   python main.py --export-session   (writes session.json)
set -euo pipefail

HOST="${1:-root@93.127.199.127}"
REMOTE_DIR="${2:-/opt/hw_bot}"

cd "$(dirname "$0")/.."

for f in .env session.json config.yaml Dockerfile docker-compose.yml; do
  [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }
done

echo "==> Checking Docker on $HOST"
ssh "$HOST" 'command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh'

echo "==> Creating $REMOTE_DIR"
# Directories, not single files: state.json is rewritten with os.replace(),
# which fails with EBUSY against a bind-mounted file.
ssh "$HOST" "mkdir -p '$REMOTE_DIR/data' '$REMOTE_DIR/logs' '$REMOTE_DIR/profile-docker'"

echo "==> Copying source"
scp -q Dockerfile docker-compose.yml requirements.txt config.yaml \
       main.py config.py checker.py executor.py notifier.py state.py \
       logger.py hardening.py "$HOST:$REMOTE_DIR/"

echo "==> Copying secrets (never baked into the image)"
scp -q .env session.json "$HOST:$REMOTE_DIR/"
ssh "$HOST" "chmod 600 '$REMOTE_DIR/.env' '$REMOTE_DIR/session.json'"

echo "==> Building and starting"
ssh "$HOST" "cd '$REMOTE_DIR' && docker compose up -d --build"
ssh "$HOST" "cd '$REMOTE_DIR' && docker compose ps"

echo
echo "Deployed. Follow logs with:"
echo "  ssh $HOST \"cd $REMOTE_DIR && docker compose logs -f\""
