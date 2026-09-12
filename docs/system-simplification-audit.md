# Deye Energy Manager simplification audit

## Recommendation

Do not start again yet. Keep this repo as the compatibility shell, gut it in stages, and split only after the current Home Assistant entity surface is known.

A rewrite would probably recreate the same risk in a cleaner-looking package: Home Assistant automations may already depend on the advisory sensors, binary sensors, switches, buttons, and entity IDs. The safer path is:

1. Freeze actuator writes by leaving the gates off.
2. Inventory live Home Assistant automations that reference `deye_energy_manager`.
3. Reduce the repo to a small battery/inverter/EV decision core while preserving compatibility sensors as aliases for one or two releases.
4. Move house comfort tasks that are simple schedules into Home Assistant automations.
5. Only then split dedicated integrations if the remaining boundaries are stable.

## Keep

Keep the pure decision engine shape. `decision.py` is large, but it is the right boundary: it returns decisions without touching Home Assistant, and `coordinator.py` applies those decisions through gated service calls. The main `decide()` path emits a single `EnergyManagerDecision` with proposed actions and diagnostics, while `build_deye_plan()` converts the decision into inverter programme writes. See [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:1593) and [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:2543).

Keep these behaviours in this integration:

- Deye reserve/capacity and charge-source planning.
- Cheap-grid preserve/top-up policy, if it is still needed with export allowed.
- Paid-time reserve release/avoidance, because it directly affects inverter reserve.
- EV grid bypass and EV solar permission, because those interact with Deye programme power and battery targets.
- Advisory sensors that HA automations currently consume, until the automations are migrated.
- Bedroom night heating, but preferably as a small separate path or HA automation after dependency mapping. It has a clear user value and a narrow trigger.

## Quarantine

Quarantine inverter cooling first. The code currently controls external fans from a load-fed curve plus AC-temperature feedback. It calculates throughput as the max of PV, inverter AC output, and battery power, then builds a baseline fan percentage and trims it from AC temperature error. Defaults are target `43C`, emergency `48C`, max normal fan `70%`, failsafe `50%`, feedback step `5%`. See [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:42), [models.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/models.py:152), and [const.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/const.py:341).

That model conflicts with the hardware report: internal inverter fans also trigger at `50C` and stop at `40C`. That report is not verified in the repo, but it means the useful external-fan goal is not “follow a nice fan curve”; it is “avoid crossing the internal fan-on temperature, or stay manually out of the way.” The current curve starts reacting below that, has an emergency threshold below the internal trigger, and may run the external fan at many intermediate speeds that do not map cleanly to the actual hardware hysteresis. The result is complexity without a clear control objective.

The cooling write path is gated by `inverter_cooling_control_enabled`, and the repo default is off, which limits new-install damage. See [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1097) and [const.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/const.py:227). A read-only live HA snapshot reported cooling control toggles enabled, so the installed system may be actively using this path even though the default is safe. The integration also exposes many cooling entities that automations may depend on: 10 tuning numbers in [number.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/number.py:119), 12 correlation sensors in [sensor.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/sensor.py:74), plus the control switch in [switch.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/switch.py:29).

The copied ESPHome fan-controller YAML under `/tmp/deye-audit/fan-controller.yaml` looks like a simple speed fan backed by PWM plus a relay: it turns the relay on when the fan entity turns on, turns it off when the fan entity turns off, and republishes RPM after speed changes. It does not appear, from the non-secret cooling lines inspected, to contain the complex temperature curve. That points back to this integration or HA automations as the source of cooling policy.

Minimal cooling replacement:

- Keep advisory temperature and current fan percentage sensors.
- Delete the load-fed curve, trend tracking, baseline/trim sensors, and most tuning numbers after an automation inventory.
- If automatic cooling remains, use a two-threshold hysteresis around the real hardware boundary, for example external fan on below the internal fan-on point and off below the internal fan-off point. Do not invent exact thresholds in code until the actual desired external-fan temperatures are chosen from observed data.
- A simpler option is to move cooling to a Home Assistant automation: `if AC temp >= external_on then fan.set_percentage; if AC temp <= external_off then fan.turn_off`.

## Move To Home Assistant

Move these unless they are tightly coupled to inverter reserve:

- General thermal solar soaking.
- Comfort heat.
- Morning preheat.
- Underfloor schedule.
- Emergency shed buttons and unowned-load shedding, unless you still want the integration to own climate leases.

The thermal system is the broadest non-inverter controller here. It handles thermal mode, direct climate actuation, room rotation, fan modes, solar soak, comfort heat, morning preheat, overnight dining comfort, underfloor comfort, emergency shed, manual override leases, and unowned shedding. The apply path can set HVAC mode, temperature, fan mode, and ownership booleans. See [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:1869), [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:2096), and [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1415).

The repository already hints this was a migration layer: README says legacy heat controls remain as compatibility aliases during the thermal cutover. See [README.md](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/README.md:337). That makes thermal a good candidate for retirement or extraction.

Bedroom night heating is the exception. It is direct and understandable: an armed switch holds the bedroom at the overnight taper target, suppresses cheap-grid battery charging, turns off other configured thermal loads, and disarms in the morning. See [README.md](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/README.md:77), [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:630), and [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1447). Keep it for now, but do not keep the whole thermal engine just to support it.

## Preserve For Compatibility

The current entity surface is large:

- Feature switches include Deye, grid charge, EV, thermal, direct climate, cooling, paid-time, underfloor, and other policy toggles. See [switch.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/switch.py:17).
- Binary sensors expose both old `heat_*` and newer `thermal_*` concepts plus EV/grid/forecast states. See [binary_sensor.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/binary_sensor.py:24).
- Sensors expose cooling, thermal, battery plan, EV, and recent action diagnostics. See [sensor.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/sensor.py:74).
- Number controls include legacy heat thresholds, thermal thresholds, EV thresholds, underfloor thresholds, battery targets, cooling curve controls, and forecast buffers. See [number.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/number.py:23).

This is the main reason not to rewrite first. If a HA automation uses any of those entity IDs, a clean new integration would break the house even if its code is better.

## Delete Later

Ranked Ponytail audit findings:

- `delete:` Inverter cooling curve and tuning surface. Replacement: one HA hysteresis automation or a tiny two-threshold controller after dependency inventory. [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:42)
- `delete:` Legacy heat alias surface once automations move to thermal names or HA automations. Replacement: no aliases after deprecation. [README.md](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/README.md:337)
- `delete:` General direct thermal actuation if comfort/underfloor/preheat can live in HA. Replacement: HA climate automations and a few advisory battery/solar sensors. [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1415)
- `delete:` Unowned managed-load shedding unless actively used. Replacement: nothing, or a visible HA automation for known climate entities only. [decision.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/decision.py:1160)
- `yagni:` Script actuation mode appears documented as a compatibility bridge, while runtime only has direct/advisory handling in `_apply_heat()`. Replacement: advisory/direct only, unless a live install still uses scripts. [README.md](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/README.md:220), [coordinator.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/coordinator.py:1415)
- `shrink:` Split diagnostics from control. Replacement: keep a small core decision package and compatibility sensor layer during migration. [sensor.py](/home/ubuntu/.t3/worktrees/deye_energy_manager/t3code-c530c489/custom_components/deye_energy_manager/sensor.py:74)

## Suggested Module Boundary

Target end state:

- `deye_energy_manager`: inverter reserve, charge source, cheap-grid preserve/top-up, paid-time reserve release, EV programme-power bypass, EV solar permission advisory.
- `ha automations`: inverter fan hysteresis, bedroom night heating, underfloor schedule, ordinary comfort heat, manual emergency actions.
- Optional later `thermal_energy_manager`: only if solar thermal storage still needs a reusable integration after HA automations prove too limited.

Do not split by file first. Split by actuator:

- Deye writes stay here: programme capacities, programme powers, programme charge selects, grid charge switch.
- Climate writes leave here unless bedroom night heating proves worth keeping.
- Fan writes leave here unless a two-threshold cooling controller proves useful.

## Migration Plan

1. Add an HA automation/entity dependency inventory. Search live HA automations, scripts, dashboards, helpers, and Node-RED if present for `deye_energy_manager`, `solar_owns_`, `cooling_`, `thermal_`, and `heat_`.
2. Turn off `switch.deye_energy_manager_inverter_cooling_control_enabled` only after checking whether any live safety automation depends on it. Then run cooling as advisory while comparing AC temperature, internal fan events if available, and external fan state.
3. Replace cooling with a HA hysteresis automation. Keep old cooling sensors for one release; mark the curve controls deprecated.
4. Move underfloor, comfort heat, morning preheat, and unowned shedding to HA automations or delete them if unused.
5. Keep bedroom night heating until the rest is quiet. Then either move it to HA or leave it as the only climate action.
6. Remove deprecated entities in a versioned release after automations no longer reference them.

## Known Unknowns

- The `50C on / 40C off` internal fan hysteresis is user-reported hardware behavior; this repo does not verify it.
- I did not complete a live Home Assistant automation/registry inventory, so actual entity dependencies are unknown.
- I did not run tests because this audit only adds documentation and does not change runtime behavior.
