FROM python:3.12-slim-bookworm

WORKDIR /root
COPY requirements.txt /root/requirements.txt
RUN pip3 install -r requirements.txt

CMD ["tail", "-f", "/dev/null"]
