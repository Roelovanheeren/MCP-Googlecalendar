FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY dental-mcp-http-server.py .

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "dental-mcp-http-server.py"]