from __future__ import annotations

import decimal
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util
import voluptuous as vol
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_UNIQUE_ID,
    CONF_UNIT_OF_MEASUREMENT,
    ENERGY_KILO_WATT_HOUR,
    ENERGY_MEGA_WATT_HOUR,
    ENERGY_WATT_HOUR,
    POWER_WATT,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.template import Template
from homeassistant.helpers.typing import ConfigType

from custom_components.powercalc.common import SourceEntity
from custom_components.powercalc.const import (
    CONF_DAILY_FIXED_ENERGY,
    CONF_ENERGY_SENSOR_CATEGORY,
    CONF_ENERGY_SENSOR_PRECISION,
    CONF_ENERGY_SENSOR_UNIT_PREFIX,
    CONF_FIXED,
    CONF_ON_TIME,
    CONF_POWER,
    CONF_UPDATE_FREQUENCY,
    CONF_VALUE,
)
from custom_components.powercalc.migrate import async_migrate_entity_id
from custom_components.powercalc.sensors.abstract import generate_energy_sensor_entity_id, generate_energy_sensor_name
from custom_components.powercalc.sensors.power import VirtualPowerSensor, create_virtual_power_sensor
from .abstract import FixedEnergySensor

ENERGY_ICON = "mdi:lightning-bolt"
ENTITY_ID_FORMAT = SENSOR_DOMAIN + ".{}"

DEFAULT_DAILY_UPDATE_FREQUENCY = 1800
DAILY_FIXED_ENERGY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_VALUE): vol.Any(vol.Coerce(float), cv.template),
        vol.Optional(CONF_UNIT_OF_MEASUREMENT, default=ENERGY_KILO_WATT_HOUR): vol.In(
            [ENERGY_KILO_WATT_HOUR, POWER_WATT]
        ),
        vol.Optional(CONF_ON_TIME, default=timedelta(days=1)): cv.time_period,
        vol.Optional(
            CONF_UPDATE_FREQUENCY, default=DEFAULT_DAILY_UPDATE_FREQUENCY
        ): vol.Coerce(int),
    }
)

_LOGGER = logging.getLogger(__name__)


async def create_daily_fixed_energy_sensor(
    hass: HomeAssistant,
    sensor_config: ConfigType,
    source_entity: SourceEntity | None = None,
) -> DailyEnergySensor:
    mode_config: ConfigType = sensor_config.get(CONF_DAILY_FIXED_ENERGY)

    name = generate_energy_sensor_name(
        sensor_config, sensor_config.get(CONF_NAME), source_entity
    )
    unique_id = sensor_config.get(CONF_UNIQUE_ID) or None
    entity_id = generate_energy_sensor_entity_id(
        hass, sensor_config, unique_id=unique_id, source_entity=source_entity
    )
    if not unique_id:
        old_entity_id = async_generate_entity_id(
            ENTITY_ID_FORMAT, sensor_config.get(CONF_NAME), hass=hass
        )
        async_migrate_entity_id(
            hass, old_entity_id=old_entity_id, new_entity_id=entity_id
        )

    _LOGGER.debug(
        "Creating daily_fixed_energy energy sensor (name=%s, entity_id=%s, unique_id=%s)",
        name,
        entity_id,
        unique_id,
    )

    return DailyEnergySensor(
        hass,
        name,
        entity_id,
        sensor_config=sensor_config,
        mode_config=mode_config,
        rounding_digits=sensor_config.get(CONF_ENERGY_SENSOR_PRECISION),
    )


async def create_daily_fixed_energy_power_sensor(
    hass: HomeAssistant, sensor_config: dict, source_entity: SourceEntity
) -> VirtualPowerSensor | None:
    mode_config: dict = sensor_config.get(CONF_DAILY_FIXED_ENERGY)
    if mode_config.get(CONF_UNIT_OF_MEASUREMENT) != POWER_WATT:
        return None

    if mode_config.get(CONF_ON_TIME) != timedelta(days=1):
        return None

    power_sensor_config = sensor_config.copy()
    power_sensor_config[CONF_FIXED] = {CONF_POWER: mode_config.get(CONF_VALUE)}

    unique_id = sensor_config.get(CONF_UNIQUE_ID)
    if unique_id:
        power_sensor_config[CONF_UNIQUE_ID] = f"{unique_id}_power"

    _LOGGER.debug(
        "Creating daily_fixed_energy power sensor (base_name=%s unique_id=%s)",
        sensor_config.get(CONF_NAME),
        unique_id,
    )

    return await create_virtual_power_sensor(hass, power_sensor_config, source_entity)


class DailyEnergySensor(FixedEnergySensor):
    def set_sensor_properties_from_mode_config(self, mode_config: ConfigType):
        self._value = mode_config.get(CONF_VALUE)
        self._update_frequency = mode_config.get(CONF_UPDATE_FREQUENCY)

        if CONF_ON_TIME in mode_config:
            self._on_time = mode_config.get(CONF_ON_TIME)
            if not isinstance(self._on_time, timedelta):
                self._on_time = timedelta(seconds=self._on_time)

        self._on_time = self._on_time or timedelta(days=1)

    async def async_added_to_hass(self):
        """Handle entity which will be added."""

        await super().async_added_to_hass()

        @callback
        def refresh(now: datetime):
            """Update the energy sensor state."""
            delta = self.calculate_delta(self._update_frequency)
            if delta > 0:
                self._state = self._state + delta
                _LOGGER.debug(
                    f"{self.entity_id}: Updating daily_fixed_energy sensor: {round(self._state, 4)}"
                )
                self.async_schedule_update_ha_state()
                self._last_updated = dt_util.now().timestamp()

        self._update_timer_removal = async_track_time_interval(
            self.hass, refresh, timedelta(seconds=self._update_frequency)
        )

    def calculate_delta(self, elapsed_seconds: int = 0) -> Decimal:
        if self._last_delta_calculate is None:
            self._last_delta_calculate = self._last_updated

        elapsed_seconds = (
            self._last_delta_calculate - self._last_updated
        ) + elapsed_seconds
        self._last_delta_calculate = dt_util.utcnow().timestamp()

        value = self._value
        if isinstance(value, Template):
            value.hass = self.hass
            value = value.async_render()

        if self._user_unit_of_measurement == POWER_WATT:
            wh_per_day = value * (self._on_time.total_seconds() / 3600)
        else:
            wh_per_day = value * 1000

        # Convert Wh to the native measurement unit
        energy_per_day = wh_per_day
        if self._attr_native_unit_of_measurement == ENERGY_KILO_WATT_HOUR:
            energy_per_day = wh_per_day / 1000
        elif self._attr_native_unit_of_measurement == ENERGY_MEGA_WATT_HOUR:
            energy_per_day = wh_per_day / 1000000

        return Decimal((energy_per_day / 86400) * elapsed_seconds)
