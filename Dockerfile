# Rive Navigator - Cloud Run Deployment
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code and rive docs
COPY agent/ ./agent/
COPY rive-docs/ ./rive-docs/

# Expose port (Cloud Run injects PORT at runtime)
ENV PORT=8080
EXPOSE 8080

# Run the server
CMD ["sh", "-c", "python -m uvicorn agent.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
