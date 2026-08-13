FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      fonts-dejavu-core=2.37-6 \
      libffi8=3.4.4-1 \
      libharfbuzz-subset0=6.0.0+dfsg-3 \
      libjpeg62-turbo=1:2.1.5-2 \
      libopenjp2-7=2.5.0-2+deb12u3 \
      libpango-1.0-0=1.50.12+ds-1 \
      libpangoft2-1.0-0=1.50.12+ds-1 \
      shared-mime-info=2.2-1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.12.0

WORKDIR /workspace/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --locked --no-dev
COPY apps/api/manage.py ./manage.py
COPY apps/api/src ./src

ENV PATH="/workspace/apps/api/.venv/bin:${PATH}" \
    PYTHONPATH="/workspace/apps/api/src" \
    PYTHONDONTWRITEBYTECODE="1" \
    PYTHONUNBUFFERED="1" \
    CLARIDEZ_DOCUMENT_RENDERER_ENVIRONMENT="claridez-render-weasyprint-69.0-debian12-v1"

USER 65532:65532
ENTRYPOINT ["python", "manage.py", "documents_worker", "--settings=claridez.settings.document_worker"]
