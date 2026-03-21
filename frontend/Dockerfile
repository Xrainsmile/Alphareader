# ── Stage 1: Build ──
FROM node:20-alpine AS builder
WORKDIR /app

# 从 docker-compose build args 接收 API Key
ARG VITE_API_KEY

COPY package.json ./
RUN npm install --registry=https://registry.npmmirror.com
COPY . .

# 用 build arg 覆盖 .env.production，确保 key 来自根目录 .env
RUN echo "VITE_API_KEY=${VITE_API_KEY}" > .env.production

RUN npm run build:h5
# uni-app build does not copy public/ automatically; copy static assets manually
RUN cp -r public/* dist/build/h5/ 2>/dev/null || true

# ── Stage 2: Serve ──
FROM nginx:alpine
# Copy default Nginx config (may be overridden by volume mount in production)
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist/build/h5 /usr/share/nginx/html
EXPOSE 80 443
