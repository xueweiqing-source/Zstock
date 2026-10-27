#!/bin/bash
# stock-forecast 一键部署脚本（目标：京东云 CentOS7 + nginx 1.20 + Python 3.11）
# 用法：bash install.sh
set -euo pipefail

APP_DIR=/var/www/stock-forecast
NGINX_CONF=/etc/nginx/conf.d/znote.conf
PY=/usr/local/bin/python3.11
SERVICE_SRC="$APP_DIR/deploy/stock-forecast.service"
STAMP=$(date +%Y%m%d%H%M%S)

echo "== 1. 备份 nginx 配置 =="
cp -a "$NGINX_CONF" "${NGINX_CONF}.bak_${STAMP}"
echo "备份 -> ${NGINX_CONF}.bak_${STAMP}"

echo "== 2. 创建 venv 并安装依赖 =="
cd "$APP_DIR"
if [ ! -d venv ]; then
  "$PY" -m venv venv
fi
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q

echo "== 3. 凭据环境文件（/etc/stock-forecast.env，权限 600，不入库） =="
ENV_FILE=/etc/stock-forecast.env
if [ -f "$ENV_FILE" ]; then
  echo "$ENV_FILE 已存在，保留现有凭据"
else
  ADMIN_PW=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 20)
  SECRET=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  umask 077
  cat > "$ENV_FILE" <<EOF
SF_ADMIN_USER=admin
SF_ADMIN_PASSWORD=${ADMIN_PW}
SF_SECRET_KEY=${SECRET}
# LLM 研判（可选，不配置则降级为规则叙事）
#LLM_API_BASE=https://api.deepseek.com/v1
#LLM_API_KEY=
#LLM_MODEL=deepseek-chat
EOF
  echo "已生成 ${ENV_FILE}，登录口令如下（请妥善保存）："
  echo "  账号 admin"
  echo "  口令 ${ADMIN_PW}"
fi
chmod 600 "$ENV_FILE"

echo "== 4. 安装 systemd 服务 =="
cp "$SERVICE_SRC" /etc/systemd/system/stock-forecast.service
systemctl daemon-reload
systemctl enable stock-forecast.service
systemctl restart stock-forecast.service
sleep 2
systemctl --no-pager status stock-forecast.service | head -12

echo "== 5. 写入 nginx location（已存在则跳过） =="
if ! grep -q "location ^~ /forecast/" "$NGINX_CONF"; then
  # 用临时文件 + sed r 插入，避免远端 sed 多行丢换行
  TMPF=$(mktemp)
  cat "$APP_DIR/deploy/nginx-forecast.conf" > "$TMPF"
  # 插入到最后一个 } 之前：先找到 server 块结束——znote.conf 结构简单，插到文件末尾 server 内
  # 这里用 python 精确插入到最后一个 '}' 之前
  "$PY" - "$NGINX_CONF" "$TMPF" <<'PYEOF'
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

echo "== 6. 校验并 reload nginx =="
nginx -t
systemctl reload nginx

echo "== 7. 写入 crontab（每日 22:00，预测次一交易日） =="
CRON_LINE='0 22 * * * TZ=Asia/Shanghai /var/www/stock-forecast/venv/bin/python /var/www/stock-forecast/run_pipeline.py >> /var/log/stock-forecast-cron.log 2>&1'
# 注意：crontab -l 在空表时返回非零，必须用临时文件合并，避免 set -e / pipefail 中断
TMP_CRON=$(mktemp)
crontab -l 2>/dev/null | grep -v 'run_pipeline.py' > "$TMP_CRON" || true
echo "$CRON_LINE" >> "$TMP_CRON"
crontab "$TMP_CRON"
rm -f "$TMP_CRON"
echo "当前 crontab："
crontab -l

echo "== 8. 首次生成报告 =="
"$APP_DIR/venv/bin/python" "$APP_DIR/run_pipeline.py" || echo "首次报告生成失败，请查看日志"

echo "== 9. 验收 =="
sleep 1
echo "-- healthz --"
curl -sS "http://127.0.0.1:8501/healthz" || true
echo ""
echo "-- 未登录应 302 到 login --"
curl -sSI "http://127.0.0.1/forecast/" | head -5 || true
echo "-- 经 nginx 的 healthz --"
curl -sS "http://127.0.0.1/forecast/healthz" || true
echo ""
echo "部署完成。"
echo "  访问：http://36.151.142.130/forecast/"
echo "  登录口令见 ${ENV_FILE}（若本次为首次安装，已在上方打印）"
echo "  修改口令：编辑 ${ENV_FILE} 后 systemctl restart stock-forecast"
