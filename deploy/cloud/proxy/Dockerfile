FROM nginx:1.27-alpine

# wget is used by the compose healthcheck on :8080/healthz.
RUN apk add --no-cache wget

EXPOSE 80 443
