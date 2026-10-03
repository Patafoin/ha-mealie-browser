# Mealie Browser for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![GitHub release](https://img.shields.io/github/v/release/Patafoin/ha-mealie-browser)](https://github.com/Patafoin/ha-mealie-browser/releases)
[![Validate](https://github.com/Patafoin/ha-mealie-browser/actions/workflows/validate.yml/badge.svg)](https://github.com/Patafoin/ha-mealie-browser/actions/workflows/validate.yml)

Browse your [Mealie](https://mealie.io) recipes from a Home Assistant dashboard, and open a recipe by voice on a kitchen tablet.

- **A dashboard card** (`custom:mealie-browser-card`): searchable recipe grid with category filters, and a full-card recipe view (picture, times, servings, ingredients, steps). No popup, made for wall tablets.
- **An action**, `mealie_browser.open_recipe_by_voice`: give it a spoken phrase ("dahl de lentilles"), it finds the matching recipe and shows it on the card. The integration only does that: waking a tablet up or bringing it to the recipes view stays in your own script (see the [example](#example-alexa-or-assist)).

Everything goes through Home Assistant: the browser never talks to Mealie, so the card works remotely, Mealie needs no CORS setup, and the Mealie API token never leaves the server.

## Requirements

- Home Assistant 2026.2 or newer.
- A [Mealie](https://mealie.io) server reachable from Home Assistant, and an API token (Mealie: user profile → *API Tokens*; a user that can read recipes is enough). The core Mealie integration is **not** needed.

## Installation

### HACS

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/Patafoin/ha-mealie-browser`, category *Integration*.
2. Download **Mealie Browser**, then restart Home Assistant.
3. *Settings → Devices & services → Add integration → Mealie Browser*, then enter the Mealie URL (e.g. `http://192.168.1.10:9925`) and the API token.

If the token is later revoked, Home Assistant shows a reauthentication request to enter a new one.

### Manual

Copy `custom_components/mealie_browser` into your `config/custom_components/`, restart Home Assistant, then add the integration as above.

The card is served by the integration and registered as a dashboard resource automatically. If your dashboard resources are managed in YAML, add it yourself:

```yaml
lovelace:
  resources:
    - url: /mealie_browser/mealie-browser-card.js
      type: module
```

## The card

```yaml
type: custom:mealie-browser-card
```

| Option | Default | Description |
|---|---|---|
| `height` | — | CSS height of the card, e.g. `700px`. Without it the card fills the height given by the layout (panel or grid view) and scrolls inside. |

The card follows the Home Assistant theme. To restyle it, set these variables in your theme or with card_mod:

| Variable | Default |
|---|---|
| `--mealie-browser-accent-color` | `--primary-color` |
| `--mealie-browser-text-color` | `--primary-text-color` |
| `--mealie-browser-muted-color` | `--secondary-text-color` |
| `--mealie-browser-surface-color` | `--secondary-background-color` |
| `--mealie-browser-border-color` | `--divider-color` |

## Open a recipe by voice

```yaml
action: mealie_browser.open_recipe_by_voice
data:
  text: "{{ recipe_name }}"
```

| Field | Description |
|---|---|
| `text` | The phrase to match. |

Every Mealie Browser card currently open shows the result. If no card is open yet (the tablet is still waking up or navigating), the last result is kept for 60 seconds and shown by the first card that opens.

**How the recipe is chosen.** The phrase is compared, accents and punctuation ignored, with:

1. the recipe *extras* (the key/value pairs of the Mealie recipe editor; the key is enough, the value can stay empty),
2. the recipe name,

exact matches first, then partial ones. Extras are the place for the phrases people actually say, including speech-recognition mistakes (`dalle de lentilles` for *Dahl de lentilles*).

If nothing matches, the card shows the recipe list searched with the phrase.

The action returns the result, usable with `response_variable`:

```yaml
{"slug": "dahl-de-lentilles", "name": "Dahl de lentilles"}   # or {"slug": null, "name": null}
```

### Example: Alexa or Assist

Bringing the tablet to the recipes view is the script's job, here with [browser_mod](https://github.com/thomasloven/hass-browser_mod):

```yaml
script:
  open_recipe:
    fields:
      recipe_name:
        selector:
          text:
    sequence:
      - action: browser_mod.navigate
        data:
          browser_id: kitchen_tablet
          path: /dashboard-kitchen/recipes
      - action: mealie_browser.open_recipe_by_voice
        data:
          text: "{{ recipe_name }}"
```

**Tablets that reload after waking up.** If the script wakes the tablet up first (e.g. by an ADB key event), some web views reload a few seconds later and lose the recipe. Add a `delay` and call the action a second time.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT
