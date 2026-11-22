"""Run native runtimes on the real HA loop with local OCPP peers."""

import asyncio
import base64
from dataclasses import replace

import pytest
from ocpp.routing import on
from ocpp.v16 import call_result
from ocpp.v16.enums import Action
from homeassistant.exceptions import HomeAssistantError

from .test_companion import hass, entry
from .engine.test_integration import MockServer
from custom_components.ocpp_charge_proxy.engine import transport as ws
from custom_components.ocpp_charge_proxy.engine.config import Config


def config(**kwargs):
    values = dict(
        server_hostname="localhost",
        chargepoint_id="CP001",
        password="test-secret",
        charger_model="Test",
        charger_vendor="Test",
        charger_serial="SAME-SERIAL",
        firmware_version="test",
        current_amps=32,
        initial_energy_wh=5000,
        log_level="info",
        use_tls=False,
        relay_host="127.0.0.1",
        relay_port=0,
    )
    values.update(kwargs)
    return Config(**values)


@pytest.mark.asyncio
async def test_native_emulator_lifecycle_and_cached_persistence(hass, tmp_path):
    from custom_components.ocpp_charge_proxy.runtime import NativeRuntime

    async def provider(socket):
        try:
            await MockServer("CP001", socket).start()
        except ws.ConnectionClosed:
            pass

    async with ws.serve(provider, "127.0.0.1", 0, subprotocols=["ocpp1.6"]) as upstream:
        cfg = config(
            server_hostname=f"127.0.0.1:{upstream.sockets[0].getsockname()[1]}"
        )
        runtime = NativeRuntime(hass, entry(), cfg)
        await runtime.async_start()
        try:
            async with asyncio.timeout(2):
                while not runtime.state.connected_to_server:
                    await asyncio.sleep(0.001)
            await runtime.async_command("/api/plug")
            assert runtime.state.plugged_in and runtime.state.state == "Preparing"
            await runtime.async_command("/api/current", {"amps": 16})
            assert runtime.state.current_amps_setting == 16
        finally:
            await runtime.async_stop()
        assert runtime.state.state == "Unavailable" and runtime.cp is None
        assert not runtime.entry._background_tasks
        await runtime.async_stop()


@pytest.mark.asyncio
async def test_rejected_boot_does_not_exit_core_or_block_setup(hass):
    from custom_components.ocpp_charge_proxy.runtime import NativeRuntime

    class Rejected(MockServer):
        @on(Action.boot_notification)
        async def reject(self, charge_point_model, charge_point_vendor, **kwargs):
            return call_result.BootNotification(
                current_time="2026-11-21T12:00:00Z", interval=1, status="Rejected"
            )

    async def provider(socket):
        try:
            await Rejected("CP001", socket).start()
        except ws.ConnectionClosed:
            pass

    async with ws.serve(provider, "127.0.0.1", 0, subprotocols=["ocpp1.6"]) as upstream:
        runtime = NativeRuntime(
            hass,
            entry(),
            config(server_hostname=f"127.0.0.1:{upstream.sockets[0].getsockname()[1]}"),
        )
        await asyncio.wait_for(runtime.async_start(), 1)
        try:
            async with asyncio.timeout(2):
                while runtime.last_error is None:
                    await asyncio.sleep(0.001)
            assert "rejected" in runtime.last_error.lower()
            assert not runtime.state.connected_to_server
        finally:
            await runtime.async_stop()


@pytest.mark.asyncio
async def test_native_relay_readonly_and_unload_closes_connections(hass):
    from custom_components.ocpp_charge_proxy.runtime import NativeRuntime

    async def provider(socket):
        async for raw in socket:
            await socket.send(raw)

    async with ws.serve(provider, "127.0.0.1", 0, subprotocols=["ocpp1.6"]) as upstream:
        runtime = NativeRuntime(
            hass,
            entry(),
            config(
                mode="relay",
                server_hostname=f"127.0.0.1:{upstream.sockets[0].getsockname()[1]}",
            ),
        )
        await runtime.async_start()
        token = base64.b64encode(b"CP001:test-secret").decode()
        car = await ws.connect(
            runtime.relay.url,
            subprotocols=["ocpp1.6"],
            extra_headers={"Authorization": "Basic " + token},
        )
        try:
            await car.send('[2,"heartbeat","Heartbeat",{}]')
            assert (
                await asyncio.wait_for(car.recv(), 2)
                == '[2,"heartbeat","Heartbeat",{}]'
            )
            with pytest.raises(HomeAssistantError, match="read-only"):
                await runtime.async_command("/api/plug")
        finally:
            await runtime.async_stop()
        await asyncio.wait_for(car.wait_closed(), 1)
        assert runtime.audit.worker.done() and not runtime.state.charger_connected


@pytest.mark.asyncio
async def test_failed_listener_setup_cleans_audit_worker(hass):
    from custom_components.ocpp_charge_proxy.runtime import NativeRuntime

    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    runtime = NativeRuntime(
        hass,
        entry(),
        config(mode="relay", relay_port=server.sockets[0].getsockname()[1]),
    )
    try:
        with pytest.raises(OSError):
            await runtime.async_start()
        assert runtime.audit.worker.done()
        assert runtime.audit.handler.stream is None
        await runtime.async_stop()
    finally:
        server.close()
        await server.wait_closed()
