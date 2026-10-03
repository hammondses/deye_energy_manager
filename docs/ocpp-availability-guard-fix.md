# TIMXON availability guard correction

At 16:10 NZDT on October 3, the live EV automation repeatedly reached its
normal start branch but stopped at the newly added
`switch.evcharger_availability == on` condition. Trace
`8a0dc6e26c63a072f7efc99418b36549` shows an integer 32 A profile, an availability
turn-on call, then the failed availability condition. Connector status was
`Preparing`, solar permission was on, and manual override was off.

The installed OCPP 0.12.0 `switch.py` defines the charger availability switch
as on only for `Available`. Its `api.py:get_availability_status` falls back to
connector 1 status when station-level status is absent on a single-connector
charger. Consequently this switch may be off in `Preparing` even though the
connector can start. An availability service call does not make that switch a
reliable acknowledgement of operational readiness.

The earlier delayed-ownership guard change introduced this regression. The
correction removes exactly the two availability-on conditions, in the ordinary
start and one-shot SuspendedEV recovery sequences. Both locations already
re-read connector status immediately beforehand and accept only `Preparing`,
`Charging`, `SuspendedEV`, `SuspendedEVSE`, or `Finishing`. Manual override,
daytime, solar enablement and permission checks remain. No current formula,
profile, trigger or existing stop policy changed.

HA configuration hash changed from `aa52c84da1031530` to
`6a7d2aaabce4cdd6`. Configuration readback exactly matched the prepared edit,
and the automation remained enabled. The complete corrected configuration is
in `live-config-backups/2026-10-03-timxon-operational-status-guards.json`.
The preceding configuration is in
`live-config-backups/2026-10-03-timxon-after-delay-guards.json`; restoring only
that automation is the inverse, though it would reintroduce the observed bug.

No manual charger start/stop was sent for validation. The natural 16:12:30
poll, trace `d8f8390a3527c41376d2b65d7cbdbaa7`, sent integer profile 32 A,
called availability turn-on, and reached charge-control turn-on without error.
At 16:13:27, a live in-process HA template reported connector `Charging` and
charge control `on`, while availability remained `off`. This verifies the
restart blocker correction; it does not prove full modulation or forecast
handover behavior. The new shared planner and its replacement EV automation
remain undeployed.
