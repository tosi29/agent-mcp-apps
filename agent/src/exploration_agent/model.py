"""The Sakura model, configured from the environment or a lazily read SecureString."""

import os
from collections.abc import Callable

from strands.models.model import Model
from strands.models.openai import OpenAIModel

from exploration_agent.secure_parameter import read_secure_parameter


def build_sakura_model(api_key: str, model_id: str) -> Model:
    return OpenAIModel(
        client_args={
            "base_url": "https://api.ai.sakura.ad.jp/v1",
            "api_key": api_key,
            "max_retries": 0,
            "timeout": 60.0,
        },
        model_id=model_id,
        params={"max_tokens": 2048},
    )


def sakura_factory_from_env() -> Callable[[], Model]:
    """Check the local settings at startup."""
    key = os.environ.get("SAKURA_API_KEY", "").strip()
    model_id = os.environ.get("SAKURA_MODEL_ID", "").strip()
    if not key or not model_id:
        raise ValueError("SAKURA_API_KEYとSAKURA_MODEL_IDを設定してください")
    return lambda: build_sakura_model(key, model_id)


def sakura_factory_from_parameter_store() -> Callable[[], Model]:
    """Check the settings at startup. The SecureString is read only by the returned factory."""
    name = os.environ.get("SAKURA_API_KEY_PARAMETER_NAME", "").strip()
    model_id = os.environ.get("SAKURA_MODEL_ID", "").strip()
    if not name or not model_id:
        raise ValueError("SAKURA_API_KEY_PARAMETER_NAMEとSAKURA_MODEL_IDを設定してください")
    # Do not copy the key into process-wide environment variables or persistent artifacts.
    return lambda: build_sakura_model(read_secure_parameter(name), model_id)
