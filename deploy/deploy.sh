#!/usr/bin/env bash
# ============================================
# AlphaReader - Server Deployment Script
# Run on the Lighthouse server after cloning the repo
# Usage: bash deploy/deploy.sh YOUR_DOMAIN your@email.com
# ============================================
set -euo pipefail

DOMAIN="${1:?Usage: bash deploy/deploy.sh YOUR_DOMAIN your@email.com}"
EMAIL="${2:?Usage: bash deploy/deploy.sh YOUR_DOMAIN your@email.com}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "══════════════════════════════════════"
echo "  AlphaReader Deployment"
echo "  Domain: ${DOMAIN}"
echo "  Email:  ${EMAIL}"
echo "══════════════════════════════════════"

cd "$PROJECT_DIR"

# ── Step 1: System dependencies ──
echo ""
echo "▶ [1/7] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq docker.io docker-compose-plugin certbot curl git

# Enable Docker for current user
sudo usermod -aG docker "$USER" 2>/dev/null || true

# ── Step 2: Replace domain placeholder in configs ──
echo ""
echo "▶ [2/7] Configuring domain: ${DOMAIN}..."
sed -i "s/YOUR_DOMAIN/${DOMAIN}/g" deploy/nginx/conf.d/default.conf
sed -i "s/YOUR_DOMAIN/${DOMAIN}/g" .env

# ── Step 3: Setup .env from production template ──
echo ""
echo "▶ [3/7] Setting up environment..."
if [ ! -f .env ]; then
    cp .env.production .env
    sed -i "s/YOUR_DOMAIN/${DOMAIN}/g" .env
    echo "⚠  Created .env from template. Please edit .env to set:"
    echo "   - DEEPSEEK_API_KEY"
    echo "   - POSTGRES_PASSWORD (use a strong random password)"
    echo ""
    read -p "Press Enter after editing .env, or Ctrl+C to abort..."
fi

# ── Step 4: Get SSL certificate (HTTP-only first) ──
echo ""
echo "▶ [4/7] Obtaining SSL certificate..."

# Temporarily start with HTTP-only config for certbot
cat > deploy/nginx/conf.d/default.conf.tmp <<'TMPCONF'
server {
    listen 80;
    server_name _;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 200 'AlphaReader setup in progress';
        add_header Content-Type text/plain;
    }
}
TMPCONF

# Swap to temp config, start nginx, get cert, restore real config
cp deploy/nginx/conf.d/default.conf deploy/nginx/conf.d/default.conf.bak
cp deploy/nginx/conf.d/default.conf.tmp deploy/nginx/conf.d/default.conf

docker compose -f docker-compose.yml up -d frontend
sleep 3

sudo certbot certonly --webroot \
    -w deploy/certbot/www \
    -d "${DOMAIN}" \
    -d "www.${DOMAIN}" \
    --email "${EMAIL}" \
    --agree-tos \
    --non-interactive

# Copy certs to deploy directory
sudo cp -rL /etc/letsencrypt/live deploy/certbot/conf/ 2>/dev/null || true
sudo cp -rL /etc/letsencrypt/archive deploy/certbot/conf/ 2>/dev/null || true
sudo cp /etc/letsencrypt/options-ssl-nginx.conf deploy/certbot/conf/ 2>/dev/null || true

# Restore real Nginx config
cp deploy/nginx/conf.d/default.conf.bak deploy/nginx/conf.d/default.conf
rm -f deploy/nginx/conf.d/default.conf.tmp deploy/nginx/conf.d/default.conf.bak

# ── Step 5: Run Alembic migration ──
echo ""
echo "▶ [5/7] Running database migration..."
docker compose -f docker-compose.yml up -d db cache
sleep 5

docker compose -f docker-compose.yml run --rm web \
    python -m alembic upgrade head

# ── Step 6: Start all services ──
echo ""
echo "▶ [6/7] Starting all services..."
docker compose -f docker-compose.yml up -d --build

# ── Step 7: Verify ──
echo ""
echo "▶ [7/7] Verifying deployment..."
sleep 10

if curl -sf "http://localhost:8000/api/v1/health" > /dev/null 2>&1; then
    echo "✅ Backend health check passed"
else
    echo "⚠  Backend health check failed — check logs: docker compose logs web"
fi

if curl -sf "https://${DOMAIN}" > /dev/null 2>&1; then
    echo "✅ Frontend accessible at https://${DOMAIN}"
else
    echo "⚠  Frontend not yet accessible — DNS may need time to propagate"
fi

echo ""
echo "══════════════════════════════════════"
echo "  Deployment complete!"
echo ""
echo "  Frontend:  https://${DOMAIN}"
echo "  API:       https://${DOMAIN}/api/v1/health"
echo ""
echo "  Useful commands:"
echo "    docker compose -f docker-compose.yml logs -f web    # Backend logs"
echo "    docker compose -f docker-compose.yml logs -f frontend  # Nginx logs"
echo "    docker compose -f docker-compose.yml restart web    # Restart backend"
echo "══════════════════════════════════════"

# ── Setup certbot auto-renewal cron ──
echo ""
echo "▶ Setting up SSL auto-renewal..."
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && cd ${PROJECT_DIR} && docker compose -f docker-compose.yml restart frontend") | sort -u | crontab -
echo "✅ Certbot renewal cron added (daily 3:00 AM)"
