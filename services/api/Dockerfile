FROM python:3.13-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
# Copiamos solo los archivos de definición de dependencias primero (mejor cache de capas)
COPY pyproject.toml uv.lock ./
# Instala las dependencias exactas del lockfile, sin crear un venv aislado dentro
# de un venv (usamos el Python del sistema del contenedor directamente)
ENV UV_PROJECT_ENVIRONMENT=/usr/local
RUN uv sync --frozen --no-dev
# Ahora copiamos el resto del código fuente
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]