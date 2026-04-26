# Use official lightweight Python image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the grocery list first to install dependencies
COPY requirements.txt .

# Install the Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application files into the container
COPY . .

# Expose the port Flask runs on
EXPOSE 5000

# Command to run the application using a production server
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]