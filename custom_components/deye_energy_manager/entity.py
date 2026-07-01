"""Base entities for Deye Energy Manager."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeyeEnergyManagerCoordinator


class DeyeEnergyManagerEntity(CoordinatorEntity[DeyeEnergyManagerCoordinator]):
    """Base coordinator entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DeyeEnergyManagerCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "Deye Energy Manager",
            "manufacturer": "Local policy integration",
        }

