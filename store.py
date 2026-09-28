import boto3

from config import CONFIG

TABLE = boto3.resource("dynamodb").Table(CONFIG.table_name)


def put(item: dict) -> None:
    TABLE.put_item(Item=item)


def delete(video_id: str) -> None:
    TABLE.delete_item(Key={"video_id": video_id})
