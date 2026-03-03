FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    ninja-build \
    clang \
    pkg-config \
    libboost-dev \
    libcrypto++-dev \
    pybind11-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY apps /app/apps
COPY core /app/core
COPY native /app/native
COPY third_party /app/third_party

RUN pip install --upgrade pip && pip install .

RUN cmake -S /app/native/wfs_core -B /app/native/wfs_core/build -G Ninja \
    && cmake --build /app/native/wfs_core/build \
    && find /app/native/wfs_core/build -name "wfs_core_native*.so" -exec cp {} /usr/local/lib/python3.12/site-packages/ \; \
    || echo "native module build skipped"

EXPOSE 8080

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8080"]

