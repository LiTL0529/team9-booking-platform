"""Run the whole platform natively, without Docker.

Useful when Docker is not available. Uses an embedded PostgreSQL (pgserver), moto for
SNS/SQS, a local redis-server if one is on PATH, and runs every service with uvicorn.

  python scripts/dev_native.py up        # start everything (Ctrl+C stops it)
  python scripts/dev_native.py up --scale booking=3 --scale availability=2

Ports: gateway 8080, dev-auth 8009, services 8110/8120/8130/8140/8150 (+1 per extra replica),
moto 5000, postgres 55432, redis 56379.
Logs go to .local/logs/<process>.log
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE = REPO / ".local"
LOGS = STATE / "logs"
PY = sys.executable
PG_PORT, REDIS_PORT, MOTO_PORT, AUTH_PORT, GATEWAY_PORT = 55432, 56379, 5000, 8009, 8080
ISSUER = f"http://127.0.0.1:{AUTH_PORT}"
MOTO = f"http://127.0.0.1:{MOTO_PORT}"
ACCOUNT = "123456789012"
REGION = "ap-southeast-1"

SERVICES = {
    "merchant": {
        "PUBLISH_TOPIC_ARN": f"arn:aws:sns:{REGION}:{ACCOUNT}:merchant-events",
        "IDENTITY_PROVIDER": "dev",
        "DEV_AUTH_URL": ISSUER,
        "DEV_AUTH_ADMIN_SECRET": "local-admin-secret",
    },
    "catalogue": {"PUBLISH_TOPIC_ARN": f"arn:aws:sns:{REGION}:{ACCOUNT}:catalogue-events"},
    "availability": {
        "CONSUME_QUEUE_URL": f"{MOTO}/{ACCOUNT}/availability-events",
        "CONSUMER_CONCURRENCY": "2",
        "REDIS_URL": f"redis://127.0.0.1:{REDIS_PORT}/0",
    },
    "booking": {
        "PUBLISH_TOPIC_ARN": f"arn:aws:sns:{REGION}:{ACCOUNT}:booking-events",
        "CONSUME_QUEUE_URL": f"{MOTO}/{ACCOUNT}/booking-slot-events",
    },
    "notification": {"CONSUME_QUEUE_URL": f"{MOTO}/{ACCOUNT}/notification-events"},
}
ROUTE_PREFIXES = {
    "merchant": ["/v1/merchants"],
    "catalogue": ["/v1/resources", "/v1/slots"],
    "availability": ["/v1/availability"],
    "booking": ["/v1/bookings"],
    "notification": ["/v1/notifications"],
}
PASSWORDS = {name: f"{name}_local" for name in SERVICES}

processes: list[tuple[str, subprocess.Popen]] = []


def base_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        AWS_ACCESS_KEY_ID="local",
        AWS_SECRET_ACCESS_KEY="local",
        AWS_REGION=REGION,
        AWS_DEFAULT_REGION=REGION,
        CONSUMER_WAIT_SECONDS="1",
        PYTHONUNBUFFERED="1",
    )
    return env


def spawn(name: str, args: list[str], env: dict[str, str] | None = None, cwd: Path = REPO) -> subprocess.Popen:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = open(LOGS / f"{name}.log", "ab")
    proc = subprocess.Popen(args, cwd=cwd, env=env or base_env(), stdout=log, stderr=subprocess.STDOUT)
    processes.append((name, proc))
    print(f"  started {name:<16} pid={proc.pid}")
    return proc


def wait_http(url: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise SystemExit(f"timed out waiting for {url}")


def pg_bin() -> Path:
    import pgserver

    return Path(pgserver.__file__).parent / "pginstall" / "bin"


def start_postgres() -> None:
    data = STATE / "pgdata"
    bindir = pg_bin()
    exe = ".exe" if os.name == "nt" else ""
    if not (data / "PG_VERSION").exists():
        data.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(bindir / f"initdb{exe}"), "-D", str(data), "-U", "postgres", "-A", "trust", "-E", "UTF8",
                        "--locale=C"],
                       check=True, stdout=subprocess.DEVNULL)
    spawn("postgres", [str(bindir / f"postgres{exe}"), "-D", str(data), "-p", str(PG_PORT),
                       "-c", "max_connections=300", "-c", "listen_addresses=localhost"])
    from sqlalchemy import create_engine, text

    engine = create_engine(f"postgresql+psycopg://postgres@127.0.0.1:{PG_PORT}/postgres", isolation_level="AUTOCOMMIT")
    for _ in range(60):
        try:
            with engine.connect() as conn:
                for name, password in PASSWORDS.items():
                    role = f"{name}_svc"
                    if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:r"), {"r": role}).first():
                        conn.exec_driver_sql(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'")
                    if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname=:d"), {"d": name}).first():
                        conn.exec_driver_sql(f"CREATE DATABASE {name} OWNER {role}")
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    else:
        raise SystemExit("postgres did not start; see .local/logs/postgres.log")
    engine.dispose()


def up(scale: dict[str, int]) -> None:
    print("starting platform natively ...")
    start_postgres()
    redis = shutil.which("redis-server")
    if redis:
        spawn("redis", [redis, "--port", str(REDIS_PORT), "--save", "", "--appendonly", "no"])
    else:
        print("  redis-server not found: availability runs without its cache")
        SERVICES["availability"].pop("REDIS_URL")
    spawn("moto", [PY, "-m", "moto.server", "-p", str(MOTO_PORT)])
    wait_http(f"{MOTO}/moto-api/")
    env = base_env() | {"AWS_ENDPOINT_URL": MOTO}
    subprocess.run([PY, "local/messaging/bootstrap.py"], cwd=REPO, env=env, check=True)

    auth_env = base_env() | {
        "DEV_AUTH_ISSUER": ISSUER,
        "DEV_AUTH_ADMIN_SECRET": "local-admin-secret",
        "DEV_AUTH_STATE_FILE": str(STATE / "dev-auth-users.json"),
    }
    spawn("dev-auth", [PY, "-m", "uvicorn", "app:app", "--port", str(AUTH_PORT)], auth_env, REPO / "local" / "dev-auth")
    wait_http(f"{ISSUER}/health/live")

    routes = []
    for index, (name, extra) in enumerate(SERVICES.items()):
        port = 8110 + index * 10  # merchant 8110, catalogue 8120, availability 8130, booking 8140, ...
        for replica in range(scale.get(name, 1)):
            env = base_env() | extra | {
                "SERVICE_NAME": f"{name}-service",
                "DATABASE_URL": f"postgresql+psycopg://{name}_svc:{PASSWORDS[name]}@127.0.0.1:{PG_PORT}/{name}",
                "AWS_ENDPOINT_URL": MOTO,
                "JWT_ISSUER": ISSUER,
                "JWKS_URL": f"{ISSUER}/.well-known/jwks.json",
                "CATALOGUE_URL": "http://127.0.0.1:8120",
            }
            spawn(f"{name}-{replica + 1}", [PY, "-m", "uvicorn", "app.main:create_app", "--factory",
                                             "--port", str(port), "--no-access-log"], env, REPO / "services" / name)
            if replica == 0:
                wait_http(f"http://127.0.0.1:{port}/health/ready")
                routes += [[prefix, f"http://127.0.0.1:{port}"] for prefix in ROUTE_PREFIXES[name]]
            port += 1
    routes.append(["/auth", ISSUER])
    gateway_env = base_env() | {
        "GATEWAY_ROUTES": json.dumps(routes),
        "GATEWAY_JWKS_URL": f"{ISSUER}/.well-known/jwks.json",
        "GATEWAY_JWT_ISSUER": ISSUER,
    }
    spawn("gateway", [PY, "-m", "uvicorn", "app:app", "--port", str(GATEWAY_PORT), "--no-access-log"],
          gateway_env, REPO / "local" / "gateway")
    wait_http(f"http://127.0.0.1:{GATEWAY_PORT}/gateway/health")
    print(f"\nplatform is up: gateway http://127.0.0.1:{GATEWAY_PORT}  (logs in {LOGS})")
    print("note: with the native runner the gateway sends each service's traffic to its first replica;")
    print("      extra replicas still consume events. Use docker compose --scale for HTTP load balancing.")


def shutdown(*_args) -> None:
    print("\nstopping ...")
    for _name, proc in reversed(processes):
        if proc.poll() is None:
            proc.terminate()
    for _name, proc in processes:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["up"])
    parser.add_argument("--scale", action="append", default=[], help="service=replicas")
    args = parser.parse_args()
    scale = {k: int(v) for k, v in (item.split("=") for item in args.scale)}
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        up(scale)
        reported: set[str] = set()
        while True:
            # A stopped service is reported but does not stop the others (failure demos rely on this).
            for name, proc in processes:
                if proc.poll() is not None and name not in reported:
                    reported.add(name)
                    print(f"process {name} exited with {proc.returncode}; see .local/logs/{name}.log")
            time.sleep(2)
    except SystemExit:
        raise
    except BaseException:
        shutdown()


if __name__ == "__main__":
    main()
