"""One-off task that creates one database and one login per service on the shared RDS instance.

Run in AWS as an ECS task (see infra/terraform/envs/test/compute.tf) with either
  MASTER_DATABASE_URL  postgresql+psycopg://master:***@host:5432/postgres
or MASTER_DB_HOST / MASTER_DB_USER / MASTER_DB_PASSWORD (injected from the RDS-managed secret), and
  DB_BOOTSTRAP_SPEC    [{"database": "booking", "user": "booking_svc", "password": "..."}, ...]

Locally the same job is done by local/postgres/init.sql.
"""

from __future__ import annotations

import json
import logging
import os
import re

from sqlalchemy import URL, create_engine, text

log = logging.getLogger("db_bootstrap")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _ident(value: str) -> str:
    if not _IDENT.match(value):
        raise ValueError(f"unsafe identifier: {value!r}")
    return value


def bootstrap(master_url: str | URL, spec: list[dict]) -> None:
    engine = create_engine(master_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        for item in spec:
            database, user = _ident(item["database"]), _ident(item["user"])
            role_exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :u"), {"u": user}).first()
            password = item["password"].replace("'", "''")
            if role_exists:
                conn.exec_driver_sql(f"ALTER ROLE {user} WITH LOGIN PASSWORD '{password}'")
            else:
                conn.exec_driver_sql(f"CREATE ROLE {user} WITH LOGIN PASSWORD '{password}'")
            # RDS: the master user must be a member of the role to create a database it owns.
            conn.exec_driver_sql(f"GRANT {user} TO CURRENT_USER")
            db_exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": database}).first()
            if not db_exists:
                conn.exec_driver_sql(f"CREATE DATABASE {database} OWNER {user}")
            conn.exec_driver_sql(f"REVOKE ALL ON DATABASE {database} FROM PUBLIC")
            conn.exec_driver_sql(f"GRANT ALL ON DATABASE {database} TO {user}")
            log.info("database %s ready for %s", database, user)
    engine.dispose()


def master_url_from_env() -> str | URL:
    if os.environ.get("MASTER_DATABASE_URL"):
        return os.environ["MASTER_DATABASE_URL"]
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["MASTER_DB_USER"],
        password=os.environ["MASTER_DB_PASSWORD"],
        host=os.environ["MASTER_DB_HOST"],
        port=int(os.environ.get("MASTER_DB_PORT", "5432")),
        database="postgres",
        query={"sslmode": os.environ.get("MASTER_DB_SSLMODE", "require")},
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bootstrap(master_url_from_env(), json.loads(os.environ["DB_BOOTSTRAP_SPEC"]))
