import json
import logging
import os
import re
from dataclasses import dataclass
from functools import cache
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

API_KEY_FIELD = "API_KEY"
TABLE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{3,255}")

logger = logging.getLogger()


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    table_name: str
    api_key_secret_id: str
    retention_days: int
    youtube_api_base_url: str
    http_timeout_seconds: int
    log_level: str


def load_config(env=os.environ) -> Config:
    def required(name):
        if not (value := env.get(name, "").strip()):
            raise ConfigError(f"{name} is required")
        return value

    def positive_int(name, default):
        try:
            value = int(env.get(name, default))
        except ValueError:
            raise ConfigError(f"{name} must be an integer") from None
        if value <= 0:
            raise ConfigError(f"{name} must be positive")
        return value

    table_name = required("TABLE_NAME")
    if not TABLE_NAME_PATTERN.fullmatch(table_name):
        raise ConfigError("TABLE_NAME is not a DynamoDB table name")

    base_url = env.get("YOUTUBE_API_BASE_URL", "https://www.googleapis.com/youtube/v3")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError("YOUTUBE_API_BASE_URL must be an https URL")

    log_level = env.get("LOG_LEVEL", "INFO").upper()
    if log_level not in logging.getLevelNamesMapping():
        raise ConfigError(f"LOG_LEVEL {log_level} is not a logging level")

    return Config(
        table_name,
        required("API_KEY_SECRET_ID"),
        positive_int("RETENTION_DAYS", "28"),
        base_url.rstrip("/"),
        positive_int("HTTP_TIMEOUT_SECONDS", "10"),
        log_level,
    )


@cache
def api_key() -> str:
    secret_id = CONFIG.api_key_secret_id
    try:
        secret = SECRETS.get_secret_value(SecretId=secret_id)
    except ClientError as e:
        raise ConfigError(f"{secret_id}: {e.response['Error']['Code']}") from None
    try:
        value = json.loads(secret.get("SecretString", ""))[API_KEY_FIELD].strip()
    except (ValueError, TypeError, KeyError, AttributeError):
        value = ""
    if not value:
        raise ConfigError(f"{secret_id} has no {API_KEY_FIELD} value")
    return value


SECRETS = boto3.client("secretsmanager")
CONFIG = load_config()
logger.setLevel(CONFIG.log_level)
for name in ("boto3", "botocore"):
    logging.getLogger(name).setLevel(max(logger.level, logging.INFO))
