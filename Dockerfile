FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./pyproject.toml
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser
CMD ["python", "-m", "src.main"]
