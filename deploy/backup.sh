#!/bin/sh
# Respaldo diario de la base SQLite; conserva 14 días.
set -e
cd /srv/signature/backend
. ./.venv/bin/activate
set -a; . ./.env; set +a
python -m app.cli backup "/srv/signature/backups/signature-$(date +%Y%m%d-%H%M).db"
find /srv/signature/backups -name 'signature-*.db' -mtime +14 -delete
