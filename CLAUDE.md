# MyHOME - Home Assistant Custom Integration

## What this is

A Home Assistant custom integration for **BTicino MyHOME** home automation systems. It communicates with BTicino gateways (F455, MH200N, etc.) over the **OpenWebNet (OWN)** protocol via TCP/IP.

This project was abandoned by its original author (`anotherjulien`) and is being adopted.

## Companion library: OWNd

Located at `/Users/jack/Projects/OWNd` — a Python library that implements the OpenWebNet protocol. This integration depends on it (`OWNd==0.7.48` in manifest, but the local copy is `0.7.49`).

OWNd handles: gateway discovery (SSDP), TCP connection management, HMAC-SHA authentication, event listening, command sending, and OWN message parsing.

## Project structure

```
custom_components/myhome/
├── __init__.py          # Integration setup, service registration, entity pruning
├── config_flow.py       # UI-based configuration (SSDP discovery + manual entry)
├── gateway.py           # Gateway handler: event loop, command queue, message routing
├── myhome_device.py     # Base entity class for all MyHOME entities
├── const.py             # Constants and config keys
├── validate.py          # YAML config schema (voluptuous-based)
├── manifest.json        # HA integration metadata
├── services.yaml        # Service definitions (sync_time, send_message)
├── light.py             # Light entities (WHO=1, dimmable/non-dimmable)
├── switch.py            # Switch entities (WHO=1, outlet/switch class)
├── cover.py             # Cover entities (WHO=2, shutters/blinds)
├── climate.py           # Climate entities (WHO=4, heating/cooling zones)
├── binary_sensor.py     # Binary sensor entities (WHO=25, dry contacts/motion)
├── sensor.py            # Sensor entities (WHO=18 energy, WHO=4 temp, WHO=1 lux)
├── button.py            # Button entities (enable/disable commands)
└── translations/        # en, fr, it, nl
```

## OpenWebNet protocol basics

Messages follow the format `*WHO*WHAT*WHERE##`:
- **WHO**: device category (1=Lights, 2=Covers, 4=Climate, 5=Alarm, 18=Energy, 25=DryContacts)
- **WHAT**: action/state (0=off, 1=on, etc.)
- **WHERE**: device address (area+point: "11"=area1/point1, "#N"=group N)

Status requests: `*#WHO*WHERE##`
Dimension requests: `*#WHO*WHERE*dimension##`

## Architecture

1. Config flow discovers gateways via SSDP or manual IP entry
2. Device configuration is in a YAML file (default: `/config/myhome.yaml`)
3. Gateway handler maintains:
   - One **event session** (listens for device state changes)
   - N **command sessions** (sends commands via async queue)
4. Events are dispatched to entity `handle_event()` methods
5. Commands go through `send_buffer` (asyncio.Queue)

## Key patterns

- Entities are looked up via `hass.data[DOMAIN][mac][CONF_PLATFORMS][platform][entity_id][CONF_ENTITIES]`
- Device addresses include optional bus interface: `WHO-WHERE#4#BUS`
- The validate.py schemas transform user-friendly YAML into internal data structures (re-keying by MAC, adding WHO prefixes, etc.)

## How to run/test

This is a Home Assistant custom component — it runs inside HA. Install by copying `custom_components/myhome/` into HA's `custom_components/` directory (or via HACS).

No test suite exists in this repo.

## Dependencies

- `OWNd` (OpenWebNet protocol library)
- `aiofiles` (async file I/O for YAML loading)
- `PyYAML` (YAML parsing — comes with HA)
- `voluptuous` (config validation — comes with HA)
- Home Assistant >= 2024.3.0

## Current state / known issues

- Version mismatch: manifest requires `OWNd==0.7.48` but the local OWNd is `0.7.49`
- Typo in `__init__.py` line 65: "Configartion" → "Configuration"
- `gateway.py` line 385 has a buggy log format string (extra positional arg `self.gateway.host`)
- The `PLATFORMS` list in `__init__.py` doesn't include `"button"` but button entities are set up via the validate schema
- No automated tests
