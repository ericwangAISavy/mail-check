# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY deployment/microservices/requirements.txt /app/requirements.txt
RUN --mount=type=secret,id=proxy_ca \
    if [ -s /run/secrets/proxy_ca ]; then PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r requirements.txt; \
    else pip install --no-cache-dir -r requirements.txt; fi
COPY mailcheck/__init__.py /app/mailcheck/__init__.py
COPY mailcheck/web/__init__.py mailcheck/web/security.py /app/mailcheck/web/
COPY mailcheck/services /app/mailcheck/services
RUN chmod -R a+rX /app
USER 1000:1000
ENTRYPOINT ["python", "-m", "mailcheck.services"]

FROM runtime AS core
CMD ["core"]
FROM runtime AS mail
CMD ["mail"]
FROM runtime AS intelligence
CMD ["intelligence"]
FROM runtime AS management
ENTRYPOINT ["python", "-m", "mailcheck.services.manage"]
CMD ["verify"]

FROM rabbitmq:4.1-alpine AS broker
COPY --chmod=0444 deployment/microservices/rabbitmq.conf /etc/rabbitmq/rabbitmq.conf

FROM nginx:1.28-alpine AS edge
COPY --chmod=0444 deployment/microservices/nginx.conf /etc/nginx/nginx.conf
USER 101:101
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
