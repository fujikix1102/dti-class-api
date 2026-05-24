FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gfortran \
    git \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
COPY requirements-classy.txt requirements-classy.txt

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# CLASS/PyCLASS is optional. If installation fails, the API still starts
# and /health reports classy_available=false.
RUN pip install --no-cache-dir -r requirements-classy.txt || true

COPY app app

EXPOSE 8000

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
