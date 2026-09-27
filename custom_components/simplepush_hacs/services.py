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
    ATTR_EXPIRES_IN,
    ATTR_FILES,
    ATTR_INPUTS,
    ATTR_LINKS,
    ATTR_MARKDOWN,
    ATTR_PRIORITY,
    ATTR_SHARED,
    ATTR_TOPIC,
    DOMAIN,
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

INPUT_SCHEMA = cv.key_value_schemas(
    "type",
    {
        "actions": ACTIONS_INPUT_SCHEMA,
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


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Simplepush actions."""

    async def async_send_task(call: ServiceCall) -> ServiceResponse:
        """Send a task and, when asked for a response, wait for its answer."""
        entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
        if (service := hass.data[DOMAIN].get(entry_id)) is None:
            raise ServiceValidationError(
                f"The Simplepush entry {entry_id} is not set up"
            )

        response: dict[str, Any] = await service.async_send_task(
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

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_TASK,
        async_send_task,
        schema=SEND_TASK_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
