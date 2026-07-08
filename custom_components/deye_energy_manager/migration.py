"""Small migration helpers shared by setup and tests."""

from __future__ import annotations

from .const import CONF_HEAT_LOADS, DEFAULT_HEAT_MODE, DEFAULT_THERMAL_ACTUATION_MODE, TEXT_DEFAULTS
from .decision import slugify

OLD_DUPLICATE_DEYE_PROGRAM_START_TIMES = ("07:00", "13:00", "17:00", "21:00", "07:00", "07:00")
PROG6_CHEAP_GRID_START_TIMES = ("07:00", "13:00", "17:00", "20:50", "20:55", "21:00")


def infer_load_slug(load: dict[str, object]) -> str:
    """Infer a stable load slug from known entity/name fields."""

    text = " ".join(str(load.get(key, "")) for key in ("name", "climate_entity", "ownership_entity")).lower()
    for slug in ("dining", "bedroom", "office", "hallway", "underfloor"):
        if slug in text:
            return slug
    return slugify(str(load.get("name") or load.get("climate_entity") or "thermal_load"))


def migrate_options(options: dict[str, object], data: dict[str, object] | None = None) -> tuple[dict[str, object], bool]:
    """Return options with v0.4.1 compatibility migrations applied."""

    migrated_options = dict(options)
    data = data or {}
    changed = False

    loads = migrated_options.get(CONF_HEAT_LOADS, data.get(CONF_HEAT_LOADS))
    if loads:
        migrated_loads = []
        for load in loads:
            migrated = dict(load)
            if not migrated.get("slug"):
                migrated["slug"] = infer_load_slug(migrated)
                changed = True
            migrated_loads.append(migrated)
        migrated_options[CONF_HEAT_LOADS] = migrated_loads

    if migrated_options.get("heat_control_enabled") and not migrated_options.get("thermal_control_enabled"):
        migrated_options["thermal_control_enabled"] = True
        changed = True

    heat_mode = str(migrated_options.get("heat_mode", DEFAULT_HEAT_MODE))
    thermal_actuation_mode = str(migrated_options.get("thermal_actuation_mode", DEFAULT_THERMAL_ACTUATION_MODE))
    if thermal_actuation_mode == "scripts":
        migrated_options["thermal_actuation_mode"] = (
            "direct" if bool(migrated_options.get("direct_climate_control_enabled", False)) else DEFAULT_THERMAL_ACTUATION_MODE
        )
        changed = True
    elif thermal_actuation_mode == DEFAULT_THERMAL_ACTUATION_MODE:
        if heat_mode == "auto_scripts":
            migrated_options["thermal_actuation_mode"] = (
                "direct" if bool(migrated_options.get("direct_climate_control_enabled", False)) else DEFAULT_THERMAL_ACTUATION_MODE
            )
            changed = True
        elif heat_mode == "auto_direct":
            migrated_options["thermal_actuation_mode"] = "direct"
            changed = True

    if heat_mode == "auto_scripts":
        migrated_options["heat_mode"] = "auto_direct" if bool(migrated_options.get("direct_climate_control_enabled", False)) else "advisory"
        changed = True

    if migrated_options.get("grid_loss_notify_service") == "notify.notify":
        migrated_options["grid_loss_notify_service"] = TEXT_DEFAULTS["grid_loss_notify_service"]
        changed = True

    if migrated_options.get("ev_fallback_hold_minutes") == 180.0:
        migrated_options["ev_fallback_hold_minutes"] = 15.0
        changed = True

    if tuple(migrated_options.get("deye_program_start_times", ())) == OLD_DUPLICATE_DEYE_PROGRAM_START_TIMES:
        migrated_options["deye_program_start_times"] = PROG6_CHEAP_GRID_START_TIMES
        changed = True

    return migrated_options, changed
