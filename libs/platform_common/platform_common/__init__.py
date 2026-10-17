"""Shared service template.

Every microservice in the platform is built on this package so that token checks,
logging, tracing, health checks, database access, the transactional outbox and
event consumption behave the same way everywhere.
"""

__version__ = "1.0.0"
