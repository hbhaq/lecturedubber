FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
COPY app ./app
COPY tests ./tests
RUN useradd -m studio && mkdir -p /data && chown studio:studio /data
USER studio
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
