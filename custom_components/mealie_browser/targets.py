"""Deliver "open this recipe" / "search this" orders to the cards.

A card subscribes over the websocket with the browser_mod ID of its browser
(or none). An order addressed to a browser goes only to cards running in that
browser; an order with no browser goes to every card.

When no matching card is listening yet (the tablet is waking up, or is still
navigating to the recipes view), the order is kept for a short while and
handed to the first matching card that subscribes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import time
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, PENDING_TARGET_TTL

WS_SUBSCRIBE = f"{DOMAIN}/subscribe"

type Target = dict[str, Any]


@dataclass
class _Subscriber:
    browser_id: str | None
    send: Callable[[Target], None]


@dataclass
class TargetDispatcher:
    """Routes targets to subscribed cards, keeps undelivered ones briefly."""

    _subscribers: list[_Subscriber] = field(default_factory=list)
    # browser_id (None = any browser) -> (target, monotonic time pushed)
    _pending: dict[str | None, tuple[Target, float]] = field(default_factory=dict)

    @staticmethod
    def _matches(target_browser: str | None, card_browser: str | None) -> bool:
        return target_browser is None or target_browser == card_browser

    @callback
    def push(self, browser_id: str | None, target: Target) -> None:
        """Send ``target`` to matching cards, or keep it until one subscribes."""
        delivered = False
        for sub in list(self._subscribers):
            if self._matches(browser_id, sub.browser_id):
                sub.send(target)
                delivered = True
        if delivered:
            self._pending.pop(browser_id, None)
        else:
            self._pending[browser_id] = (target, time.monotonic())

    @callback
    def subscribe(
        self, browser_id: str | None, send: Callable[[Target], None]
    ) -> Callable[[], None]:
        """Register a card; flush a pending target for it first."""
        now = time.monotonic()
        for key, (target, pushed) in list(self._pending.items()):
            if now - pushed > PENDING_TARGET_TTL:
                del self._pending[key]
            elif self._matches(key, browser_id):
                del self._pending[key]
                send(target)

        sub = _Subscriber(browser_id, send)
        self._subscribers.append(sub)

        @callback
        def unsubscribe() -> None:
            if sub in self._subscribers:
                self._subscribers.remove(sub)

        return unsubscribe


@callback
def async_register_websocket(hass: HomeAssistant, dispatcher: TargetDispatcher) -> None:
    """Register the card's subscription command."""

    @websocket_api.websocket_command(
        {
            vol.Required("type"): WS_SUBSCRIBE,
            vol.Optional("browser_id"): vol.Any(str, None),
        }
    )
    @callback
    def ws_subscribe(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        msg_id = msg["id"]
        connection.send_result(msg_id)

        @callback
        def send(target: Target) -> None:
            connection.send_message(websocket_api.event_message(msg_id, target))

        connection.subscriptions[msg_id] = dispatcher.subscribe(
            msg.get("browser_id"), send
        )

    websocket_api.async_register_command(hass, ws_subscribe)
