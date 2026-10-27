FROM python:3.11-slim

WORKDIR /app

# Install build and runtime dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev \
    libfreetype6-dev \
    git \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements*.txt ./

# Install Python dependencies. CPU-only torch wheels: the default Linux
# wheels pull several GB of CUDA libraries the API never uses.
RUN pip install --upgrade pip setuptools wheel && \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# Bake the NLI model into the image so a cold start (scale from zero) does
# not download ~1.6 GB from the Hugging Face hub. HF_HOME sits outside /app
# so docker-compose's source mount does not hide it.
ENV HF_HOME=/opt/hf
RUN python -c "from transformers import pipeline; pipeline('text-classification', model='facebook/bart-large-mnli')"

# Copy application code
COPY . /app

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose API port
EXPOSE 8000

# Default command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
