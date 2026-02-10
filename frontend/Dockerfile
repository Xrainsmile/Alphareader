# ── Stage 1: Build ──
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json ./
RUN npm install --registry=https://registry.npmmirror.com
COPY . .
RUN npm run build:h5

# ── Stage 2: Serve ──
FROM nginx:alpine
# Copy default Nginx config (may be overridden by volume mount in production)
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist/build/h5 /usr/share/nginx/html
EXPOSE 80 443
