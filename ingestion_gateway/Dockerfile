FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m apex_user
USER apex_user

COPY flask_ingestion.py .
EXPOSE 5000
CMD ["gunicorn", "-w", "4", "--threads", "2", "-b", "0.0.0.0:5000", "flask_ingestion:app"]
