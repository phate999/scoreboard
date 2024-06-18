FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update && apt-get install -y \
      libmagic-dev \
      && rm -rf /var/lib/apt/lists/*

WORKDIR /root
COPY requirements.txt /root/requirements.txt
RUN pip3 install -r requirements.txt

RUN mkdir -p /app
WORKDIR /app

CMD ["fastapi", "dev", "--host=0.0.0.0"]
