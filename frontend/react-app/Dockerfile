# ===== 阶段1：build —— 编译 React 前端 =====
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# ===== 阶段2：serve —— Nginx 托管静态文件 =====
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf   # 用我们的配置（反代 /api + 关缓冲）
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80