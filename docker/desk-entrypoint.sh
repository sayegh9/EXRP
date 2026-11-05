#!/bin/bash
set -e

echo "=== Initializing EXRP Frappe Desk Environment ==="

# 1. Ensure Python environment has exrp installed
export PYTHONPATH="/home/frappe/frappe-bench/apps/exrp:${PYTHONPATH}"
if [ -d "/home/frappe/frappe-bench/env/bin" ]; then
    /home/frappe/frappe-bench/env/bin/pip install -e /home/frappe/frappe-bench/apps/exrp --no-deps 2>/dev/null || true
fi

# 2. Configure common_site_config.json
cat <<EOF > /home/frappe/frappe-bench/sites/common_site_config.json
{
  "db_host": "exrp-mariadb",
  "db_port": 3306,
  "redis_cache": "redis://exrp-redis-cache:6379",
  "redis_queue": "redis://exrp-redis-queue:6379",
  "redis_socketio": "redis://exrp-redis-queue:6379",
  "auto_update": false
}
EOF

# 3. Ensure apps.txt has exrp
if ! grep -q "^exrp$" /home/frappe/frappe-bench/sites/apps.txt 2>/dev/null; then
  echo "exrp" >> /home/frappe/frappe-bench/sites/apps.txt
fi

# 4. Link EXRP public assets to bench assets directory
mkdir -p /home/frappe/frappe-bench/sites/assets/exrp/js
mkdir -p /home/frappe/frappe-bench/sites/assets/exrp/css
cp -r /home/frappe/frappe-bench/apps/exrp/exrp/public/js/* /home/frappe/frappe-bench/sites/assets/exrp/js/ 2>/dev/null || true
cp -r /home/frappe/frappe-bench/apps/exrp/exrp/public/css/* /home/frappe/frappe-bench/sites/assets/exrp/css/ 2>/dev/null || true

# Also symlink into baked assets
mkdir -p /home/frappe/frappe-bench/assets
ln -sfn /home/frappe/frappe-bench/apps/exrp/exrp/public /home/frappe/frappe-bench/assets/exrp 2>/dev/null || true

SITE_NAME="exrp.localhost"
echo "Active site: ${SITE_NAME}"
bench use ${SITE_NAME} 2>/dev/null || true
cd /home/frappe/frappe-bench/sites
ln -sfn ${SITE_NAME} localhost 2>/dev/null || true
ln -sfn ${SITE_NAME} 127.0.0.1 2>/dev/null || true

# 5. Ensure demo ERP DocTypes & sample records exist
/home/frappe/frappe-bench/env/bin/python -c "
import frappe
frappe.init(site='${SITE_NAME}')
frappe.connect()
from exrp.setup_demo_doctypes import ensure_demo_erp_doctypes
ensure_demo_erp_doctypes()
" 2>/dev/null || true

echo "=== Launching Frappe Gunicorn with Statics on 0.0.0.0:8000 (Mapped to 8088 on Host) ==="
exec /home/frappe/frappe-bench/env/bin/gunicorn \
  --chdir=/home/frappe/frappe-bench/apps/exrp/docker \
  --bind=0.0.0.0:8000 \
  --threads=4 \
  --workers=2 \
  --worker-class=gthread \
  --worker-tmp-dir=/dev/shm \
  --timeout=120 \
  wsgi:application
