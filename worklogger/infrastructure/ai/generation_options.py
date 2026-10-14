"""Explicit generation capabilities for an external endpoint and model."""

from __future__ import annotations

from dataclasses import dataclass

from worklogger.infrastructure.http import validate_https_url


@dataclass(frozen=True)
class ExternalGenerationOptions:
    temperature: float | None = None
    max_output_tokens: int | None = None
    token_limit_parameter: str = "max_tokens"

    def __post_init__(self):
        if self.temperature is not None and (
            type(self.temperature) not in (int, float)
            or not 0 <= self.temperature <= 2
        ):
            raise ValueError("ai_generation_options_invalid")
        if self.max_output_tokens is not None and (
            type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 131072
        ):
            raise ValueError("ai_generation_options_invalid")
        if self.token_limit_parameter not in ("max_tokens", "max_completion_tokens"):
            raise ValueError("ai_generation_options_invalid")

    def payload(self) -> dict[str, int | float]:
        values = {}
        if self.temperature is not None:
            values["temperature"] = self.temperature
        if self.max_output_tokens is not None:
            values[self.token_limit_parameter] = self.max_output_tokens
        return values


@dataclass(frozen=True)
class ExternalModelProfile:
    base_url: str
    model: str
    options: ExternalGenerationOptions = ExternalGenerationOptions()

    def __post_init__(self):
        if not isinstance(self.base_url, str) or not isinstance(self.model, str):
            raise ValueError("ai_model_profile_invalid")
        endpoint = self.base_url.strip().rstrip("/")
        model = self.model.strip()
        validate_https_url(endpoint)
        if not model or len(model) > 256 or any(ord(char) < 32 for char in model):
            raise ValueError("ai_model_profile_invalid")
        object.__setattr__(self, "base_url", endpoint)
        object.__setattr__(self, "model", model)


def external_model_profiles(value: object) -> tuple[ExternalModelProfile, ...]:
    if not isinstance(value, list) or len(value) > 128:
        raise ValueError("ai_model_profiles_invalid")
    profiles = []
    identities = set()
    allowed = {"base_url", "model", "temperature", "max_output_tokens", "token_limit_parameter"}
    for item in value:
        if not isinstance(item, dict) or set(item) - allowed:
            raise ValueError("ai_model_profiles_invalid")
        profile = ExternalModelProfile(
            base_url=item.get("base_url"), model=item.get("model"),
            options=ExternalGenerationOptions(
                temperature=item.get("temperature"), max_output_tokens=item.get("max_output_tokens"),
                token_limit_parameter=item.get("token_limit_parameter", "max_tokens"),
            ),
        )
        identity = (profile.base_url, profile.model)
        if identity in identities:
            raise ValueError("ai_model_profiles_duplicate")
        identities.add(identity)
        profiles.append(profile)
    return tuple(profiles)
