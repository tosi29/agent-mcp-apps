"""Fetch the existing SecureString only during a request, after the V2 snapshot."""

import os
from contextlib import closing

import boto3
from botocore.config import Config
from strands.models.model import Model

from exploration_agent.runtime import SakuraSettings


def build_sakura_model_from_parameter_store() -> Model:
    name = os.environ["SAKURA_API_KEY_PARAMETER_NAME"]
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
        raise RuntimeError("推論APIキーをParameter Storeから取得できませんでした") from None
    if parameter.get("Type") != "SecureString":
        raise ValueError("推論APIキーにはSecureStringパラメータを使用してください")
    # Do not copy the key into process-wide environment variables or persistent artifacts.
    return SakuraSettings.from_env(api_key=parameter.get("Value", "")).build_model()
