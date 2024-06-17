FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update && apt-get install \
      libmagic-dev \
      && rm -rf /var/lib/apt/lists/*

WORKDIR /root
COPY requirements.txt /root/requirements.txt
RUN pip3 install -r requirements.txt

CMD ["tail", "-f", "/dev/null"]
