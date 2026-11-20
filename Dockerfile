FROM python:3.12-slim
WORKDIR /app
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
RUN python -m pytest -q
EXPOSE 8080
CMD ["python", "-m", "provisioning"]
