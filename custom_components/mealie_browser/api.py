"""Thin Mealie API client.

The connection settings (URL, token, SSL check) are borrowed from the core
``mealie`` integration's config entry, so this integration never stores a
secret of its own and the token never reaches the browser.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import LOGGER, REQUEST_TIMEOUT
from .matching import RecipeCandidate

_TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)


class MealieError(Exception):
    """Mealie could not be reached or answered with an error."""


@dataclass
class _CachedRecipe:
    updated_at: str | None
    candidate: RecipeCandidate


@dataclass
class MealieApi:
    """Read-only access to the few Mealie endpoints the card needs."""

    hass: HomeAssistant
    mealie_entry: ConfigEntry
    # slug -> extras cache, invalidated by the recipe's updatedAt timestamp
    _recipe_cache: dict[str, _CachedRecipe] = field(default_factory=dict)

    @property
    def _host(self) -> str:
        return (self.mealie_entry.data.get(CONF_HOST) or "").rstrip("/")

    @property
    def _session(self) -> aiohttp.ClientSession:
        return async_get_clientsession(
            self.hass, verify_ssl=self.mealie_entry.data.get(CONF_VERIFY_SSL, True)
        )

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.mealie_entry.data.get(CONF_API_TOKEN)}"}

    async def get_json(
        self, path: str, params: Mapping[str, str] | list[tuple[str, str]] | None = None
    ) -> tuple[int, Any]:
        """GET a Mealie API path, return (status, decoded JSON)."""
        try:
            async with self._session.get(
                f"{self._host}{path}",
                headers=self._headers,
                params=params,
                timeout=_TIMEOUT,
            ) as resp:
                return resp.status, await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise MealieError(f"{path}: {err}") from err

    async def get_image(self, recipe_id: str, filename: str) -> tuple[int, bytes, str]:
        """GET a recipe image, return (status, body, content type)."""
        path = f"/api/media/recipes/{recipe_id}/images/{filename}"
        try:
            async with self._session.get(
                f"{self._host}{path}", headers=self._headers, timeout=_TIMEOUT
            ) as resp:
                return resp.status, await resp.read(), resp.content_type
        except (aiohttp.ClientError, TimeoutError) as err:
            raise MealieError(f"{path}: {err}") from err

    async def _get_ok(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        status, data = await self.get_json(path, params)
        if status != 200:
            raise MealieError(f"{path}: HTTP {status}")
        return data

    async def async_recipe_candidates(self) -> list[RecipeCandidate]:
        """Every recipe with its name and extras, for voice matching.

        Extras are only returned by the detail endpoint, so each recipe is
        fetched once and cached until Mealie reports it as updated.
        """
        summary = await self._get_ok("/api/recipes", {"perPage": "-1"})
        items = summary.get("items") or []

        semaphore = asyncio.Semaphore(6)

        async def candidate(item: dict[str, Any]) -> RecipeCandidate | None:
            slug = item.get("slug")
            if not slug:
                return None
            updated_at = item.get("updatedAt") or item.get("dateUpdated")
            cached = self._recipe_cache.get(slug)
            if cached and cached.updated_at == updated_at:
                return cached.candidate
            async with semaphore:
                try:
                    detail = await self._get_ok(f"/api/recipes/{slug}")
                except MealieError as err:
                    LOGGER.warning("Could not read recipe %s: %s", slug, err)
                    return RecipeCandidate(slug, item.get("name") or "", {})
            result = RecipeCandidate(
                slug, detail.get("name") or "", detail.get("extras") or {}
            )
            self._recipe_cache[slug] = _CachedRecipe(updated_at, result)
            return result

        results = await asyncio.gather(*(candidate(i) for i in items))
        return [r for r in results if r is not None]
