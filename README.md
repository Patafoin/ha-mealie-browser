# Mealie Browser for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![GitHub release](https://img.shields.io/github/v/release/Patafoin/ha-mealie-browser)](https://github.com/Patafoin/ha-mealie-browser/releases)
[![Validate](https://github.com/Patafoin/ha-mealie-browser/actions/workflows/validate.yml/badge.svg)](https://github.com/Patafoin/ha-mealie-browser/actions/workflows/validate.yml)

Browse your [Mealie](https://mealie.io) recipes from a Home Assistant dashboard, and open a recipe by voice on a kitchen tablet.

- **A dashboard card** (`custom:mealie-browser-card`): searchable recipe grid with category filters, and a full-card recipe view (picture, times, servings, ingredients, steps). No popup, made for wall tablets.
- **An action**, `mealie_browser.open_recipe_by_voice`: give it a spoken phrase ("dahl de lentilles"), it finds the matching recipe and shows it on the card — optionally steering a [browser_mod](https://github.com/thomasloven/hass-browser_mod) browser to the recipes view first.

Everything goes through Home Assistant: the browser never talks to Mealie, so the card works remotely, Mealie needs no CORS setup, and the Mealie API token never leaves the server.

## Requirements

- Home Assistant 2026.2 or newer.
- The core [Mealie integration](https://www.home-assistant.io/integrations/mealie/), set up. Mealie Browser reuses its connection (URL and token): there is nothing else to configure.
- Optional: [browser_mod](https://github.com/thomasloven/hass-browser_mod), to make a given browser navigate to the recipes view.

## Installation

### HACS

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/Patafoin/ha-mealie-browser`, category *Integration*.
2. Download **Mealie Browser**, then restart Home Assistant.
3. *Settings → Devices & services → Add integration → Mealie Browser*.

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
  browser_id: kitchen_tablet            # optional, browser_mod ID
  dashboard_path: /dashboard-kitchen/recipes   # optional
```

| Field | Description |
|---|---|
| `text` | The phrase to match. |
| `browser_id` | browser_mod ID of the browser that should show the recipe. Without it, every open Mealie Browser card shows it. |
| `dashboard_path` | View holding the card. With a `browser_id`, that browser navigates there first (requires browser_mod). |

`browser_id` and `dashboard_path` default to the integration options (*Configure* on the integration).

**How the recipe is chosen.** The phrase is compared, accents and punctuation ignored, with:

1. the recipe *extras* (the key/value pairs of the Mealie recipe editor; the key is enough, the value can stay empty),
2. the recipe name,

exact matches first, then partial ones. Extras are the place for the phrases people actually say, including speech-recognition mistakes (`dalle de lentilles` for *Dahl de lentilles*).

If nothing matches, the card shows the recipe list searched with the phrase.

The action returns the result, usable with `response_variable`:

```yaml
{"slug": "dahl-de-lentilles", "name": "Dahl de lentilles"}   # or {"slug": null, "name": null}
```

**Tablets that reload after waking up.** If the tablet is woken up right before the action (e.g. by an ADB key event), some web views reload a few seconds later and lose the recipe. Set *Send the recipe again after* in the integration options (e.g. 9 s) to send it twice.

### Example: Alexa or Assist

```yaml
script:
  open_recipe:
    fields:
      recipe_name:
        selector:
          text:
    sequence:
      - action: mealie_browser.open_recipe_by_voice
        data:
          text: "{{ recipe_name }}"
          browser_id: kitchen_tablet
          dashboard_path: /dashboard-kitchen/recipes
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT
