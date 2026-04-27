FROM python:3.12-alpine

# dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev \
    libffi-dev \
    openssl-dev

WORKDIR /app

# python packages
RUN pip install --no-cache-dir \
    flask==3.0.3 \
    'gpsoauth==2.0.0' \
    'requests==2.32.5' \
    gunicorn==22.0.0

# cert
RUN wget -O /etc/ssl/certs/cacert.pem https://curl.se/ca/cacert.pem

ENV CURL_CA_BUNDLE=/etc/ssl/certs/cacert.pem
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/cacert.pem
ENV SSL_CERT_FILE=/etc/ssl/certs/cacert.pem

COPY server.py .
COPY templates/ templates/
COPY static/ static/

# run with gunicorn for prod
# Use 1 worker to keep in-memory state (challenges, rate limits) consistent
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "60", "server:app"]

EXPOSE 8080
