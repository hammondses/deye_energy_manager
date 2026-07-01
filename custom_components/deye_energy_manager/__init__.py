"""Home Assistant integration for Deye Energy Manager."""

from __future__ import annotations

import logging

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform
    from homeassistant.core import HomeAssistant

    from .coordinator import DeyeEnergyManagerCoordinator
except ModuleNotFoundError as err:
    if err.name != "homeassistant":
        raise
    ConfigEntry = HomeAssistant = object  # type: ignore[misc,assignment]
    Platform = None  # type: ignore[assignment]
    DeyeEnergyManagerCoordinator = None  # type: ignore[assignment]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Deye Energy Manager from a config entry."""

    if DeyeEnergyManagerCoordinator is None or Platform is None:
        return False
    coordinator = DeyeEnergyManagerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, [Platform(platform) for platform in PLATFORMS])
    entry.async_on_unload(entry.add_update_listener(async_update_entry))
    return True


async def async_update_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options change."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, [Platform(platform) for platform in PLATFORMS])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
