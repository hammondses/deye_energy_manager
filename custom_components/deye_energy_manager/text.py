"""Text options for Deye Energy Manager advisory tuning."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextEntityDescription, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TEXT_DEFAULTS
from .entity import DeyeEnergyManagerEntity


TEXTS = (
    TextEntityDescription(
        key="solar_plan_charge_acceptance_curve",
        name="Solar plan battery charge acceptance curve",
        icon="mdi:chart-bell-curve",
        mode=TextMode.TEXT,
        native_min=0,
        native_max=255,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(SolarPlanText(coordinator, description) for description in TEXTS)


class SolarPlanText(DeyeEnergyManagerEntity, TextEntity):
    """Editable JSON configuration backed by config-entry options."""

    def __init__(self, coordinator, description: TextEntityDescription) -> None:
        super().__init__(coordinator, description.key, description.name or description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str:
        return str(
            self.coordinator.entry.options.get(
                self.entity_description.key,
                TEXT_DEFAULTS[self.entity_description.key],
            )
        )

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.async_set_option(self.entity_description.key, value)
