# ===== 后端镜像：把"能跑 uvicorn 的 Python 环境"固化成只读快照 =====

# 1. 基础镜像：Python 3.11 slim（和本地 venv 一致，依赖验证过）
FROM python:3.11-slim

# 2. 容器内工作目录：后面所有 COPY/RUN 都以这里为根
WORKDIR /app

# 3. 先拷依赖清单——只此一层，代码还没进来（刻意的顺序，见下方注释）
COPY requirements.txt .

# 4. 装依赖：pip 从清单装，所有传递依赖自动处理
RUN pip install --no-cache-dir -r requirements.txt

# 5. 最后拷代码：backend/app/ → /app/app/
#    顺序的秘密：依赖层(3-4)几乎不变，代码层(5)天天变。
#    改代码重建时，3-4 层命中缓存直接跳过，不用重装依赖。
COPY ./app/ ./app/

# 6. 声明容器监听 8000（文档作用；真正开放端口在 compose 里）
EXPOSE 8000

# 7. 健康检查：每 30s curl 探 /health（模块2 埋的伏笔，Docker 用它判断容器"活着"）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 8. 启动命令：uvicorn 必须绑 0.0.0.0——localhost 只认容器自己，外面永远访问不到
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
