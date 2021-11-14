FROM python:3.9-slim-buster
ENV PYTHONDONTWRITEBYTECODE=true PYTHONUNBUFFERED=true

WORKDIR /usr/src/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

USER 1000
COPY prometheus-ecs-sd.py .
ENTRYPOINT [ "./prometheus-ecs-sd.py" ]