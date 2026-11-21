# Optional standalone deployment

The standard installation is the native custom integration. Use standalone operation
only when the proxy must continue running through Core restarts. No broker is required.
The existing [HA OS app project](https://github.com/abedegno/ocpp_charge_proxy) is another
optional deployment; relay support there requires its prepared 0.2+ release.

From the repository root:

```sh
docker build -f standalone/Dockerfile -t ocpp-proxy:local .
```

The Docker image contains the same bundled engine, copied as a neutral Python package.
It does not install Home Assistant. Set environment variables `IO_SERVER_HOSTNAME`,
`IO_CHARGEPOINT_ID`, `IO_PASSWORD` and `IO_MODE` (`emulator` or `relay`). Persist `/data`.
Expose relay port 9000 when using relay mode; keep HTTP API 8099 private.

`compose.yaml` is an example using required `OCPP_SERVER_HOSTNAME`, `OCPP_CHARGEPOINT_ID`
and `OCPP_PASSWORD` environment values. The HTTP port binds host loopback. Adjust
networking so Core can reach the API without exposing it publicly; localhost in a
separate container normally refers to that container. TLS paths require a read-only
certificate mount and `IO_RELAY_CERTFILE`/`IO_RELAY_KEYFILE`. Upstream WSS remains verified.

For emulator identity/energy settings, the engine retains `IO_CHARGER_MODEL`,
`IO_CHARGER_VENDOR`, `IO_CHARGER_SERIAL`, `IO_FIRMWARE_VERSION`, `IO_CURRENT_AMPS` and
`IO_INITIAL_ENERGY_WH`. Keep initial-energy seeding at zero after applying it once;
the CLI seed overrides the saved register when supplied at startup.

In Home Assistant choose **Connect to standalone proxy** and supply its reachable
private API URL. Do not leave a native provider connection active for the same
chargepoint. Read the [migration guide](../MIGRATION.md) before switching backends.

Unlike native mode, standalone exposes its ingress-style status/traffic page on the
HTTP API port. It is not independently authenticated. Native diagnostic downloads
remain available in the standard integration.
