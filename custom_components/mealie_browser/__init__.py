"""Mealie Browser: browse Mealie recipes from a Home Assistant dashboard.

- An authenticated proxy (``/api/mealie_browser/...``) lets the bundled card
  read recipes and images without ever exposing the Mealie token.
- The ``open_recipe_by_voice`` action matches a spoken phrase to a recipe and
  shows it on the cards. Waking a tablet up and bringing it to the recipes
  view is up to the caller (e.g. a script using browser_mod).

The Mealie URL and API token are those entered in the config flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration
from homeassistant.util.hass_dict import HassKey

from .api import MealieApi, MealieAuthError, MealieError
from .const import ATTR_TEXT, CARD_PATH, CARD_URL, DOMAIN, LOGGER, SERVICE_OPEN_RECIPE_BY_VOICE
from .lovelace import async_register_card_resource, async_remove_card_resource
from .matching import find_recipe
from .targets import TargetDispatcher, async_register_websocket
from .views import VIEWS

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

DISPATCHER: HassKey[TargetDispatcher] = HassKey(DOMAIN)

OPEN_RECIPE_SCHEMA = vol.Schema({vol.Required(ATTR_TEXT): cv.string})


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
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MealieBrowserConfigEntry) -> bool:
    """Set up Mealie Browser from a config entry."""
    if not entry.data.get(CONF_HOST) or not entry.data.get(CONF_API_TOKEN):
        # entry migrated from 1.x without a core mealie entry to copy from
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="connection_missing"
        )
    api = MealieApi(
        hass,
        entry.data[CONF_HOST],
        entry.data[CONF_API_TOKEN],
        entry.data.get(CONF_VERIFY_SSL, True),
    )
    try:
        await api.async_validate()
    except MealieAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="invalid_auth"
        ) from err
    except MealieError as err:
        raise ConfigEntryNotReady(str(err)) from err
    entry.runtime_data = MealieBrowserData(api=api)

    integration = await async_get_integration(hass, DOMAIN)
    await async_register_card_resource(hass, f"{CARD_URL}?v={integration.version}")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MealieBrowserConfigEntry) -> bool:
    """Unload a config entry (views and action stay registered, and answer 503)."""
    return True


async def async_remove_entry(hass: HomeAssistant, entry: MealieBrowserConfigEntry) -> None:
    """Drop the dashboard resource when the integration is removed."""
    await async_remove_card_resource(hass)


async def async_migrate_entry(hass: HomeAssistant, entry: MealieBrowserConfigEntry) -> bool:
    """2.0: own Mealie connection instead of the core mealie entry's; no options.

    The URL and token are copied from the core mealie entry 1.x pointed to. If
    it is gone, the entry is left without a connection and setup asks for one
    (reauthentication).
    """
    if entry.version > 2:
        return False
    if entry.version == 1:
        data: dict[str, Any] = {}
        old = hass.config_entries.async_get_entry(entry.data.get("mealie_entry_id", ""))
        if old is not None and old.domain == "mealie":
            data = {
                CONF_HOST: (old.data.get(CONF_HOST) or "").rstrip("/"),
                CONF_API_TOKEN: old.data.get(CONF_API_TOKEN),
                CONF_VERIFY_SSL: old.data.get(CONF_VERIFY_SSL, True),
            }
        hass.config_entries.async_update_entry(
            entry, data=data, options={}, version=2, minor_version=1
        )
    return True


def _loaded_entry(hass: HomeAssistant) -> MealieBrowserConfigEntry:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


async def _async_open_recipe_by_voice(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    entry = _loaded_entry(hass)
    text: str = call.data[ATTR_TEXT]

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

    hass.data[DISPATCHER].push(target)

    if recipe:
        return {"slug": recipe.slug, "name": recipe.name}
    return {"slug": None, "name": None}

