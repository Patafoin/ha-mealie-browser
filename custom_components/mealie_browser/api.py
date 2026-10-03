"""Thin Mealie API client.

The connection settings (URL, API token, SSL check) come from the config
entry. The token stays on the server: the browser only talks to the proxy.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import LOGGER, REQUEST_TIMEOUT
from .matching import RecipeCandidate

_TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)


class MealieError(Exception):
    """Mealie could not be reached or answered with an error."""


class MealieAuthError(MealieError):
    """Mealie refused the API token."""


@dataclass
class _CachedRecipe:
    updated_at: str | None
    candidate: RecipeCandidate


@dataclass
class MealieApi:
    """Read-only access to the few Mealie endpoints the card needs."""

    hass: HomeAssistant
    host: str
    token: str
    verify_ssl: bool = True
    # slug -> extras cache, invalidated by the recipe's updatedAt timestamp
    _recipe_cache: dict[str, _CachedRecipe] = field(default_factory=dict)

    @property
    def _host(self) -> str:
        return self.host.rstrip("/")

    @property
    def _session(self) -> aiohttp.ClientSession:
        return async_get_clientsession(self.hass, verify_ssl=self.verify_ssl)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def async_validate(self) -> None:
        """Check that Mealie answers and accepts the token."""
        status, _ = await self.get_json("/api/users/self")
        if status in (401, 403):
            raise MealieAuthError(f"HTTP {status}")
        if status != 200:
            raise MealieError(f"/api/users/self: HTTP {status}")

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
                try:
                    return resp.status, await resp.json(content_type=None)
                except ValueError:
                    if resp.status == 200:
                        raise
                    return resp.status, None  # error page that is not JSON
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
