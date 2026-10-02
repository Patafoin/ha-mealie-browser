"""Authenticated HTTP proxy between the card and Mealie.

The browser never talks to Mealie: Mealie sends no CORS headers, its token
must stay server-side, and it is often not reachable from outside the LAN
while Home Assistant is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .api import MealieApi, MealieError
from .const import API_BASE, DOMAIN, LOGGER

if TYPE_CHECKING:
    from . import MealieBrowserConfigEntry

# Query parameters of Mealie's GET /api/recipes the card may use
_RECIPE_LIST_PARAMS = {
    "search",
    "categories",
    "tags",
    "page",
    "perPage",
    "orderBy",
    "orderDirection",
}


def _loaded_api(hass: HomeAssistant) -> MealieApi | None:
    entry: MealieBrowserConfigEntry
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data.api
    return None


class _MealieProxyView(HomeAssistantView):
    requires_auth = True

    def _not_ready(self) -> web.Response:
        return self.json({"error": "not_configured"}, status_code=503)

    async def _proxy_json(
        self,
        request: web.Request,
        path: str,
        params: dict[str, str] | list[tuple[str, str]] | None = None,
    ) -> web.Response:
        api = _loaded_api(request.app[KEY_HASS])
        if api is None:
            return self._not_ready()
        try:
            status, data = await api.get_json(path, params)
        except MealieError as err:
            LOGGER.error("Mealie request failed: %s", err)
            return self.json({"error": "mealie_unreachable"}, status_code=502)
        return self.json(data, status_code=status)


class RecipesView(_MealieProxyView):
    """GET /api/mealie_browser/recipes?search=&categories=…"""

    url = f"{API_BASE}/recipes"
    name = f"api:{DOMAIN}:recipes"

    async def get(self, request: web.Request) -> web.Response:
        params: list[tuple[str, str]] = [
            (k, v) for k, v in request.query.items() if k in _RECIPE_LIST_PARAMS
        ]
        keys = {k for k, _ in params}
        if "orderBy" not in keys:
            params.append(("orderBy", "name"))
            params.append(("orderDirection", "asc"))
        if "perPage" not in keys:
            params.append(("perPage", "-1"))
        return await self._proxy_json(request, "/api/recipes", params)


class RecipeView(_MealieProxyView):
    """GET /api/mealie_browser/recipes/{slug}"""

    url = API_BASE + "/recipes/{slug:[A-Za-z0-9_-]+}"
    name = f"api:{DOMAIN}:recipe"

    async def get(self, request: web.Request, slug: str) -> web.Response:
        return await self._proxy_json(request, f"/api/recipes/{slug}")


class CategoriesView(_MealieProxyView):
    """GET /api/mealie_browser/categories"""

    url = f"{API_BASE}/categories"
    name = f"api:{DOMAIN}:categories"

    async def get(self, request: web.Request) -> web.Response:
        params = {"perPage": "-1", "orderBy": "name", "orderDirection": "asc"}
        return await self._proxy_json(request, "/api/organizers/categories", params)


class ImageView(_MealieProxyView):
    """GET /api/mealie_browser/images/{recipe_id}/{original|min-original|tiny-original}.webp"""

    url = (
        API_BASE
        + "/images/{recipe_id:[0-9a-fA-F-]{32,36}}"
        + "/{filename:(?:original|min-original|tiny-original)\\.webp}"
    )
    name = f"api:{DOMAIN}:image"

    async def get(
        self, request: web.Request, recipe_id: str, filename: str
    ) -> web.Response:
        api = _loaded_api(request.app[KEY_HASS])
        if api is None:
            return self._not_ready()
        try:
            status, body, content_type = await api.get_image(recipe_id, filename)
        except MealieError as err:
            LOGGER.debug("Mealie image request failed: %s", err)
            return web.Response(status=502)
        if status != 200:
            return web.Response(status=status)
        return web.Response(
            body=body,
            content_type=content_type,
            headers={"Cache-Control": "private, max-age=86400"},
        )


VIEWS: tuple[type[HomeAssistantView], ...] = (
    RecipesView,
    RecipeView,
    CategoriesView,
    ImageView,
)
