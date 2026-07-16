FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PORT=8000
ENV AXICLASS_ROOT=/opt/AxiCLASS
ENV AXICLASS_COMMIT=ba4ede7b1d735aa6312ab5f4355d26b5e617e70c
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    gfortran \
    git \
    make \
    pkg-config \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /app/requirements.txt

# AXICLASS_BYPASS_MAKEFILE_CLASSY_TARGET_FIX7
RUN git clone "https://github.com/PoulinV/AxiCLASS.git" /opt/AxiCLASS \
    && cd /opt/AxiCLASS \
    && git checkout --detach "ba4ede7b1d735aa6312ab5f4355d26b5e617e70c" \
    && test "$(git rev-parse HEAD)" = "ba4ede7b1d735aa6312ab5f4355d26b5e617e70c" \
    && PIP_NO_BUILD_ISOLATION=1 PYTHON=python3 make -j2 class libclass.a \
    && test -x /opt/AxiCLASS/class \
    && test -f /opt/AxiCLASS/libclass.a \
    && python3 -m pip install --no-build-isolation --no-cache-dir . \
    && python3 -c "import classy; print('classy_import_after_direct_install=PASS', classy.__file__)" \
    && printf 'packaging_install_mode=direct_pip_no_build_isolation_after_class_libclass_build\n' > /opt/axiclass_packaging_patch.txt

RUN python3 -c "import hashlib,json,classy; from pathlib import Path; module_path=Path(classy.__file__).resolve(); payload={'axiclass_commit':'ba4ede7b1d735aa6312ab5f4355d26b5e617e70c','packaging_install_mode':'direct_pip_no_build_isolation_after_class_libclass_build','classy_module_path':str(module_path),'classy_module_sha256':hashlib.sha256(module_path.read_bytes()).hexdigest()}; Path('/opt/axiclass_build_identity.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\\n',encoding='utf-8'); print(payload)"

COPY app /app/app

# AXICLASS_DOCKERFILE_ALL_HEREDOC_PURGE_FIX5B
RUN python -m py_compile /app/app/main.py /app/app/physical_bao.py \
    && python3 -c "from app.physical_bao import static_identity_review; result=static_identity_review(); assert result['status']=='ok', result; print(result)"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
