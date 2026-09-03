# 與 runtime.txt、GitHub Actions 一致。三處版本不同時，本機測過的行為
# 不保證等於部署後的行為。
FROM python:3.12-slim

ENV TZ=Asia/Taipei
ENV WAYNE_MODE=web
ENV PORT=10000
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    gcc \
    libsqlite3-dev \
    fonts-noto-cjk \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY . .

RUN mkdir -p /app/data /app/logs

EXPOSE 10000

# start-period 要蓋得住冷啟動抓 Release 庫，否則健檢會把還在下載的容器打掉。
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:10000/health')" || exit 1

CMD ["python", "main.py"]
