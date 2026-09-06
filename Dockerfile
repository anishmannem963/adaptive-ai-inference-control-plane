FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --no-create-home app
WORKDIR /app
COPY pyproject.toml README.md ./
COPY control_plane ./control_plane
RUN pip install .
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8080') + '/health/live', timeout=2)"
CMD ["sh", "-c", "exec uvicorn control_plane.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
