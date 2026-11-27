#!/usr/bin/env bash
# Local check for cron; Redis credentials stay inside the backend container.
set -Eeuo pipefail
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
docker exec -i chatbot-demo-backend-1 python - < "$script_dir/monitor_redis_capacity.py"
