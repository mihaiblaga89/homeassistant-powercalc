from __future__ import annotations

import decimal
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Callable

import homeassistant.util.dt as dt_util
from homeassistant.backports.enum import StrEnum
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import (
    CONF_NAME,
    CONF_UNIQUE_ID,
    CONF_UNIT_OF_MEASUREMENT,
    ENERGY_KILO_WATT_HOUR,
    ENERGY_MEGA_WATT_HOUR,
    ENERGY_WATT_HOUR,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.template import Template
from homeassistant.helpers.typing import ConfigType
from custom_components.powercalc.common import SourceEntity
from custom_components.powercalc.const import (
    CONF_DAILY_FIXED_ENERGY,
    CONF_ENERGY_SENSOR_CATEGORY,
    CONF_ENERGY_SENSOR_PRECISION,
    CONF_ENERGY_SENSOR_UNIT_PREFIX,
    UnitPrefix,
)
from custom_components.powercalc.sensors.energy import EnergySensor
from custom_components.powercalc.migrate import async_migrate_entity_id
from custom_components.powercalc.sensors.abstract import generate_energy_sensor_entity_id, generate_energy_sensor_name
from .daily_energy import DailyEnergySensor

_LOGGER = logging.getLogger(__name__)

ENERGY_ICON = "mdi:lightning-bolt"
ENTITY_ID_FORMAT = SENSOR_DOMAIN + ".{}"


class FixedEnergyMode(StrEnum):
    DAILY = "daily"
    CYCLIC = "cyclic"


class FixedEnergySensor(RestoreEntity, SensorEntity, EnergySensor):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_should_poll = False
    _attr_icon = ENERGY_ICON

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        entity_id: str,
        sensor_config: ConfigType,
        mode_config: ConfigType,
        rounding_digits: int = 4,
    ):
        self._hass = hass
        self._attr_name = name
        self._state: Decimal = Decimal(0)
        self._attr_entity_category = sensor_config.get(CONF_ENERGY_SENSOR_CATEGORY)
        self._value: float | Template | None = None
        self._user_unit_of_measurement = mode_config.get(CONF_UNIT_OF_MEASUREMENT)
        self._update_frequency: int | None = None
        self._sensor_config = sensor_config
        self._on_time: timedelta | None = None
        self._rounding_digits = rounding_digits
        self._attr_unique_id = sensor_config.get(CONF_UNIQUE_ID)
        self.entity_id = entity_id
        self._last_updated: float = dt_util.utcnow().timestamp()
        self._last_delta_calculate: float | None = None
        self.set_native_unit_of_measurement()
        self._update_timer_removal: Callable[[], None] | None = None
        self.set_sensor_properties_from_mode_config(mode_config)

    def set_sensor_properties_from_mode_config(self, sensor_config: ConfigType):
        pass

    def set_native_unit_of_measurement(self):
        """Set the native unit of measurement"""
        unit_prefix = (
            self._sensor_config.get(CONF_ENERGY_SENSOR_UNIT_PREFIX) or UnitPrefix.KILO
        )
        if unit_prefix == UnitPrefix.KILO:
            self._attr_native_unit_of_measurement = ENERGY_KILO_WATT_HOUR
        elif unit_prefix == UnitPrefix.NONE:
            self._attr_native_unit_of_measurement = ENERGY_WATT_HOUR
        elif unit_prefix == UnitPrefix.MEGA:
            self._attr_native_unit_of_measurement = ENERGY_MEGA_WATT_HOUR

    async def async_added_to_hass(self):
        """Handle entity which will be added."""

        if state := await self.async_get_last_state():
            try:
                self._state = Decimal(state.state)
            except decimal.DecimalException:
                _LOGGER.warning(
                    f"{self.entity_id}: Cannot restore state: {state.state}"
                )
                self._state = Decimal(0)
            self._last_updated = state.last_changed.timestamp()
            self._state += self.calculate_delta()
            self.async_schedule_update_ha_state()
        else:
            self._state = Decimal(0)

        _LOGGER.debug(f"{self.entity_id}: Restoring state: {self._state}")

    def calculate_delta(self, elapsed_seconds: int = 0) -> Decimal:
        return Decimal(0)

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return round(self._state, self._rounding_digits)

    @callback
    def async_reset_energy(self) -> None:
        _LOGGER.debug(f"{self.entity_id}: Reset energy sensor")
        self._state = 0
        self._attr_last_reset = dt_util.utcnow()
        self.async_write_ha_state()
