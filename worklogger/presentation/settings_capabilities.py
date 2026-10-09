"""Settings service availability supplied by desktop composition."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SettingsCapabilities:
    external_generation: bool = False
    local_generation: bool = False
    proxy_routing: bool = False
    model_management: bool = True
