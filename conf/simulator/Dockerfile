FROM hivemq/mqtt-cli:4.33.0
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash \
    && rm -rf /var/lib/apt/lists/*
COPY HiveMQ-Simulator.sh /simulator/HiveMQ-Simulator.sh
RUN chmod +x /simulator/HiveMQ-Simulator.sh
ENV H=uns_mqtt_broker P=1883
ENV MQTT_CREDENTIALS_FILE=/run/secrets/mqtt_sim_credentials
ENV MQTT_TLS_CONFIG_FILE=/run/secrets/mqtt_sim_tls
ENTRYPOINT ["/bin/bash", "/simulator/HiveMQ-Simulator.sh"]
