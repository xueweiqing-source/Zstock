#!/bin/bash
# Zstock Docker 部署脚本（目标：已有 Docker + mysql:8.0 镜像的服务器）
# 用法：bash deploy/install-docker.sh
set -euo pipefail

APP_DIR=/var/www/stock-forecast
NGINX_CONF=/etc/nginx/conf.d/znote.conf
ENV_FILE="$APP_DIR/.env"
STAMP=$(date +%Y%m%d%H%M%S)

cd "$APP_DIR"

echo "== 1. 备份 nginx 配置 =="
cp -a "$NGINX_CONF" "${NGINX_CONF}.bak_${STAMP}"
echo "备份 -> ${NGINX_CONF}.bak_${STAMP}"

echo "== 2. 生成 .env（凭据，权限 600，已 gitignore） =="
if [ -f "$ENV_FILE" ]; then
  echo ".env 已存在，保留现有凭据"
else
  umask 077
  ADMIN_PW=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 20)
  ROOT_PW=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 24)
  DB_PW=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 24)
  SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  cat > "$ENV_FILE" <<EOF
# ---- Web 鉴权 ----
SF_ADMIN_USER=admin
SF_ADMIN_PASSWORD=${ADMIN_PW}
SF_SECRET_KEY=${SECRET}

# ---- MySQL（容器初始化用）----
DB_ROOT_PASSWORD=${ROOT_PW}
MYSQL_DATABASE=zstock
MYSQL_USER=zstock
MYSQL_PASSWORD=${DB_PW}

# ---- LLM 研判（可选，不填则降级为规则叙事）----
#LLM_API_BASE=https://api.deepseek.com/v1
#LLM_API_KEY=
#LLM_MODEL=deepseek-chat
EOF
  echo "已生成 ${ENV_FILE}，登录口令如下（请妥善保存）："
  echo "  账号 admin"
  echo "  口令 ${ADMIN_PW}"
fi
chmod 600 "$ENV_FILE"

echo "== 3. 构建镜像 =="
docker compose build

echo "== 4. 启动（web + mysql） =="
docker compose up -d
echo "等待 MySQL 就绪 …"
for i in $(seq 1 30); do
  if docker compose exec -T mysql mysqladmin ping -h localhost -uroot -p"$(grep '^DB_ROOT_PASSWORD=' "$ENV_FILE" | cut -d= -f2)" --silent 2>/dev/null; then
    echo "MySQL 就绪"; break
  fi
  sleep 2
done

echo "== 5. 初始化表结构 =="
docker compose exec -T web python -c "import db; db.init_db(); print('表结构 OK')"

echo "== 6. 迁移历史数据（若有） =="
if [ -f "$APP_DIR/data/forecast.db" ]; then
  echo "检测到 SQLite 历史数据，迁移中 …"
  docker compose exec -T web python deploy/migrate_sqlite_to_mysql.py --sqlite data/forecast.db || \
    echo "迁移失败（可稍后手动重跑），继续"
else
  echo "无历史 SQLite 数据，跳过"
fi

echo "== 7. 写入 nginx location（已存在则跳过） =="
if ! grep -q "location ^~ /forecast/" "$NGINX_CONF"; then
  TMPF=$(mktemp)
  cat "$APP_DIR/deploy/nginx-forecast.conf" > "$TMPF"
  /usr/local/bin/python3.11 - "$NGINX_CONF" "$TMPF" <<'PYEOF'
import sys
conf, frag = sys.argv[1], sys.argv[2]
text = open(conf, encoding='utf-8').read()
block = open(frag, encoding='utf-8').read()
idx = text.rfind('}')
if idx == -1:
    raise SystemExit('cannot find closing brace')
new = text[:idx] + '\n' + block + '\n' + text[idx:]
open(conf, 'w', encoding='utf-8').write(new)
print('nginx conf updated')
PYEOF
  rm -f "$TMPF"
else
  echo "已存在 /forecast/ location，跳过"
fi

echo "== 8. 校验并 reload nginx =="
nginx -t
systemctl reload nginx

echo "== 9. 停掉旧的 systemd 服务（改由 Docker 接管） =="
systemctl disable --now stock-forecast.service 2>/dev/null || true
rm -f /etc/systemd/system/stock-forecast.service
systemctl daemon-reload
echo "旧 systemd 服务已移除"

echo "== 10. 写入 crontab（每日 22:00，容器内跑流水线） =="
CRON_LINE="0 22 * * * cd ${APP_DIR} && /usr/bin/docker compose exec -T web python run_pipeline.py >> /var/log/stock-forecast-cron.log 2>&1"
TMP_CRON=$(mktemp)
crontab -l 2>/dev/null | grep -v 'run_pipeline.py' > "$TMP_CRON" || true
echo "$CRON_LINE" >> "$TMP_CRON"
crontab "$TMP_CRON"
rm -f "$TMP_CRON"
echo "当前 crontab："
crontab -l

echo "== 11. 验收 =="
sleep 2
docker compose ps
echo "-- healthz --"
curl -sS "http://127.0.0.1:8501/healthz" || true
echo ""
echo "-- 未登录应 302 --"
curl -sSI "http://127.0.0.1/forecast/" | head -3 || true
echo "-- 经 nginx 的 healthz --"
curl -sS "http://127.0.0.1/forecast/healthz" || true
echo ""
echo "部署完成。"
echo "  访问：http://36.151.142.130/forecast/"
echo "  登录口令见 ${ENV_FILE}"
echo "  改口令：vi ${ENV_FILE} && docker compose restart web"
