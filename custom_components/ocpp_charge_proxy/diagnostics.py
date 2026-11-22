"""Redacted native/external state and recent OCPP traffic for support."""

from .config import deployment
from .const import DOMAIN
from .engine.relay import redact


def _hide(value, secrets):
    if isinstance(value, dict):
        return {key: _hide(item, secrets) for key, item in redact(value).items()}
    if isinstance(value, list):
        return [_hide(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    runtime = getattr(coordinator, "runtime", None)
    secrets = [entry.data.get("password", ""), entry.data.get("charger_serial", "")]
    if runtime is not None and runtime.persistence is not None:
        secrets.append(runtime.persistence.load_serial_number())
    data = {
        "deployment": deployment(entry.data),
        "state": runtime.snapshot()
        if runtime is not None
        else (coordinator.data if coordinator else None),
    }
    if runtime is not None and runtime.audit is not None:
        data["traffic"] = list(runtime.audit.recent)
    return _hide(data, secrets)
