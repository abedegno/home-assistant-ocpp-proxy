"""Native is the default for new entries; legacy entries keep their backend."""

from dataclasses import replace
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from .test_companion import hass


def make_entry(data, version=2):
    return ConfigEntry(
        version=version,
        minor_version=1,
        domain="ocpp_charge_proxy",
        title="OCPP Charge Proxy",
        data=data,
        options={},
        source="user",
        unique_id="ocpp_charge_proxy",
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
        state=ConfigEntryState.SETUP_IN_PROGRESS,
    )


@pytest.mark.asyncio
async def test_native_relay_setup_and_unload(hass):
    from custom_components import ocpp_charge_proxy as integration

    data = {
        "deployment": "native",
        "mode": "relay",
        "server_hostname": "localhost",
        "chargepoint_id": "CP001",
        "password": "private",
        "relay_host": "127.0.0.1",
        "relay_port": 0,
    }
    entry = make_entry(data)
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    assert await integration.async_setup_entry(hass, entry)
    coordinator = hass.data["ocpp_charge_proxy"][entry.entry_id]
    assert (
        coordinator.data["mode"] == "relay"
        and coordinator.data["deployment"] == "native"
    )
    runtime = coordinator.runtime
    assert await integration.async_unload_entry(hass, entry)
    assert runtime.audit.worker.done()
    assert entry.entry_id not in hass.data["ocpp_charge_proxy"]


@pytest.mark.asyncio
async def test_v1_migration_does_not_start_native_or_change_identity(hass):
    from custom_components import ocpp_charge_proxy as integration

    entry = make_entry({"api_url": "http://standalone:8099"}, version=1)
    updates = []
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = lambda *args, **kwargs: updates.append(
        kwargs
    )
    identity = entry.entry_id
    assert await integration.async_migrate_entry(hass, entry)
    assert updates[0]["data"] == {
        "api_url": "http://standalone:8099",
        "deployment": "external",
    }
    assert updates[0]["version"] == 2 and entry.entry_id == identity


@pytest.mark.asyncio
async def test_new_flow_offers_native_without_broker(hass):
    from custom_components.ocpp_charge_proxy.config_flow import (
        OCPPChargeProxyConfigFlow,
    )

    flow = OCPPChargeProxyConfigFlow()
    flow.hass = hass
    result = await flow.async_step_user()
    defaults = result["data_schema"]({})
    assert defaults["deployment"] == "native"
    assert "mqtt" not in defaults and "api_url" not in defaults


@pytest.mark.asyncio
async def test_optional_app_discovery_cannot_rewrite_native_entry(hass):
    from custom_components.ocpp_charge_proxy.config_flow import (
        OCPPChargeProxyConfigFlow,
    )

    entry = make_entry({"deployment": "native", "mode": "relay", "password": "private"})
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries.return_value = [entry]
    flow = OCPPChargeProxyConfigFlow()
    flow.hass = hass
    result = await flow.async_step_hassio(
        MagicMock(config={"host": "standalone", "port": 8099})
    )
    assert result["type"] == "abort"
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_reconfigure_external_to_native_keeps_entry_and_requires_handoff(hass):
    from types import SimpleNamespace
    from custom_components.ocpp_charge_proxy.config_flow import (
        OCPPChargeProxyConfigFlow,
    )

    entry = make_entry({"deployment": "external", "api_url": "http://old:8099"})
    hass.data["ocpp_charge_proxy"] = {
        entry.entry_id: SimpleNamespace(data={"energy_kwh": 12.345})
    }
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_known_entry.return_value = entry
    flow = OCPPChargeProxyConfigFlow()
    flow.hass = hass
    flow.handler = "ocpp_charge_proxy"
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}
    result = await flow.async_step_reconfigure({"deployment": "native"})
    assert result["step_id"] == "native"
    result = await flow.async_step_native(
        {
            "mode": "emulator",
            "server_hostname": "provider.invalid",
            "chargepoint_id": "SAME-ID",
            "password": "private",
        }
    )
    assert result["step_id"] == "emulator"
    defaults = result["data_schema"]({})
    assert defaults["initial_energy_wh"] == 12345
    result = await flow.async_step_emulator({**defaults, "charger_serial": ""})
    assert result["errors"] == {"charger_serial": "handoff_serial_required"}
    result = await flow.async_step_emulator(
        {**defaults, "charger_serial": "SAME-SERIAL"}
    )
    assert result["type"] == "abort"
    args, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["entry"] is entry
    data = kwargs["data"]
    assert data["deployment"] == "native" and "api_url" not in data
    assert (
        data["charger_serial"] == "SAME-SERIAL" and data["initial_energy_wh"] == 12345
    )
    assert data["handoff_token"]


@pytest.mark.asyncio
async def test_native_diagnostics_redacts_password_and_identity(hass):
    from types import SimpleNamespace
    from custom_components.ocpp_charge_proxy.diagnostics import (
        async_get_config_entry_diagnostics,
    )
    import json

    entry = make_entry(
        {
            "deployment": "native",
            "password": "my-secret",
            "charger_serial": "SERIAL-PRIVATE",
        }
    )
    coordinator = SimpleNamespace(
        data={"state": "Available", "server_config": {"echo": "my-secret"}},
        runtime=SimpleNamespace(
            persistence=None,
            audit=SimpleNamespace(
                recent=[{"password": "my-secret", "serial": "SERIAL-PRIVATE"}]
            ),
        ),
    )
    hass.data["ocpp_charge_proxy"] = {entry.entry_id: coordinator}
    coordinator.runtime.snapshot = lambda: coordinator.data
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert "my-secret" not in json.dumps(result) and "SERIAL-PRIVATE" not in json.dumps(
        result
    )


@pytest.mark.asyncio
async def test_native_to_external_handoff_stops_before_requesting_app_url(hass):
    from types import SimpleNamespace
    from custom_components.ocpp_charge_proxy.config_flow import (
        OCPPChargeProxyConfigFlow,
    )

    entry = make_entry(
        {"deployment": "native", "mode": "emulator", "charger_serial": "SAME"}
    )
    store = SimpleNamespace(
        load_energy_register_wh=lambda: 9999, load_serial_number=lambda: "SAME"
    )
    runtime = SimpleNamespace(persistence=store)
    coordinator = SimpleNamespace(runtime=runtime, data={"energy_kwh": 9.5})
    hass.data["ocpp_charge_proxy"] = {entry.entry_id: coordinator}
    hass.config_entries = MagicMock()
    hass.config_entries.async_get_known_entry.return_value = entry
    hass.config_entries.async_unload = AsyncMock(return_value=True)
    flow = OCPPChargeProxyConfigFlow()
    flow.hass = hass
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}
    result = await flow.async_step_reconfigure({"deployment": "external"})
    assert result["step_id"] == "stop_native"
    hass.config_entries.async_unload.assert_not_called()
    result = await flow.async_step_stop_native({"confirm_stop": True})
    hass.config_entries.async_unload.assert_awaited_once_with(entry.entry_id)
    assert result["step_id"] == "external"
    assert result["description_placeholders"]["energy_wh"] == "9999"
