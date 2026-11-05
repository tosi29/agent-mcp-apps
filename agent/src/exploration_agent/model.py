"""The Sakura model, configured from the environment or a lazily read SecureString."""

from __future__ import annotations

import os
from dataclasses import dataclass

from strands.models.model import Model
from strands.models.openai import OpenAIModel

from exploration_agent.secure_parameter import read_secure_parameter


@dataclass(frozen=True, repr=False)
class SakuraSettings:
    api_key: str
    model_id: str
    stream: bool = True

    @classmethod
    def from_env(cls, stream: bool = True, *, api_key: str | None = None) -> SakuraSettings:
        key = (os.environ.get("SAKURA_API_KEY", "") if api_key is None else api_key).strip()
        model = os.environ.get("SAKURA_MODEL_ID", "").strip()
        if not key or not model:
            raise ValueError("SAKURA_API_KEYとSAKURA_MODEL_IDを設定してください")
        return cls(key, model, stream)

    def build_model(self) -> OpenAIModel:
        return OpenAIModel(
            client_args={
                "base_url": "https://api.ai.sakura.ad.jp/v1",
                "api_key": self.api_key,
                "max_retries": 0,
                "timeout": 60.0,
            },
            model_id=self.model_id,
            stream=self.stream,
            params={"max_tokens": 2048},
        )


def build_sakura_model_from_parameter_store() -> Model:
    key = read_secure_parameter(os.environ["SAKURA_API_KEY_PARAMETER_NAME"])
    # Do not copy the key into process-wide environment variables or persistent artifacts.
    return SakuraSettings.from_env(api_key=key).build_model()
