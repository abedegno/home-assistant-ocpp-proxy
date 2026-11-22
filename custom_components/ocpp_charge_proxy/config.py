"""Translate UI configuration without reading process environment."""

from .engine.config import Config

DEFAULTS = dict(
    charger_model="PLP2-0-2-2",
    charger_vendor="Wall Box Chargers",
    charger_serial="",
    firmware_version="6.11.16",
    current_amps=32,
    initial_energy_wh=0,
    log_level="info",
    mode="emulator",
    relay_host="0.0.0.0",
    relay_port=9000,
    relay_certfile="",
    relay_keyfile="",
)


def deployment(data):
    return data.get("deployment", "external" if "api_url" in data else "native")


def build_config(data, options=None):
    values = {
        **DEFAULTS,
        **{
            key: value
            for key, value in data.items()
            if key in Config.__dataclass_fields__
        },
    }
    for key, value in (options or {}).items():
        if key in ("current_amps",):
            values[key] = value
    return Config(**values)
