# Deye Energy Manager: what to keep and what to remove

Audited 2026-09-12. Recommendation: **shrink the existing integration, move bedroom heating into Home Assistant, and replace cooling as a separate task. Do not start a wholesale rewrite or create several new integrations yet.**

## Evidence and scope

The checkout initially contained v0.5.46 (`d88e1d8`), while Home Assistant reported v0.5.69. `origin/main` still points to the older version. At the user's request, v0.5.69 (`d13dfe0`, also `origin/codex/ev-soc-controls`) was merged into this audit branch. The deployed `decision.py`, `coordinator.py`, `models.py`, and `const.py` byte-match that release. This is stronger evidence than relying on the manifest alone, although it is not verification of every installed file or in-memory module.

Three GPT-5.5 audits cover [energy and EV](audit-energy.md), [thermal and bedroom heating](audit-thermal.md), and [inverter cooling](audit-cooling.md). The [live dependency inventory](audit-homeassistant.md) adds actual automation configuration, current gates, dashboards, and recent bedroom policy history.

No live configuration, control toggles, or actuator settings were changed. The merge passes all 150 repository tests. These are local regression tests, not hardware acceptance tests. Documentation does not require a new HACS version; the existing v0.5.69 tag was reused, not moved.

## What the system is now

| Job | Actual situation | Recommended destination |
| --- | --- | --- |
| Battery reserve, solar forecast, tariff/free-power windows, inverter capacities and charge modes | Active core policy; directly matches the user's need | Keep in the existing integration |
| EV bypass, charging permission, SOC/target/manual override | Active, shared with TIMXON automations/scripts and dashboard | Keep coordinated with the inverter; remove duplicate writers during a later migration |
| Bedroom night heating | User confirms it works; button and history show regular use | Move to an HA automation with an arm helper, preserving behavior |
| General solar heat soak, rotation, heat shedding, room comfort/preheat/underfloor | Large subsystem; outer thermal and heat gates currently off | Remove unwanted policy; do not recreate features merely because they exist |
| PV load-test/export-limited controls | v0.5.69 repurposes these for curtailment soak; thermal/export-limited/PV-test gates are off live | Remove if there is no remaining export-clipping use case, after reference checks |
| External inverter cooling | Active minimum-hunt controller plus fan health and latched inverter protection | Simplify separately; explicitly decide the hardware objective and preserve any retained protection |
| Diagnostics/settings | Some drive real automations; many are internal tuning surfaces | Keep consumed entities and a small set of useful reasons; prune the rest |

There is real removable residue: v0.5.69 still calculates the old comfort/rotation/underfloor matrix, then overrides those actuator selectors to false in `decision.py:2225`. It is not simply a case of every exposed switch representing an active feature.

The useful core already has a pure decision-to-plan boundary and gated inverter writes. Rewriting it means rediscovering SOC fallbacks, programme-row rules, EV interactions, write suppression, and existing HA contracts. Several dedicated integrations would add setup, entity migration, and arbitration work before removing any of that complexity.

The target is one focused energy manager plus a few explicit household automations. Separate Python modules may help internal readability later; separate installed integrations are not needed to achieve that boundary.

## Cooling: why the new observation matters

The user reports that additional internal fans start at 50 C and only stop after cooling to 40 C. Treat that as the reported hardware behavior, not a manufacturer specification independently verified by this audit.

That is a stateful physical controller: at 45 C, the internal fans can be either on or off depending on whether 50 C was crossed earlier. A controller that merely settles somewhere below 50 C cannot guarantee they become quiet again after a crossing. v0.5.69 adds minimum-speed hunting, but still does not represent this internal-fan state. More curve tuning alone does not settle the missing objective. The live target is 40 C with a 1 C deadband and a 52 C emergency threshold, not the release defaults; settling just above 40 C could still leave internal fans running. This is a plausible mismatch, not a measured diagnosis of all cooling behavior.

Choose the intended behavior before choosing thresholds: avoid starting the internal fans, deliberately cool through their reset point after they start, or accept stock-fan operation and use external fans only for extra cooling. Do not assume the same external speed can meet all three goals under every load.

There is also a separate protection path in v0.5.69: sustained hot external-fan failure can latch inverter restrictions, including max-sell/max-solar limits and a protection programme plan. Removing the entire cooling subsystem is therefore more than removing a fan curve. The cooling audit explains this coupling and the limits of RPM-derived health.

A small hysteresis controller may be enough for external fan policy. HA automation is a candidate; ESPHome-local control is another if suitable temperature input and offline behavior exist. Neither is selected as a proven replacement without a short hardware observation. Keep raw temperature/RPM/health evidence during that change; a software recommendation is not evidence that a fan actually runs.

## Bedroom heating: preserve the working feature

The user's preferred destination is a Home Assistant automation. Keep the familiar double-press button, persisted arm state, configured target, morning paid-import/recovery cutoffs, noon cutoff, manual behavior, and free-power interaction. The thermal audit records the current contract. Arming also suppresses cheap-grid battery charging: the manager must read the replacement helper, or receive an equivalent explicit input, if that energy-policy behavior is to remain unchanged.

One non-obvious behavior needs an explicit migration decision: when bedroom mode starts, the manager also turns off other configured heat loads, including unowned ones. This path can run even with general thermal control off. The user wants heat shedding removed, so the proposed bedroom automation should normally own just the bedroom; document that intentional difference rather than silently carrying room-wide shedding into the replacement.

Do not rely only on temperature/SOC threshold crossings when migrating. Re-evaluate on startup, arming, relevant state changes, and scheduled boundaries. HA documents that numeric-state triggers fire on crossings and that `for:` waits do not survive restart/reload: [automation triggers](https://www.home-assistant.io/docs/automation/trigger/). Preserve persistent intent with a helper instead of a long-running automation delay.

## Bounded transition

1. Preserve the current entity IDs consumed by the bedroom button, EV automation/scripts, and dashboards. The live inventory lists concrete references; it is not an exhaustive negative proof for all HA storage/includes.
2. Migrate bedroom night heating to a small HA automation/helper. Compare the current rules and the proposed bedroom-only behavior, then switch ownership once. Do not run both climate writers together.
3. Remove unwanted general thermal machinery and obsolete UI; remove curtailment/PV-test behavior if export clipping no longer needs it. Deal with disabled legacy HA scripts/automations as part of that cleanup; disabling the integration alone does not delete them.
4. Replace cooling policy separately, with the internal 50/40 cycle and protection behavior understood. Verify actual fan operation, missing/stale sensor behavior, restart behavior, and latch recovery.
5. Consolidate EV/inverter writes. The active daytime EV automation and callable start/stop scripts show that some complexity already lives in HA. Keep forecast/target policy in Python and make each physical control have one clear owner.
6. Reassess the remaining code. Only split further if an independent lifecycle or hardware boundary actually needs another integration.

## Workspace access

SMB access succeeds. A real read-only CIFS mount was attempted but the workspace container returned `Operation not permitted`; FUSE is also unavailable. Selected files are available in the locally ignored `homeassistant-config-snapshot/` directory. It is a dated snapshot, not a mount, and is not automatically refreshed. No share password or raw HA configuration is committed in this report.
