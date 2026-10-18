ARG PYTHON_CUDA_IMAGE=pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime
FROM ${PYTHON_CUDA_IMAGE}
RUN apt-get update && apt-get install -y git ffmpeg build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN ./setup.sh --gpu
ENV UGC_ML_ENV_PYTHON=/app/.gpu-venv/bin/python
EXPOSE 8091
CMD ["./remote_worker/start.sh"]
