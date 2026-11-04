"""Build the Sakura model from a SecureString fetched only during a request."""

import os

from strands.models.model import Model

from exploration_agent.runtime import SakuraSettings
from exploration_agent.secure_parameter import read_secure_parameter


def build_sakura_model_from_parameter_store() -> Model:
    key = read_secure_parameter(os.environ["SAKURA_API_KEY_PARAMETER_NAME"])
    # Do not copy the key into process-wide environment variables or persistent artifacts.
    return SakuraSettings.from_env(api_key=key).build_model()
