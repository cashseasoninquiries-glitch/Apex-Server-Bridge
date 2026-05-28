# Use a slim, production-grade Python image
FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for high-speed networking
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create a non-root user for security (The 'Solo' User)
RUN useradd -m apex_user
USER apex_user

# Copy the rest of the application
COPY . .

# Expose the port your bridge uses
EXPOSE 5000

# The engine stays alive and restarts on failure
CMD ["python", "app.py"]