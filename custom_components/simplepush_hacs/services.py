"""Simplepush actions."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.notify import ATTR_MESSAGE, ATTR_TITLE, ATTR_TITLE_DEFAULT
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_AUDIO,
    ATTR_EXPIRES_IN,
    ATTR_FILES,
    ATTR_IMAGE,
    ATTR_INPUT,
    ATTR_INPUTS,
    ATTR_LINK,
    ATTR_LINKS,
    ATTR_MARKDOWN,
    ATTR_PRIORITY,
    ATTR_SHARED,
    ATTR_TIMEOUT,
    ATTR_TOPIC,
    DOMAIN,
    SERVICE_SEND_NOTIFICATION,
    SERVICE_SEND_TASK,
)

ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("action"): cv.string,
        vol.Optional("id"): vol.Any(str, int),
        vol.Optional("style"): vol.In(["primary", "destructive"]),
    }
)

ACTIONS_INPUT_SCHEMA = vol.Schema(
    {
        vol.Required("type"): "actions",
        vol.Required("actions"): vol.All(
            cv.ensure_list, vol.Length(min=1), [ACTION_SCHEMA]
        ),
        vol.Optional("description"): cv.string,
        vol.Optional("required", default=True): cv.boolean,
    }
)

TEXT_INPUT_SCHEMA = vol.Schema(
    {
        vol.Required("type"): "text",
        vol.Optional("default_value"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("required", default=True): cv.boolean,
    }
)

PHOTO_INPUT_SCHEMA = vol.Schema(
    {
        vol.Required("type"): "photo",
        vol.Optional("description"): cv.string,
        vol.Optional("required", default=True): cv.boolean,
    }
)

CHOICE_INPUT_SCHEMA = vol.Schema(
    {
        vol.Required("type"): "choice",
        vol.Required("options"): vol.All(
            cv.ensure_list, [cv.string], vol.Length(min=2)
        ),
        vol.Optional("multi", default=False): cv.boolean,
        vol.Optional("min_selections"): cv.positive_int,
        vol.Optional("max_selections"): cv.positive_int,
        vol.Optional("description"): cv.string,
        vol.Optional("required", default=True): cv.boolean,
    }
)


def _valid_scale(entry: dict[str, Any]) -> dict[str, Any]:
    """Check that a slider's scale is usable."""
    if entry["min"] >= entry["max"]:
        raise vol.Invalid("min must be below max")
    default = entry.get("default_value")
    if default is not None and not entry["min"] <= default <= entry["max"]:
        raise vol.Invalid("default_value must be between min and max")
    return entry


SLIDER_INPUT_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("type"): "slider",
            vol.Required("min"): vol.Coerce(float),
            vol.Required("max"): vol.Coerce(float),
            vol.Optional("step"): vol.All(
                vol.Coerce(float), vol.Range(min=0, min_included=False)
            ),
            vol.Optional("unit"): cv.string,
            vol.Optional("default_value"): vol.Coerce(float),
            vol.Optional("description"): cv.string,
            vol.Optional("required", default=True): cv.boolean,
        }
    ),
    _valid_scale,
)

VOICE_INPUT_SCHEMA = vol.Schema(
    {
        vol.Required("type"): "voice",
        vol.Optional("description"): cv.string,
        vol.Optional("required", default=True): cv.boolean,
    }
)

LOCATION_INPUT_SCHEMA = vol.Schema(
    {
        vol.Required("type"): "location",
        vol.Optional("description"): cv.string,
        vol.Optional("required", default=True): cv.boolean,
    }
)

FILE_INPUT_SCHEMA = vol.Schema(
    {
        vol.Required("type"): "file",
        vol.Optional("description"): cv.string,
        vol.Optional("required", default=True): cv.boolean,
    }
)

INPUT_SCHEMA = cv.key_value_schemas(
    "type",
    {
        "actions": ACTIONS_INPUT_SCHEMA,
        "text": TEXT_INPUT_SCHEMA,
        "photo": PHOTO_INPUT_SCHEMA,
        "choice": CHOICE_INPUT_SCHEMA,
        "slider": SLIDER_INPUT_SCHEMA,
        "voice": VOICE_INPUT_SCHEMA,
        "location": LOCATION_INPUT_SCHEMA,
        "file": FILE_INPUT_SCHEMA,
    },
)

INPUTS_SCHEMA = vol.All(cv.ensure_list, [INPUT_SCHEMA])

# Options of a task, shared by simplepush_hacs.send_task and notify.<name>.
TASK_OPTIONS = {
    vol.Optional(ATTR_TOPIC): cv.string,
    vol.Optional(ATTR_SHARED, default=False): cv.boolean,
    vol.Optional(ATTR_MARKDOWN, default=False): cv.boolean,
    vol.Optional(ATTR_PRIORITY): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
    vol.Optional(ATTR_EXPIRES_IN): vol.All(
        vol.Coerce(float), vol.Range(min=0, min_included=False)
    ),
    vol.Optional(ATTR_FILES): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(ATTR_LINKS): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(ATTR_INPUTS, default=[]): INPUTS_SCHEMA,
}

SEND_TASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_TITLE, default=ATTR_TITLE_DEFAULT): cv.string,
        **TASK_OPTIONS,
    }
)

NOTIFY_DATA_SCHEMA = vol.Schema(TASK_OPTIONS)

NOTIFICATION_INPUT_SCHEMA = cv.key_value_schemas(
    "type",
    {
        "text": vol.Schema({vol.Required("type"): "text"}),
        "choice": vol.Schema(
            {
                vol.Required("type"): "choice",
                vol.Required("options"): vol.All(
                    cv.ensure_list, [cv.string], vol.Length(min=1, max=3)
                ),
            }
        ),
        "actions": vol.Schema(
            {
                vol.Required("type"): "actions",
                vol.Required("actions"): vol.All(
                    cv.ensure_list, vol.Length(min=1, max=3), [ACTION_SCHEMA]
                ),
            }
        ),
    },
)

SEND_NOTIFICATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_TITLE, default=ATTR_TITLE_DEFAULT): cv.string,
        vol.Optional(ATTR_TOPIC): cv.string,
        vol.Optional(ATTR_SHARED, default=False): cv.boolean,
        vol.Optional(ATTR_PRIORITY): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
        vol.Exclusive(
            ATTR_IMAGE, "media", msg="image and audio can't be used together"
        ): cv.string,
        vol.Exclusive(
            ATTR_AUDIO, "media", msg="image and audio can't be used together"
        ): cv.string,
        vol.Exclusive(
            ATTR_LINK, "link_or_input", msg="link and input can't be used together"
        ): cv.string,
        vol.Exclusive(
            ATTR_INPUT, "link_or_input", msg="link and input can't be used together"
        ): NOTIFICATION_INPUT_SCHEMA,
        vol.Optional(ATTR_TIMEOUT): vol.All(
            vol.Coerce(float), vol.Range(min=0, min_included=False)
        ),
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Simplepush actions."""

    def entry_service(call: ServiceCall) -> Any:
        """Return the notify service of the Simplepush entry the call picked."""
        entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
        if (service := hass.data[DOMAIN].get(entry_id)) is None:
            raise ServiceValidationError(
                f"The Simplepush entry {entry_id} is not set up"
            )
        return service

    async def async_send_task(call: ServiceCall) -> ServiceResponse:
        """Send a task and, when asked for a response, wait for its answer."""
        response: dict[str, Any] = await entry_service(call).async_send_task(
            message=call.data[ATTR_MESSAGE],
            title=call.data[ATTR_TITLE],
            topic=call.data.get(ATTR_TOPIC),
            shared=call.data[ATTR_SHARED],
            markdown=call.data[ATTR_MARKDOWN],
            inputs=call.data[ATTR_INPUTS],
            files=call.data.get(ATTR_FILES),
            links=call.data.get(ATTR_LINKS),
            priority=call.data.get(ATTR_PRIORITY),
            expires_in=call.data.get(ATTR_EXPIRES_IN),
            wait=call.return_response,
        )
        return response

    async def async_send_notification(call: ServiceCall) -> ServiceResponse:
        """Send a notification and, when asked for a response, wait for its answer."""
        response: dict[str, Any] = await entry_service(call).async_send_notification(
            message=call.data[ATTR_MESSAGE],
            title=call.data[ATTR_TITLE],
            topic=call.data.get(ATTR_TOPIC),
            shared=call.data[ATTR_SHARED],
            priority=call.data.get(ATTR_PRIORITY),
            image=call.data.get(ATTR_IMAGE),
            audio=call.data.get(ATTR_AUDIO),
            link=call.data.get(ATTR_LINK),
            notification_input=call.data.get(ATTR_INPUT),
            timeout=call.data.get(ATTR_TIMEOUT),
            wait=call.return_response,
        )
        return response

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_TASK,
        async_send_task,
        schema=SEND_TASK_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_NOTIFICATION,
        async_send_notification,
        schema=SEND_NOTIFICATION_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
