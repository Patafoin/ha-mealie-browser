# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [2.0.0b1] - 2026-10-03

Mealie Browser is now independent: it no longer needs the core Mealie integration, and no longer drives browsers. It finds the recipe and shows it on the open cards, nothing else. Waking a tablet up and bringing it to the recipes view belongs to your own script (see the README example).

### Changed

- **Own connection to Mealie**: the setup asks for the Mealie URL and an API token. The core Mealie integration is no longer needed. Entries from 1.x take the URL and token from the core Mealie entry if it still exists; otherwise Home Assistant asks for them (reauthentication).
- Every open card receives the result of `open_recipe_by_voice`; the last one is still kept for 60 seconds for a card that is not displayed yet.

### Removed

- The `mealie_browser:` YAML key (imported since 1.0.0); remove it from `configuration.yaml` if still there.
- `browser_id` and `dashboard_path` fields of `mealie_browser.open_recipe_by_voice`, and the browser_mod navigation they triggered. **Breaking**: remove these fields from your scripts, and call `browser_mod.navigate` there if you need it.
- Integration options (default browser, default dashboard path, second send after a delay). Existing options are dropped automatically.

## [1.0.0] - 2026-10-02

First public release.

### Added

- Setup from the UI. Mealie Browser reuses the connection of the core Mealie integration: no URL or token to enter.
- `custom:mealie-browser-card`: searchable recipe grid with category filters, and a full-card recipe view (picture, times, servings, ingredients, steps). Served by the integration and added to the dashboard resources automatically, with a versioned URL so browsers pick up new releases.
- Authenticated proxy for recipes, categories and pictures: the browser never talks to Mealie, the Mealie token stays on the server, and the card works away from home.
- `mealie_browser.open_recipe_by_voice` action: matches a spoken phrase against recipe extras, then names, and shows the recipe on the card (or a search when nothing matches). Optionally steers a browser_mod browser to the recipes view. Returns the matched recipe.
- Orders for a browser whose card is not displayed yet are kept for 60 seconds.
- Options: default browser, default dashboard path, and an optional second send for tablets whose web view reloads after waking up.
- English and French translations; the card follows the Home Assistant language and theme.
