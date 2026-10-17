# Image for the local-only helpers: dev-auth, the gateway stand-in and the messaging bootstrap.
FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
RUN pip install fastapi==0.141.1 starlette==1.7.0 "uvicorn[standard]==0.34.2" httpx==0.28.1 "pyjwt[crypto]==2.15.1" boto3==1.35.90
RUN useradd --system --uid 10001 --create-home app
WORKDIR /local
COPY . .
USER 10001
