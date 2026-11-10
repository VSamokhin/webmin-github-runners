FROM python:3.13-alpine
LABEL org.opencontainers.image.title="ghrunners-collector" \
      org.opencontainers.image.description="Collects GitHub Actions self-hosted runner status into a JSON file" \
      org.opencontainers.image.licenses="MIT"
COPY ghrunners_collector.py /usr/local/bin/ghrunners-collector
RUN chmod 0755 /usr/local/bin/ghrunners-collector \
 && adduser -D -H -u 10001 ghrunners \
 && mkdir -p /data && chown ghrunners /data
USER ghrunners
ENV GHR_OUTPUT=/data/status.json
VOLUME /data
ENTRYPOINT ["/usr/local/bin/ghrunners-collector"]
