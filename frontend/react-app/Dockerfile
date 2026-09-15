# ===== 阶段1：build —— 编译 React 前端 =====
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# ===== 阶段2：serve —— Nginx 托管静态文件 =====
# nginx.conf 是自定义配置：反向代理 /api 到后端 + 关闭代理缓冲（保证流式输出即时到达前端）
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80