FROM python:3.11-slim AS build-env
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

FROM gcr.io/distroless/python3-debian12:nonroot
ENV PYTHONDONTWRITEBYTECODE=true PYTHONUNBUFFERED=true PYTHONPATH=/usr/local/lib/python3.11/site-packages
COPY --from=build-env /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY prometheus-ecs-sd.py /app/
ENTRYPOINT ["/app/prometheus-ecs-sd.py"]
