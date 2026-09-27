"""Config flow for simplepush integration."""

from __future__ import annotations

import hashlib
from typing import Any

from simplepush import ApiError
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_TOKEN, CONF_NAME, CONF_PASSWORD
from homeassistant.core import callback

from .client import create_client
from .const import CONF_TOPIC, DEFAULT_NAME, DOMAIN, SUBENTRY_TOPIC


def validate_input(
    api_token: str, password: str | None = None, topic: str | None = None
) -> dict[str, str] | None:
    """Send a test task to your own devices, or to `topic` with its password."""
    if topic is None:
        client = create_client(api_token, password)
    else:
        client = create_client(api_token, topics={topic: password})
    try:
        client.send_task(
            topic=topic,
            title="Home Assistant",
            content="Simplepush is set up",
        )
    except ApiError as err:
        if err.status == 401:
            return {"base": "invalid_auth"}
        if err.status in (403, 404):
            return {"base": "unknown_topic"}
        return {"base": "cannot_connect"}
    except OSError:
        return {"base": "cannot_connect"}

    return None


def _without_empty(user_input: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in user_input.items() if value != ""}


class SimplePushFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for simplepush."""

    VERSION = 2

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Topics are added to an entry as subentries."""
        return {SUBENTRY_TOPIC: TopicSubentryFlowHandler}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""
        errors: dict[str, str] | None = None
        if user_input is not None:
            user_input = _without_empty(user_input)

            # A stable id for the API token without storing it twice.
            await self.async_set_unique_id(
                hashlib.sha256(user_input[CONF_API_TOKEN].encode()).hexdigest()[:16]
            )
            self._abort_if_unique_id_configured()

            self._async_abort_entries_match({CONF_NAME: user_input[CONF_NAME]})

            if not (
                errors := await self.hass.async_add_executor_job(
                    validate_input,
                    user_input[CONF_API_TOKEN],
                    user_input.get(CONF_PASSWORD),
                )
            ):
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_TOKEN): str,
                    vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    vol.Optional(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )


class TopicSubentryFlowHandler(ConfigSubentryFlow):
    """Add a topic with its password, or change the password of one."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a topic."""
        entry = self._get_entry()
        errors: dict[str, str] | None = None
        if user_input is not None:
            user_input = _without_empty(user_input)
            topic = user_input[CONF_TOPIC]
            if any(sub.unique_id == topic for sub in entry.subentries.values()):
                return self.async_abort(reason="already_configured")

            if not (
                errors := await self.hass.async_add_executor_job(
                    validate_input,
                    entry.data[CONF_API_TOKEN],
                    user_input.get(CONF_PASSWORD),
                    topic,
                )
            ):
                return self.async_create_entry(
                    title=topic, data=user_input, unique_id=topic
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOPIC): str,
                    vol.Optional(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change the password of a topic."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        topic = subentry.data[CONF_TOPIC]
        errors: dict[str, str] | None = None
        if user_input is not None:
            user_input = _without_empty(user_input)
            if not (
                errors := await self.hass.async_add_executor_job(
                    validate_input,
                    entry.data[CONF_API_TOKEN],
                    user_input.get(CONF_PASSWORD),
                    topic,
                )
            ):
                return self.async_update_reload_and_abort(
                    entry, subentry, data={CONF_TOPIC: topic, **user_input}
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Optional(CONF_PASSWORD): str}),
            description_placeholders={"topic": topic},
            errors=errors,
        )
