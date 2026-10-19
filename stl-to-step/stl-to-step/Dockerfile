FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglu1-mesa libxrender1 libxext6 libsm6 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
ENV HOST=0.0.0.0 PORT=8000 NO_BROWSER=1
EXPOSE 8000
CMD ["python", "dashboard.py"]
