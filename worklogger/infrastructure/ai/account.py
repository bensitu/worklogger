"""Explicit account selection between local and external text processing."""

from dataclasses import replace

from worklogger.config.constants import (
    AI_ASSIST_ENABLED_SETTING_KEY, EXTERNAL_MODEL_ENABLED_SETTING_KEY,
    EXTERNAL_MODEL_BASE_URL_SETTING_KEY, EXTERNAL_MODEL_NAME_SETTING_KEY,
)
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.ai.external import OpenAICompatibleGateway
from worklogger.infrastructure.http import validate_https_url


class AccountAIGateway:
    def __init__(self, *, local, settings, user_id, key_store, transport, enabled=True, gateway_factory=OpenAICompatibleGateway):
        self._local = local
        self._settings = settings
        self._user_id = user_id
        self._key_store = key_store
        self._transport = transport
        self._enabled = enabled
        self._factory = gateway_factory
        self._external_ready = False

    def update_configuration(self, state):
        self._external_ready = bool(state.external_api_key and state.external_api_key_available)

    @property
    def available(self):
        try:
            values = self._settings.get_all(self._user_id)
            if not self._enabled or values.get(AI_ASSIST_ENABLED_SETTING_KEY, "1") != "1":
                return False
            if values.get(EXTERNAL_MODEL_ENABLED_SETTING_KEY, "0") == "1":
                return bool(self._external_ready and self._configuration(values))
            return bool(self._local and self._local.available)
        except Exception:
            return False

    def _configuration(self, values):
        endpoint = str(values.get(EXTERNAL_MODEL_BASE_URL_SETTING_KEY) or "").strip()
        model = str(values.get(EXTERNAL_MODEL_NAME_SETTING_KEY) or "").strip()
        if not model or len(model) > 256 or any(ord(char) < 32 for char in model):
            raise ValueError("ai_configuration_invalid")
        validate_https_url(endpoint)
        return endpoint, model

    def generate(self, request):
        try:
            values = self._settings.get_all(self._user_id)
            if not self._enabled or values.get(AI_ASSIST_ENABLED_SETTING_KEY, "1") != "1":
                return Result.failure(ValidationError("ai_assist_disabled", "ai_assist_disabled"))
            if values.get(EXTERNAL_MODEL_ENABLED_SETTING_KEY, "0") != "1":
                if self._local is None:
                    return Result.failure(ValidationError("local_model_not_selected", "local_model_not_selected"))
                return self._local.generate(request)
            endpoint, model = self._configuration(values)
            key = self._key_store.get_secret("ai_api_key")
            if not key.ok:
                return Result.failure(key.error)
            if not key.value:
                return Result.failure(ValidationError("ai_api_key_required", "ai_api_key_required"))
            gateway = self._factory(api_key=key.value, base_url=endpoint,
                                    opener=self._transport.opener(allow_redirects=False))
            return gateway.generate(replace(request, model=model))
        except ValueError:
            return Result.failure(ValidationError("ai_configuration_invalid", "ai_configuration_invalid"))
        except Exception:
            return Result.failure(InfrastructureError("ai_request_failed", "ai_request_failed"))
