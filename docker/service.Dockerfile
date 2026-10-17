# One Dockerfile for every microservice: build with --build-arg SERVICE=<name>
# and the repository root as the build context.
FROM python:3.12-slim AS build
ARG SERVICE
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY libs/platform_common /src/platform_common
COPY services/${SERVICE}/requirements.txt /src/requirements.txt
RUN pip install /src/platform_common -r /src/requirements.txt

FROM python:3.12-slim
ARG SERVICE
ARG VERSION=dev
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SERVICE_VERSION=${VERSION}
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY services/${SERVICE}/app ./app
COPY services/${SERVICE}/migrations ./migrations
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live',timeout=2).status==200 else 1)"
# Keep idle connections open longer than the NLB idle timeout (350 s); otherwise uvicorn's 5 s default
# closes connections that API Gateway's VPC link is about to reuse, which surfaces as fast 504s.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--timeout-keep-alive", "400"]
