"""Config flow for simplepush integration."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from simplepush import ApiError
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_TOKEN, CONF_NAME, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .client import create_client
from .const import CONF_DELETE_AFTER, CONF_TOPIC, DEFAULT_NAME, DOMAIN, SUBENTRY_TOPIC


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


def _unique_id(api_token: str) -> str:
    """Return a stable id for the API token without storing it twice."""
    return hashlib.sha256(api_token.encode()).hexdigest()[:16]


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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the settings flow of an entry."""
        return SimplePushOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""
        errors: dict[str, str] | None = None
        if user_input is not None:
            user_input = _without_empty(user_input)

            await self.async_set_unique_id(_unique_id(user_input[CONF_API_TOKEN]))
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

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Simplepush rejected the API token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API token and keep everything else of the entry.

        The personal password stays valid: replacing the token or erasing the
        account data keeps the salt it derives from. Topic passwords don't
        depend on the token.
        """
        entry = self._get_reauth_entry()
        errors: dict[str, str] | None = None
        if user_input is not None:
            api_token = user_input[CONF_API_TOKEN]
            unique_id = _unique_id(api_token)
            if any(
                other.unique_id == unique_id and other.entry_id != entry.entry_id
                for other in self._async_current_entries(include_ignore=False)
            ):
                return self.async_abort(reason="already_configured")

            if not (
                errors := await self.hass.async_add_executor_job(
                    validate_input, api_token, entry.data.get(CONF_PASSWORD)
                )
            ):
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    data_updates={CONF_API_TOKEN: api_token},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): str}),
            description_placeholders={"name": entry.title},
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


class SimplePushOptionsFlow(OptionsFlow):
    """Change how long downloaded files are kept."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the settings."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_DELETE_AFTER): NumberSelector(
                            NumberSelectorConfig(
                                min=1,
                                step=1,
                                unit_of_measurement="hours",
                                mode=NumberSelectorMode.BOX,
                            )
                        ),
                    }
                ),
                self.config_entry.options,
            ),
        )
