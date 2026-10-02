"""Keep the card registered as a dashboard resource.

The card is served by the integration (``/mealie_browser/...js``). In storage
mode (the default), its URL is added to the dashboard resources with the
integration version as a query string, so a new release busts the browser
cache. In YAML resource mode, the user adds the resource by hand.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant

from .const import CARD_URL, LOGGER


def _storage_resources(hass: HomeAssistant) -> Any | None:
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or lovelace.resource_mode != "storage":
        return None
    return lovelace.resources


def _ours(item: dict[str, Any]) -> bool:
    url = item.get("url", "")
    return url == CARD_URL or url.startswith(f"{CARD_URL}?")


async def async_register_card_resource(hass: HomeAssistant, url: str) -> None:
    """Make ``url`` the only resource pointing at the card."""
    if (resources := _storage_resources(hass)) is None:
        LOGGER.debug("Dashboard resources in YAML mode, add %s by hand", url)
        return
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True

    existing = [item for item in resources.async_items() if _ours(item)]
    if len(existing) == 1 and existing[0]["url"] == url:
        return
    # Remove before adding: two versions of the module loaded at once would
    # define the custom element twice.
    for item in existing:
        await resources.async_delete_item(item["id"])
    await resources.async_create_item({"res_type": "module", "url": url})
    LOGGER.debug("Dashboard resource set to %s", url)


async def async_remove_card_resource(hass: HomeAssistant) -> None:
    """Remove the card's dashboard resource."""
    if (resources := _storage_resources(hass)) is None:
        return
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True
    for item in [i for i in resources.async_items() if _ours(i)]:
        await resources.async_delete_item(item["id"])
