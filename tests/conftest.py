"""Shared test fixtures for MyHOME tests.

Mocks the homeassistant package so custom_components can be imported
without a full HA installation.
"""
import sys
import importlib
import importlib.abc
import importlib.machinery
from unittest.mock import MagicMock


# Stub base classes that HA entities inherit from
class _StubEntity:
    """Stub for homeassistant.helpers.entity.Entity"""
    pass


class _StubButtonEntity(_StubEntity):
    pass


class _StubLightEntity(_StubEntity):
    pass


class _StubSwitchEntity(_StubEntity):
    pass


class _StubCoverEntity(_StubEntity):
    pass


class _StubBinarySensorEntity(_StubEntity):
    pass


class _StubSensorEntity(_StubEntity):
    pass


class _StubClimateEntity(_StubEntity):
    pass


_CONST_VALUES = {
    "CONF_ENTITIES": "entities",
    "CONF_HOST": "host",
    "CONF_PORT": "port",
    "CONF_PASSWORD": "password",
    "CONF_NAME": "name",
    "CONF_MAC": "mac",
    "CONF_FRIENDLY_NAME": "friendly_name",
    "EntityCategory": MagicMock(),
    "SOURCE_REAUTH": "reauth",
}

_DOMAIN_MAP = {
    "homeassistant.components.light": "light",
    "homeassistant.components.switch": "switch",
    "homeassistant.components.button": "button",
    "homeassistant.components.cover": "cover",
    "homeassistant.components.binary_sensor": "binary_sensor",
    "homeassistant.components.sensor": "sensor",
    "homeassistant.components.climate": "climate",
}

class _StubRestoreEntity(_StubEntity):
    async def async_get_last_state(self):
        return None


_ENTITY_CLASSES = {
    "homeassistant.components.button": {"ButtonEntity": _StubButtonEntity},
    "homeassistant.components.light": {"LightEntity": _StubLightEntity},
    "homeassistant.components.switch": {"SwitchEntity": _StubSwitchEntity},
    "homeassistant.components.cover": {"CoverEntity": _StubCoverEntity},
    "homeassistant.components.binary_sensor": {"BinarySensorEntity": _StubBinarySensorEntity},
    "homeassistant.components.sensor": {"SensorEntity": _StubSensorEntity},
    "homeassistant.components.climate": {"ClimateEntity": _StubClimateEntity},
    "homeassistant.helpers.restore_state": {"RestoreEntity": _StubRestoreEntity},
}


def _make_ha_mock(fullname):
    """Create a MagicMock module that satisfies HA imports."""
    mock = MagicMock()

    for prefix, domain in _DOMAIN_MAP.items():
        if fullname == prefix or fullname.startswith(prefix + "."):
            mock.DOMAIN = domain
            break

    if fullname == "homeassistant.components.cover":
        mock.ATTR_POSITION = "position"
        mock.CoverDeviceClass = MagicMock()
        mock.CoverDeviceClass.SHUTTER = "shutter"

    # Set entity base classes as real classes (not MagicMock)
    if fullname in _ENTITY_CLASSES:
        for attr_name, cls in _ENTITY_CLASSES[fullname].items():
            setattr(mock, attr_name, cls)

    if fullname == "homeassistant.const":
        for k, v in _CONST_VALUES.items():
            setattr(mock, k, v)

    if fullname == "homeassistant.helpers.device_registry":
        mock.format_mac = lambda x: ":".join(
            x.replace(":", "").replace("-", "").replace(".", "").lower()[i:i+2]
            for i in range(0, 12, 2)
        )
        mock.CONNECTION_NETWORK_MAC = "mac"

    if fullname == "homeassistant.helpers.entity":
        mock.Entity = _StubEntity

    if fullname == "homeassistant.helpers.config_validation":
        mock.config_entry_only_config_schema = lambda d: None

    if fullname == "homeassistant.helpers.event":
        mock.async_call_later = MagicMock(return_value=MagicMock())

    if fullname == "homeassistant.core":
        mock.callback = lambda f: f

    return mock


class _HALoader(importlib.abc.Loader):
    def create_module(self, spec):
        return _make_ha_mock(spec.name)

    def exec_module(self, module):
        pass


_ha_loader = _HALoader()


class _HAFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "homeassistant" or fullname.startswith("homeassistant."):
            return importlib.machinery.ModuleSpec(
                fullname,
                _ha_loader,
                is_package=True,
            )
        return None


sys.meta_path.insert(0, _HAFinder())
