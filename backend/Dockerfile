FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements-prod.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && addgroup --system app && adduser --system --ingroup app app
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
USER app
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
