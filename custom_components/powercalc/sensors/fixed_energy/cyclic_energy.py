from __future__ import annotations

import logging
from decimal import Decimal

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.helpers.typing import ConfigType
from .abstract import FixedEnergySensor

CYCLIC_FIXED_ENERGY_SCHEMA = vol.Schema(
    {
        vol.Required("triggers"): vol.Any(vol.Coerce(float), cv.template),
    }
)

_LOGGER = logging.getLogger(__name__)


class CyclicEnergySensor(FixedEnergySensor):
    def set_sensor_properties_from_mode_config(self, mode_config: ConfigType):
        pass

    async def async_added_to_hass(self):
        """Handle entity which will be added."""

        await super().async_added_to_hass()

        # Track state changes

    def calculate_delta(self, elapsed_seconds: int = 0) -> Decimal:
        return Decimal(0)
