"""Mealie Browser: browse Mealie recipes from a Home Assistant dashboard.

- An authenticated proxy (``/api/mealie_browser/...``) lets the bundled card
  read recipes and images without ever exposing the Mealie token.
- The ``open_recipe_by_voice`` action matches a spoken phrase to a recipe and
  shows it on the card, optionally steering a browser_mod browser (e.g. a
  kitchen tablet) to the recipes view first.

The Mealie connection itself is the one of the core ``mealie`` integration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ConfigEntryError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration
from homeassistant.util.hass_dict import HassKey

from .api import MealieApi, MealieError
from .const import (
    ATTR_TEXT,
    CARD_PATH,
    CARD_URL,
    CONF_BROWSER_ID,
    CONF_DASHBOARD_PATH,
    CONF_MEALIE_ENTRY_ID,
    CONF_RESEND_DELAY,
    DEFAULT_RESEND_DELAY,
    DOMAIN,
    LOGGER,
    MEALIE_DOMAIN,
    SERVICE_OPEN_RECIPE_BY_VOICE,
)
from .lovelace import async_register_card_resource, async_remove_card_resource
from .matching import find_recipe
from .targets import TargetDispatcher, async_register_websocket
from .views import VIEWS

# `mealie_browser:` in configuration.yaml (no options) is still accepted and
# imported into a config entry.
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

DISPATCHER: HassKey[TargetDispatcher] = HassKey(DOMAIN)

OPEN_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TEXT): cv.string,
        vol.Optional(CONF_BROWSER_ID): cv.string,
        vol.Optional(CONF_DASHBOARD_PATH): cv.string,
    }
)


@dataclass
class MealieBrowserData:
    """Runtime data of the config entry."""

    api: MealieApi


type MealieBrowserConfigEntry = ConfigEntry[MealieBrowserData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register what lives for the whole HA run: views, websocket, action."""
    dispatcher = hass.data[DISPATCHER] = TargetDispatcher()

    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)]
    )
    for view in VIEWS:
        hass.http.register_view(view())
    async_register_websocket(hass, dispatcher)

    async def open_recipe_by_voice(call: ServiceCall) -> ServiceResponse:
        return await _async_open_recipe_by_voice(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_OPEN_RECIPE_BY_VOICE,
        open_recipe_by_voice,
        schema=OPEN_RECIPE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    if DOMAIN in config:
        ir.async_create_issue(
            hass,
            DOMAIN,
            "deprecated_yaml",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="deprecated_yaml",
        )
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data={}
            )
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "deprecated_yaml")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MealieBrowserConfigEntry) -> bool:
    """Set up Mealie Browser from a config entry."""
    mealie_entry = hass.config_entries.async_get_entry(entry.data[CONF_MEALIE_ENTRY_ID])
    if mealie_entry is None or mealie_entry.domain != MEALIE_DOMAIN:
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="mealie_entry_missing"
        )
    entry.runtime_data = MealieBrowserData(api=MealieApi(hass, mealie_entry))

    integration = await async_get_integration(hass, DOMAIN)
    await async_register_card_resource(hass, f"{CARD_URL}?v={integration.version}")

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MealieBrowserConfigEntry) -> bool:
    """Unload a config entry (views and action stay registered, and answer 503)."""
    return True


async def async_remove_entry(hass: HomeAssistant, entry: MealieBrowserConfigEntry) -> None:
    """Drop the dashboard resource when the integration is removed."""
    await async_remove_card_resource(hass)


async def _async_options_updated(hass: HomeAssistant, entry: MealieBrowserConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _loaded_entry(hass: HomeAssistant) -> MealieBrowserConfigEntry:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


async def _async_open_recipe_by_voice(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    entry = _loaded_entry(hass)
    text: str = call.data[ATTR_TEXT]
    browser_id = call.data.get(CONF_BROWSER_ID) or entry.options.get(CONF_BROWSER_ID) or None
    dashboard_path = (
        call.data.get(CONF_DASHBOARD_PATH) or entry.options.get(CONF_DASHBOARD_PATH) or None
    )

    try:
        recipes = await entry.runtime_data.api.async_recipe_candidates()
    except MealieError as err:
        LOGGER.error("Could not list Mealie recipes: %s", err)
        recipes = []
    recipe = find_recipe(text, recipes)

    target: dict[str, Any]
    if recipe:
        LOGGER.info("Voice match: %r -> %s", text, recipe.slug)
        target = {"action": "open", "slug": recipe.slug}
    else:
        LOGGER.info("Voice match: %r -> no recipe, showing a search", text)
        target = {"action": "search", "text": text}

    _push(hass, browser_id, dashboard_path, target)

    # A tablet woken up just before this call may reload its web view a few
    # seconds later (seen with the Android companion app), losing the page we
    # just showed. Sending the same target again once it has settled fixes it.
    delay = entry.options.get(CONF_RESEND_DELAY, DEFAULT_RESEND_DELAY)
    if delay:

        async def resend() -> None:
            await asyncio.sleep(delay)
            LOGGER.debug("Re-sending %s after %ss", target, delay)
            _push(hass, browser_id, dashboard_path, target)

        entry.async_create_background_task(hass, resend(), f"{DOMAIN} resend")

    if recipe:
        return {"slug": recipe.slug, "name": recipe.name}
    return {"slug": None, "name": None}


@callback
def _push(
    hass: HomeAssistant,
    browser_id: str | None,
    dashboard_path: str | None,
    target: dict[str, Any],
) -> None:
    """Navigate the browser to the recipes view if asked, then hand the target to the card."""
    if browser_id and dashboard_path:
        if hass.services.has_service("browser_mod", "navigate"):
            hass.async_create_task(
                hass.services.async_call(
                    "browser_mod",
                    "navigate",
                    {"browser_id": browser_id, "path": dashboard_path},
                )
            )
        else:
            LOGGER.warning("browser_mod is not available, cannot open %s", dashboard_path)
    hass.data[DISPATCHER].push(browser_id, target)
