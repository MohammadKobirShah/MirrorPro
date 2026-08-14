FROM python:3.11-slim

RUN apt-get update && apt-get install -y aria2 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/downloads

EXPOSE 8000
CMD ["python", "server.py"]
