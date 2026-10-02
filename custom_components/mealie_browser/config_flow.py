"""Config flow for Mealie Browser.

There is nothing to type: the integration borrows the connection of a core
``mealie`` config entry, picked from a list when there are several.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)

from .const import (
    CONF_BROWSER_ID,
    CONF_DASHBOARD_PATH,
    CONF_MEALIE_ENTRY_ID,
    CONF_RESEND_DELAY,
    DEFAULT_RESEND_DELAY,
    DOMAIN,
    MEALIE_DOMAIN,
)

TITLE = "Mealie Browser"


class MealieBrowserConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of Mealie Browser."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options: defaults of the open_recipe_by_voice action."""
        return MealieBrowserOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the Mealie server whose connection is reused."""
        mealie_entries = self.hass.config_entries.async_entries(MEALIE_DOMAIN)
        if not mealie_entries:
            return self.async_abort(reason="mealie_not_configured")

        if user_input is not None:
            return self.async_create_entry(title=TITLE, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MEALIE_ENTRY_ID, default=mealie_entries[0].entry_id
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=e.entry_id, label=e.title)
                                for e in mealie_entries
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import the legacy `mealie_browser:` YAML key."""
        mealie_entries = self.hass.config_entries.async_entries(MEALIE_DOMAIN)
        if not mealie_entries:
            return self.async_abort(reason="mealie_not_configured")
        return self.async_create_entry(
            title=TITLE, data={CONF_MEALIE_ENTRY_ID: mealie_entries[0].entry_id}
        )


class MealieBrowserOptionsFlow(OptionsFlow):
    """Default target of the open_recipe_by_voice action."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(CONF_BROWSER_ID): TextSelector(),
                vol.Optional(CONF_DASHBOARD_PATH): TextSelector(),
                vol.Optional(
                    CONF_RESEND_DELAY, default=DEFAULT_RESEND_DELAY
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=60,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, self.config_entry.options
            ),
        )
