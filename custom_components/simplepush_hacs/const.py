"""Constants for the simplepush integration."""

from typing import Final

DOMAIN: Final = "simplepush_hacs"
DEFAULT_NAME: Final = "Simplepush"
DATA_HASS_CONFIG: Final = "simplepush_hass_config"

ATTR_ACTIONS: Final = "actions"
ATTR_ATTACHMENTS: Final = "attachments"
ATTR_ENCRYPTED: Final = "encrypted"
ATTR_EVENT: Final = "event"
ATTR_ACTION_TIMEOUT: Final = "action_timeout"

EVENT_ACTION_TRIGGERED: Final = "simplepush_action_triggered_event"

CONF_DEVICE_KEY: Final = "device_key"
CONF_SALT: Final = "salt"
