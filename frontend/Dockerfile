# ===== 前端镜像：和 backend 同一个剧本，只换 5 处 =====

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# 前端代码在 frontend/gui/ → 容器里 /app/gui/
COPY ./gui/ ./gui/

EXPOSE 8501

# Streamlit 原生探活地址：/_stcore/health
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# 启动命令是 streamlit，不是 uvicorn
ENTRYPOINT ["streamlit", "run", "gui/main.py", "--server.address", "0.0.0.0", "--server.port", "8501"]
