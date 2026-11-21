FROM python:3.13.12-slim-bookworm@sha256:a58daefb915e1e03ad48f3ca4df8832065412c5c35cacb9d39f4229184de12b6
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/plankton
COPY requirements/web.txt requirements/cloud.txt requirements/
RUN --mount=type=secret,id=build_ca,target=/etc/ssl/certs/ca-certificates.crt \
    python -m pip install --disable-pip-version-check --only-binary=:all: --no-cache-dir -r requirements/cloud.txt \
    && python -m pip check
COPY app/ app/
COPY migrations/ migrations/
COPY deploy/cloud.py deploy/cloud.py
RUN chmod -R a=rX app migrations deploy requirements
USER 1000:1000
ENTRYPOINT ["python", "-m", "deploy.cloud"]
CMD ["serve"]
