"""Deliver "open this recipe" / "search this" orders to the cards.

A card subscribes over the websocket; every order goes to every subscribed
card. Getting the right screen onto the recipes view (and keeping it awake)
is left to the caller, e.g. a script using browser_mod.

When no card is listening yet (the tablet is waking up, or is still
navigating to the recipes view), the last order is kept for a short while and
handed to the first card that subscribes.
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
class TargetDispatcher:
    """Sends targets to subscribed cards, keeps an undelivered one briefly."""

    _subscribers: list[Callable[[Target], None]] = field(default_factory=list)
    # (target, monotonic time pushed), or None
    _pending: tuple[Target, float] | None = None

    @callback
    def push(self, target: Target) -> None:
        """Send ``target`` to every card, or keep it until one subscribes."""
        for send in list(self._subscribers):
            send(target)
        self._pending = None if self._subscribers else (target, time.monotonic())

    @callback
    def subscribe(self, send: Callable[[Target], None]) -> Callable[[], None]:
        """Register a card; flush the pending target to it first."""
        if self._pending is not None:
            target, pushed = self._pending
            self._pending = None
            if time.monotonic() - pushed <= PENDING_TARGET_TTL:
                send(target)

        self._subscribers.append(send)

        @callback
        def unsubscribe() -> None:
            if send in self._subscribers:
                self._subscribers.remove(send)

        return unsubscribe


@callback
def async_register_websocket(hass: HomeAssistant, dispatcher: TargetDispatcher) -> None:
    """Register the card's subscription command."""

    @websocket_api.websocket_command(
        {
            vol.Required("type"): WS_SUBSCRIBE,
            # Sent by 1.0.0 cards still in a browser cache; ignored.
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

        connection.subscriptions[msg_id] = dispatcher.subscribe(send)

    websocket_api.async_register_command(hass, ws_subscribe)
