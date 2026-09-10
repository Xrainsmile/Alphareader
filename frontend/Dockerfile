# ── Stage 1: Build ──
FROM node:20-alpine AS builder
WORKDIR /app

# 从 docker-compose build args 接收 API Key
# （已被下方探测取代；保留声明仅为兼容历史 compose 文件，当前不再用于注入）
ARG VITE_API_KEY

COPY package.json ./
RUN npm install --registry=https://registry.npmmirror.com
COPY . .

# 不再把 API Key 写进 .env.production。
# 原因：VITE_ 变量会在构建时被 Vite 内联进 H5 产物，而 H5 是公开可下载的，
# 等同于把密钥公开；且轮换密钥后必须重建前端，否则页面 403 空白。
# 现在改为由 Nginx 反向代理统一注入 X-API-Key（见 deploy/nginx/conf.d/*.template），
# 密钥只存在于服务器根目录 .env，轮换无需重建。
RUN rm -f .env.production .env.local .env

RUN npm run build:h5
# uni-app build does not copy public/ automatically; copy static assets manually
RUN cp -r public/* dist/build/h5/ 2>/dev/null || true

# 安全兜底：构建产物中若残留疑似 API Key（nb- 前缀 32 位十六进制）则立即构建失败。
# 防止有人重新引入 .env.production 或硬编码密钥而未被察觉。
RUN if grep -rlE 'nb-[a-f0-9]{32}' dist/ 2>/dev/null | head -1 | grep -q .; then \
      echo "ERROR: 构建产物中检测到疑似 API Key，已中止（密钥不应内联进前端产物）"; \
      grep -rlE 'nb-[a-f0-9]{32}' dist/ 2>/dev/null | head -5; \
      exit 1; \
    fi

# ── Stage 2: Serve ──
FROM nginx:alpine
# Copy default Nginx config (may be overridden by volume mount in production)
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist/build/h5 /usr/share/nginx/html
EXPOSE 80 443
