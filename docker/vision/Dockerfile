FROM nvidia/cuda:13.0.3-base-ubuntu24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3-pip ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN python3.12 -m venv /opt/venv
ENV NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility,video \
    HOME=/tmp PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
COPY docker/vision/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock
COPY vision/ /app/vision/
RUN pip install --no-cache-dir --no-deps -e /app/vision
WORKDIR /app/vision
USER 1000:1000
CMD ["isentinel-vision"]
