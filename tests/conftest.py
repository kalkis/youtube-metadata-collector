import json
import os
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

API_KEY = "test-api-key"
API_KEY_SECRET_ID = "youtube-data-api"
TABLE_NAME = "video-metadata"
FIXTURES = Path(__file__).parent / "fixtures"

os.environ.pop("AWS_PROFILE", None)
os.environ["AWS_DEFAULT_REGION"] = "eu-west-1"

MOCK = mock_aws()
MOCK.start()

SECRETS = boto3.client("secretsmanager")
SECRETS.create_secret(Name=API_KEY_SECRET_ID, SecretString="{}")
TABLE = boto3.resource("dynamodb").create_table(
    TableName=TABLE_NAME,
    KeySchema=[{"AttributeName": "video_id", "KeyType": "HASH"}],
    AttributeDefinitions=[{"AttributeName": "video_id", "AttributeType": "S"}],
    BillingMode="PAY_PER_REQUEST",
)

os.environ |= {
    "TABLE_NAME": TABLE_NAME,
    "API_KEY_SECRET_ID": API_KEY_SECRET_ID,
    "LOG_LEVEL": "DEBUG",
}


def pytest_unconfigure(config):
    MOCK.stop()


def load_fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def set_secret_string(value):
    SECRETS.put_secret_value(SecretId=API_KEY_SECRET_ID, SecretString=value)


def set_api_key(value):
    set_secret_string(json.dumps({"API_KEY": value}))


@pytest.fixture(autouse=True)
def reset_api_key():
    import config

    set_api_key(API_KEY)
    config.api_key.cache_clear()


@pytest.fixture
def table():
    yield TABLE
    for item in TABLE.scan(ProjectionExpression="video_id")["Items"]:
        TABLE.delete_item(Key=item)
