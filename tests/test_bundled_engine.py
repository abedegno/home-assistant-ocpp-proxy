"""The standard install must include its own engine, not import app source."""


def test_engine_is_bundled_with_integration():
    from custom_components.ocpp_charge_proxy.engine.config import Config
    from custom_components.ocpp_charge_proxy.engine.client import ChargePoint
    from custom_components.ocpp_charge_proxy.engine.relay import RelayServer

    assert Config.__module__.startswith("custom_components.ocpp_charge_proxy.")
    assert ChargePoint.__module__.startswith("custom_components.ocpp_charge_proxy.")
    assert RelayServer.__module__.startswith("custom_components.ocpp_charge_proxy.")
