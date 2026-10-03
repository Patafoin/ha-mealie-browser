"""Config flow for Mealie Browser: URL and API token of the Mealie server."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_VERIFY_SSL
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import MealieApi, MealieAuthError, MealieError
from .const import DOMAIN, LOGGER

TITLE = "Mealie Browser"

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
        vol.Required(CONF_API_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_VERIFY_SSL, default=True): bool,
    }
)


class MealieBrowserConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of Mealie Browser."""

    VERSION = 2

    async def _async_check(self, user_input: dict[str, Any]) -> dict[str, str]:
        api = MealieApi(
            self.hass,
            user_input[CONF_HOST],
            user_input[CONF_API_TOKEN],
            user_input[CONF_VERIFY_SSL],
        )
        try:
            await api.async_validate()
        except MealieAuthError:
            return {"base": "invalid_auth"}
        except MealieError as err:
            LOGGER.debug("Cannot reach Mealie: %s", err)
            return {"base": "cannot_connect"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Mealie server."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].rstrip("/")
            errors = await self._async_check(user_input)
            if not errors:
                return self.async_create_entry(title=TITLE, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The token was refused, or the entry comes from 1.x without its own connection."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Mealie server again."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].rstrip("/")
            errors = await self._async_check(user_input)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=user_input)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA, user_input or {k: v for k, v in entry.data.items() if k != CONF_API_TOKEN}
            ),
            errors=errors,
        )
