# Transparent relay

In native relay mode, the real charger connects to a listener inside Home Assistant
Core, and the integration connects upstream to the provider using verified WSS.
It forwards text/binary message contents unchanged, records actual responses, and
never originates OCPP acknowledgements, meter values or scheduling commands.
WebSocket framing, ping/pong and TLS terminate independently on each side.

## Listener

Configure **Run in Home Assistant → Transparent relay** with the existing provider
host, chargepoint ID and password. Set a listen address and TCP port (default 9000).
The full charger endpoint is:

```text
ws://<Core-host>:9000/<chargepoint_id>
```

Use OCPP 1.6J and the original HTTP Basic username/password. Some charger setup
screens append the ID themselves; include it exactly once. Query strings, other
charger IDs, invalid credentials and non-OCPP-1.6 connections are rejected. Only
one charger is accepted at a time. Docker/container Core installations must make
the listener port reachable; the HA web/ingress URL is not the charger endpoint.

Supply both TLS certificate-chain and key paths to use WSS. Paths must be readable
by Core (or mapped into the standalone container). The charger must trust that
certificate and connect using its matching hostname. Without both paths, only WS
is used on a trusted LAN; Basic credentials otherwise travel in plaintext. Upstream
TLS verification remains enabled. Do not expose the listener broadly without TLS.

## Capture

Download integration diagnostics for the last 100 redacted records. Persistent logs
are under `/config/ocpp_charge_proxy/<entry_id>/relay/traffic.jsonl` in native mode,
or `/data/relay/traffic.jsonl` in the standalone container. Rotation is approximately
5 MiB with five backups. The queue holds 256 records; `log_dropped` and `log_error`
expose loss or storage errors. Forwarding is not blocked indefinitely by a full log queue.

Records include UTC time, session, direction, message ID/type/action, original-frame
hash and a redacted parsed copy. Common secrets and download locations are redacted;
malformed/binary records retain size/hash only. Captures still include device/session
metadata and must be reviewed before sharing.

Match CALLRESULT/CALLERROR to its command ID within a session. A forwarded message
alone does not prove the charger applied it. Inspect SetChargingProfile validity,
duration, stack/purpose, schedule periods and real acknowledgements; also inspect
ClearChargingProfile, transaction start/stop, status and meter records.

## Failure and rollback

Either socket ending closes its partner. There is no durable command buffer or
replay. Core restart, integration reload and unload disconnect native relay clients;
the charger must reconnect. A charger may keep executing an accepted offline profile
during an outage. The relay cannot guarantee that closing a connection stops charging.

Save the original full endpoint, ID and credentials before changing the charger.
Stop any other runtime using the same identity. Check both connections and actual
BootNotification/profile responses before supervised use. Rollback restores the
saved charger endpoint/settings and stops the relay. See [migration](MIGRATION.md).

Tests use local simulated providers. Real Octopus/Wallbox interoperability and
provider credential/endpoint access still need supervised verification. The optional
standalone HTTP API remains private and unauthenticated; native mode opens no such API.
