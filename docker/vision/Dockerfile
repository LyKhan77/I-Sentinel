FROM nvidia/cuda:13.0.3-base-ubuntu24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3-pip ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN python3.12 -m venv /opt/venv
ENV NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility,video \
    HOME=/tmp PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
COPY docker/vision/requirements.lock /tmp/requirements.lock
# The lock is a complete freeze: install it as is. With dependency resolution insightface (Requires: onnxruntime)
# pulls the CPU onnxruntime, which shares site-packages/onnxruntime with onnxruntime-gpu and shadows its CUDA provider.
RUN pip install --no-cache-dir --no-deps -r /tmp/requirements.lock
# onnxruntime-gpu (pinned in the lock) is a CUDA 12 build, while torch/TensorRT use the cu13 wheels from pip.
# The dev server resolves cuBLAS/cuFFT/cuRAND/cudart 12 from /usr/local/cuda-12.8; without them the ORT CUDA
# provider fails to load and the face embedder silently falls back to CPU.
RUN apt-get update && apt-get install -y --no-install-recommends \
    cuda-cudart-12-8 libcublas-12-8 libcufft-12-8 libcurand-12-8 libcudnn9-cuda-12 \
    && rm -rf /var/lib/apt/lists/*
RUN python -c "import onnxruntime as o; p = o.get_available_providers(); assert 'CUDAExecutionProvider' in p, p"
COPY vision/ /app/vision/
RUN pip install --no-cache-dir --no-deps -e /app/vision
WORKDIR /app/vision
USER 1000:1000
CMD ["isentinel-vision"]
