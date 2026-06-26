FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: serve the local REST API. Override the command for the scheduler or
# the MCP server, e.g. `command: python -m appscope.scheduler`.
EXPOSE 8000
CMD ["uvicorn", "appscope.api:app", "--host", "0.0.0.0", "--port", "8000"]
