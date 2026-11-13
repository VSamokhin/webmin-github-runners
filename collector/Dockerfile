FROM python:3.13-alpine
LABEL org.opencontainers.image.title="ghrunners-collector" \
      org.opencontainers.image.description="Collects GitHub Actions self-hosted runner status into a JSON file" \
      org.opencontainers.image.licenses="MIT"
COPY ghrunners_collector.py /usr/local/bin/ghrunners-collector
# The collector uses only the standard library: drop pip, setuptools and the
# ensurepip wheels, whose vendored packages are the image's only CVEs.
RUN python -m pip uninstall -y -q pip setuptools wheel \
 && rm -rf /usr/local/lib/python3*/ensurepip /usr/local/bin/pip* \
 && chmod 0755 /usr/local/bin/ghrunners-collector \
 && adduser -D -H -u 10001 ghrunners \
 && mkdir -p /data && chown ghrunners /data
USER ghrunners
ENV GHR_OUTPUT=/data/status.json
VOLUME /data
ENTRYPOINT ["/usr/local/bin/ghrunners-collector"]
