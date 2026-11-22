# Native installation review

The user selected a single custom integration as the standard installation because
mandatory MQTT would add a prerequisite for public users. The engine and HA entities
now ship together. A separate optional standalone app/container remains available
for users who want independence from Core restarts.

## Compatibility and migration

- Configuration version2 retains version1 companion entries as external connections.
- Reconfigure updates the same entry, preserving entity unique IDs.
- External-to-native emulator handoff requires serial/register confirmation and
  applies a one-time seed, without lowering an existing native register.
- Optional-app discovery cannot rewrite native configuration.
- Native mode opens only its authenticated relay listener, not a separate HTTP API.
- Core restarts/reloads interrupt native connections; accepted offline charger
  schedules may continue. No proxy runtime can infer that charging stopped solely
  from losing its connection.

## Verification

All inherited protocol regressions remain under tests/engine. Additional tests use
actual HA2026.11.1 classes for native startup/shutdown, rejected registration, partial
listener failure, power input, external compatibility, migration, diagnostics and
serialized persistence. The isolated-install test uses only a copied component,
its declared dependencies and HA's real loader/config-flow manager.

No tests contact Octopus or a real charger. No live HA/charger settings are changed.
HA OS/Supervisor installation and real provider interoperability remain release
validation requirements. The explicit websockets legacy API is deprecated upstream,
but runs on the declared modern library; migrating that interface is a follow-up.

The previous app/companion reliability review and 0.2 changes are retained in the
original project and changelog. The native distribution has no Supervisor app
metadata, so Marketplace does not need to install an app-containing repository.

## Final independent review

Five important findings were reproduced and corrected: offline startup register
continuity, strict handoff/final writes, canceled/retried handoff export, verified
TLS context setup off-loop and joining canceled file work before replacement.
A reconnect-delay finding was treated as important for charging windows: backoff
now resets after successful registration while repeated failures still back off.
Regressions failed first, then passed with the complete suite.

The native/external handoff reads persisted values when a canceled prior flow has
already unloaded its runtime. If no verified snapshot is available it stops rather
than presenting an invented serial/register. Failed final flushes remain visible
and retryable after storage repair; a replacement is not reported as safely stopped.

Local verification: 162 tests pass against HA2026.11.1 and the pinned protocol
libraries, with 78.45% combined line/branch coverage. The standalone container
builds and imports the engine with no Home Assistant package installed.
