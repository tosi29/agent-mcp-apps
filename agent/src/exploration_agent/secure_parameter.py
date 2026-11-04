"""Read an existing SecureString on demand, after the V2 snapshot. Never cache the value."""

from contextlib import closing

import boto3
from botocore.config import Config


def read_secure_parameter(name: str) -> str:
    # Create a fresh session after restore; never snapshot resolved AWS credentials or the API key.
    session = boto3.Session(region_name="ap-northeast-1")
    try:
        with closing(
            session.client(
                "ssm",
                config=Config(retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=5),
            )
        ) as client:
            parameter = client.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    except Exception:
        raise RuntimeError("APIキーをParameter Storeから取得できませんでした") from None
    if parameter.get("Type") != "SecureString":
        raise ValueError("APIキーにはSecureStringパラメータを使用してください")
    return parameter.get("Value", "")
