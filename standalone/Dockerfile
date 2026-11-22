FROM python:3.14-alpine3.24
WORKDIR /app
COPY standalone/requirements.txt /app/requirements.txt
RUN apk add --no-cache ca-certificates && pip install --no-cache-dir -r requirements.txt
COPY custom_components/ocpp_charge_proxy/engine /app/engine
VOLUME /data
EXPOSE 8099 9000
ENTRYPOINT ["python", "-m", "engine"]
