# Forecast-loss incident and removal of old planner fallback

At 12:34:09 NZDT on 4 October, the shared plan rejected the 10:33:51 Solcast
forecast because its maximum age was 120 minutes. The battery automation
selected its retained shadow-controller fallback and changed the current limit
from 40 A to 223 A, directing nearly all solar into the battery. This was not
adaptive probing: the shared-plan path was no longer selected.

At 13:07 the existing HA maximum forecast age was changed to 300 minutes to
fit the observed four-hour update interval (next update 14:34), and shared
planning recovered. That setting change was mitigation, not the structural fix.

## Current control contract

- Shared planner is the only planning authority for the battery automation.
- A valid plan supplies intentional battery charging in addition to capture.
- An unavailable/stale plan supplies **zero intentional forecast charging**.
  The live feedback loop continues to target `min(inverter AC rating, house
  load + permitted export)`, bounded by actual PV and conversion efficiency.
  It retains damped corrections, adaptive probes and BMS/DC limits.
- Missing/invalid live telemetry stops the automation before calculations or
  default actions. It holds the existing current limit; it does not write 250 A.
- Forecast-validity and remaining-energy conditions no longer select the old
  full-current default under shared ownership.
- The handover helper off means **no writes**, not legacy-planner selection.
- Existing grid, reserve, management and export protection gates remain. Their
  intentional normal-charge behavior is distinct from forecast loss.

The shadow planner triggers and target inputs were removed from this actuator.
Old helper entities and disabled review artifacts remain for history; they have
no references in the new battery automation. Predbat remains stopped.

With an unavailable plan, completion-by-sunset cannot be guaranteed by this
live-only controller. The unavailable manager status remains visible rather
than inventing a replacement forecast strategy or declaring old data fresh.
The shared planner resumes automatically when valid data returns.

## Validation and rollback

All 368 regression tests passed, including the exact incident state (14 kW PV,
12.2 kW battery charging, 226 A gate, missing plan and 13 kW shadow request).
The new target remains export-first and requests under 40 A in that case.
HA's own renderer was tested with current data and simulated unavailable plan:
both retained the same 11.45 kW AC target, with mode changing to live_capture_only.

Automation-only deployment, source release 0.6.0b23; running integration Python
remains 0.6.0b20. No Core restart. Restore the `config` from
`live-config-backups/2026-10-04-battery-before-fallback-fix.json` through the HA
API only if deliberately accepting the known old fallback defect. The new
configuration is `live-config-backups/2026-10-04-battery-fallback-fixed.json`.
