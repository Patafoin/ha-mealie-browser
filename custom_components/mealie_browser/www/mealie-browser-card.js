// Mealie Browser card
// Recipe list + full-card recipe view. Every request goes through the
// integration's authenticated proxy (/api/mealie_browser/...): Mealie sends
// no CORS headers and its token must stay server-side. Images are fetched
// with the user's HA token and shown as blob URLs.

const CARD_VERSION = '2.0.0b1';

const STRINGS = {
  en: {
    search: 'Search a recipe…',
    loading: 'Loading…',
    noRecipe: 'No recipe',
    listError: 'Could not load the recipes',
    detailError: 'Could not load this recipe',
    notFound: 'Recipe not found',
    notConfigured: 'Mealie Browser is not set up',
    back: 'Back to the list',
    prep: 'Prep',
    cook: 'Cooking',
    total: 'Total',
    servings: (n) => `${n} servings`,
    ingredients: 'Ingredients',
    instructions: 'Instructions',
    description: 'Browse and display Mealie recipes (list and full-card recipe view).',
  },
  fr: {
    search: 'Rechercher une recette…',
    loading: 'Chargement…',
    noRecipe: 'Aucune recette',
    listError: 'Impossible de charger les recettes',
    detailError: 'Impossible de charger cette recette',
    notFound: 'Recette introuvable',
    notConfigured: "Mealie Browser n'est pas configuré",
    back: 'Retour à la liste',
    prep: 'Préparation',
    cook: 'Cuisson',
    total: 'Total',
    servings: (n) => `${n} portions`,
    ingredients: 'Ingrédients',
    instructions: 'Préparation',
    description: 'Parcourt et affiche les recettes Mealie (liste et fiche plein cadre).',
  },
};

const esc = (value) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
  );

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Right after a HA restart the proxy can answer 503 until the integration is
// set up, and nothing else would retry before the card is remounted.
async function withRetry(fn, attempts = 4, delayMs = 2500) {
  let lastError;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (e) {
      lastError = e;
      if (i < attempts - 1) await sleep(delayMs * (i + 1));
    }
  }
  throw lastError;
}

// Mealie durations look like "PT30M" / "PT1H15M"; older recipes may hold
// free text, shown as is.
function fmtDuration(value) {
  if (!value) return null;
  const m = /^P(?:T(?:(\d+)H)?(?:(\d+)M)?)?$/.exec(value);
  if (!m) return value;
  const h = parseInt(m[1] || '0', 10);
  const mi = parseInt(m[2] || '0', 10);
  if (!h && !mi) return null;
  return h ? `${h}h${mi ? String(mi).padStart(2, '0') : ''}` : `${mi} min`;
}

class MealieBrowserCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._config = config || {};
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
      this._view = 'list';
      this._recipes = [];
      this._categories = [];
      this._activeCategories = new Set();
      this._search = '';
      this._loadingList = false;
      this._listError = null;
      this._detail = null;
      this._loadingDetail = false;
      this._detailError = null;
      this._images = new Map(); // proxy URL -> Promise<blob URL | null>
    }
    this.style.height = this._config.height || '';
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._render();
      this._loadCategories();
      this._loadRecipes();
      this._subscribe();
    }
  }

  getCardSize() {
    return 8;
  }

  connectedCallback() {
    this._subscribe();
  }

  disconnectedCallback() {
    this._unsubscribe();
  }

  _t(key, ...args) {
    const lang = (this._hass && (this._hass.locale?.language || this._hass.language)) || 'en';
    const table = STRINGS[lang.split('-')[0]] || STRINGS.en;
    const value = table[key] ?? STRINGS.en[key];
    return typeof value === 'function' ? value(...args) : value;
  }

  // Orders from the open_recipe_by_voice action, including one left pending
  // while no card was displayed.
  async _subscribe() {
    if (!this._hass || !this.isConnected || this._unsub) return;
    this._unsub = this._hass.connection
      .subscribeMessage((target) => this._onTarget(target), {
        type: 'mealie_browser/subscribe',
      })
      .catch((e) => {
        console.error('mealie-browser-card: subscribe', e);
        this._unsub = null;
        return null;
      });
  }

  async _unsubscribe() {
    const unsub = this._unsub;
    this._unsub = null;
    if (unsub) {
      const fn = await unsub;
      if (fn) fn().catch(() => {});
    }
  }

  _onTarget(target) {
    if (target.action === 'open' && target.slug) {
      this._openRecipe(target.slug);
    } else if (target.action === 'search') {
      this._view = 'list';
      this._search = target.text || '';
      this._render();
      this._loadRecipes();
    }
  }

  _api(path) {
    return withRetry(() => this._hass.callApi('GET', `mealie_browser/${path}`));
  }

  async _loadCategories() {
    try {
      const res = await this._api('categories');
      this._categories = res.items || [];
    } catch (e) {
      console.error('mealie-browser-card: categories', e);
    }
    if (this._view === 'list') this._render();
  }

  async _loadRecipes() {
    const request = (this._listRequest = {});
    this._loadingList = true;
    this._listError = null;
    this._renderResults();
    const params = new URLSearchParams();
    if (this._search) params.set('search', this._search);
    for (const id of this._activeCategories) params.append('categories', id);
    try {
      const res = await this._api(`recipes?${params.toString()}`);
      if (request !== this._listRequest) return;
      this._recipes = res.items || [];
    } catch (e) {
      if (request !== this._listRequest) return;
      console.error('mealie-browser-card: recipes', e);
      this._recipes = [];
      this._listError = e && e.status_code === 503 ? 'notConfigured' : 'listError';
    }
    this._loadingList = false;
    this._renderResults();
  }

  async _openRecipe(slug) {
    const request = (this._detailRequest = {});
    this._view = 'detail';
    this._detail = null;
    this._detailError = null;
    this._loadingDetail = true;
    this._render();
    try {
      const detail = await this._api(`recipes/${encodeURIComponent(slug)}`);
      if (request !== this._detailRequest) return;
      this._detail = detail;
    } catch (e) {
      if (request !== this._detailRequest) return;
      console.error('mealie-browser-card: recipe', e);
      this._detailError = e && e.status_code === 404 ? 'notFound' : 'detailError';
    }
    this._loadingDetail = false;
    this._render();
  }

  _backToList() {
    this._view = 'list';
    this._detail = null;
    this._detailRequest = null;
    this._render();
  }

  _toggleCategory(id) {
    if (this._activeCategories.has(id)) this._activeCategories.delete(id);
    else this._activeCategories.add(id);
    this.shadowRoot
      .querySelectorAll('.chip')
      .forEach((chip) => chip.classList.toggle('active', this._activeCategories.has(chip.dataset.id)));
    this._loadRecipes();
  }

  _imagePath(recipe, full) {
    if (!recipe || !recipe.id || !recipe.image) return null;
    const file = full ? 'original.webp' : 'min-original.webp';
    return `/api/mealie_browser/images/${recipe.id}/${file}`;
  }

  _blobUrl(path) {
    if (!this._images.has(path)) {
      this._images.set(
        path,
        this._hass
          .fetchWithAuth(path)
          .then((res) => (res.ok ? res.blob() : null))
          .then((blob) => (blob ? URL.createObjectURL(blob) : null))
          .catch(() => null)
      );
    }
    return this._images.get(path);
  }

  _fillImages(root) {
    root.querySelectorAll('img[data-src]').forEach(async (img) => {
      const url = await this._blobUrl(img.dataset.src);
      if (url) img.src = url;
      else img.closest('.img')?.classList.add('missing');
    });
  }

  // ---------- rendering ----------

  _renderTile(recipe) {
    const path = this._imagePath(recipe, false);
    const time = fmtDuration(recipe.totalTime) || fmtDuration(recipe.performTime);
    return `
      <div class="tile" data-slug="${esc(recipe.slug)}">
        <div class="img ${path ? '' : 'missing'}">
          ${path ? `<img data-src="${esc(path)}" alt="" />` : ''}
          <ha-icon icon="mdi:chef-hat"></ha-icon>
        </div>
        <div class="tile-body">
          <div class="tile-name">${esc(recipe.name)}</div>
          ${
            time
              ? `<div class="tile-meta"><ha-icon icon="mdi:clock-outline"></ha-icon>${esc(time)}</div>`
              : ''
          }
        </div>
      </div>`;
  }

  _resultsHtml() {
    if (this._loadingList) return `<div class="empty">${this._t('loading')}</div>`;
    if (this._listError) return `<div class="empty">${this._t(this._listError)}</div>`;
    if (!this._recipes.length) return `<div class="empty">${this._t('noRecipe')}</div>`;
    return `<div class="grid">${this._recipes.map((r) => this._renderTile(r)).join('')}</div>`;
  }

  // Only the results are redrawn while searching, so the search field keeps
  // its focus and caret.
  _renderResults() {
    const results = this.shadowRoot && this.shadowRoot.querySelector('.results');
    if (!results || this._view !== 'list') return;
    results.innerHTML = this._resultsHtml();
    results.querySelectorAll('.tile').forEach((tile) => {
      tile.addEventListener('click', () => this._openRecipe(tile.dataset.slug));
    });
    this._fillImages(results);
  }

  _listHtml() {
    const chips = this._categories
      .map(
        (c) => `
        <div class="chip ${this._activeCategories.has(c.id) ? 'active' : ''}" data-id="${esc(c.id)}">
          ${esc(c.name)}
        </div>`
      )
      .join('');
    return `
      <div class="toolbar">
        <div class="search-wrap">
          <ha-icon icon="mdi:magnify"></ha-icon>
          <input class="search" type="search" placeholder="${esc(this._t('search'))}" value="${esc(this._search)}" />
        </div>
        ${chips ? `<div class="chips">${chips}</div>` : ''}
      </div>
      <div class="results"></div>`;
  }

  _detailHtml() {
    const back = `<button class="back"><ha-icon icon="mdi:arrow-left"></ha-icon>${this._t('back')}</button>`;
    if (this._loadingDetail) return `<div class="detail">${back}<div class="empty">${this._t('loading')}</div></div>`;
    if (this._detailError || !this._detail) {
      return `<div class="detail">${back}<div class="empty">${this._t(this._detailError || 'notFound')}</div></div>`;
    }
    const r = this._detail;
    const path = this._imagePath(r, true);
    const times = [
      ['mdi:clock-start', 'prep', fmtDuration(r.prepTime)],
      ['mdi:pot-steam', 'cook', fmtDuration(r.performTime || r.cookTime)],
      ['mdi:clock-outline', 'total', fmtDuration(r.totalTime)],
    ].filter(([, , v]) => v);
    const meta = times.map(
      ([icon, label, value]) =>
        `<div class="meta-item"><ha-icon icon="${icon}"></ha-icon><span>${this._t(label)} : ${esc(value)}</span></div>`
    );
    if (r.recipeServings) {
      meta.push(
        `<div class="meta-item"><ha-icon icon="mdi:silverware-fork-knife"></ha-icon><span>${esc(this._t('servings', r.recipeServings))}</span></div>`
      );
    }
    const ingredients = (r.recipeIngredient || [])
      .map((i) => `<li>${esc(i.display || i.note || i.originalText || '')}</li>`)
      .join('');
    const steps = (r.recipeInstructions || [])
      .map(
        (s) => `
        <li>
          ${s.title || s.summary ? `<div class="step-title">${esc(s.title || s.summary)}</div>` : ''}
          <div class="step-text">${esc(s.text).replace(/\n/g, '<br/>')}</div>
        </li>`
      )
      .join('');
    return `
      <div class="detail">
        ${back}
        ${path ? `<div class="img detail-img"><img data-src="${esc(path)}" alt="" /></div>` : ''}
        <h2>${esc(r.name)}</h2>
        ${r.description ? `<p class="desc">${esc(r.description)}</p>` : ''}
        ${meta.length ? `<div class="meta">${meta.join('')}</div>` : ''}
        <div class="columns">
          <div class="ingredients">
            <h3>${this._t('ingredients')}</h3>
            <ul>${ingredients}</ul>
          </div>
          <div class="instructions">
            <h3>${this._t('instructions')}</h3>
            <ol>${steps}</ol>
          </div>
        </div>
      </div>`;
  }

  _render() {
    if (!this.shadowRoot) return;
    const content = !this._hass ? '' : this._view === 'detail' ? this._detailHtml() : this._listHtml();
    this.shadowRoot.innerHTML = `
      <style>${MealieBrowserCard.styles}</style>
      <ha-card><div class="root">${content}</div></ha-card>`;
    if (!this._hass) return;

    if (this._view === 'detail') {
      this.shadowRoot.querySelector('.back')?.addEventListener('click', () => this._backToList());
      this._fillImages(this.shadowRoot);
      return;
    }
    this.shadowRoot.querySelector('.search')?.addEventListener('input', (e) => {
      this._search = e.target.value;
      clearTimeout(this._searchDebounce);
      this._searchDebounce = setTimeout(() => this._loadRecipes(), 350);
    });
    this.shadowRoot.querySelectorAll('.chip').forEach((chip) => {
      chip.addEventListener('click', () => this._toggleCategory(chip.dataset.id));
    });
    this._renderResults();
  }

  // Colours come from the HA theme; override the --mealie-browser-* variables
  // (theme or card_mod) to restyle the card.
  static get styles() {
    return `
      :host {
        display: block;
        height: 100%;
        --mb-accent: var(--mealie-browser-accent-color, var(--primary-color));
        --mb-text: var(--mealie-browser-text-color, var(--primary-text-color));
        --mb-muted: var(--mealie-browser-muted-color, var(--secondary-text-color));
        --mb-surface: var(--mealie-browser-surface-color, var(--secondary-background-color, rgba(127,127,127,0.08)));
        --mb-border: var(--mealie-browser-border-color, var(--divider-color, rgba(127,127,127,0.2)));
      }
      ha-card {
        height: 100%;
        box-sizing: border-box;
        padding: 16px;
        overflow: hidden;
        color: var(--mb-text);
      }
      .root { height: 100%; display: flex; flex-direction: column; overflow: hidden; }
      .toolbar { display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; flex: none; }
      .search-wrap {
        display: flex; align-items: center; gap: 8px;
        background: var(--mb-surface);
        border: 1px solid var(--mb-border);
        border-radius: 14px;
        padding: 8px 12px;
      }
      .search-wrap ha-icon { --mdc-icon-size: 18px; color: var(--mb-muted); }
      .search {
        flex: 1; border: none; outline: none; background: transparent;
        color: var(--mb-text); font: inherit; font-size: 15.5px; font-weight: 600;
      }
      .search::placeholder { color: var(--mb-muted); }
      .chips { display: flex; flex-wrap: wrap; gap: 6px; }
      .chip {
        font-size: 13px; font-weight: 700; padding: 5px 11px;
        border-radius: 100px; cursor: pointer;
        background: var(--mb-surface);
        border: 1px solid var(--mb-border);
        color: var(--mb-muted);
      }
      .chip.active {
        background: color-mix(in srgb, var(--mb-accent) 15%, transparent);
        border-color: color-mix(in srgb, var(--mb-accent) 45%, transparent);
        color: var(--mb-accent);
      }
      .results { flex: 1; min-height: 0; display: flex; flex-direction: column; }
      .grid {
        flex: 1; overflow-y: auto;
        -webkit-overflow-scrolling: touch;
        touch-action: pan-y;
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
        align-content: start;
        gap: 12px;
        padding: 0 4px 4px 0;
      }
      .tile {
        cursor: pointer;
        border-radius: 16px;
        background: var(--mb-surface);
        border: 1px solid var(--mb-border);
        overflow: hidden;
        display: flex; flex-direction: column;
        aspect-ratio: 1 / 1;
      }
      .img {
        position: relative; flex: 1; min-height: 0;
        display: flex; align-items: center; justify-content: center;
      }
      .img img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
      .img ha-icon { --mdc-icon-size: 30px; color: var(--mb-accent); opacity: 0.6; }
      .img:not(.missing) ha-icon { visibility: hidden; }
      .tile-body { padding: 8px 10px 10px; display: flex; flex-direction: column; gap: 4px; }
      .tile-name { font-size: 14.5px; font-weight: 700; line-height: 1.3; }
      .tile-meta { display: flex; align-items: center; gap: 4px; font-size: 12.5px; color: var(--mb-muted); font-weight: 600; }
      .tile-meta ha-icon { --mdc-icon-size: 13px; }
      .empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--mb-muted); font-size: 15px; font-weight: 600; padding: 24px 0; }

      .detail {
        flex: 1; overflow-y: auto;
        -webkit-overflow-scrolling: touch;
        touch-action: pan-y;
        display: flex; flex-direction: column; gap: 12px;
      }
      .back {
        align-self: flex-start; display: flex; align-items: center; gap: 6px;
        background: var(--mb-surface); border: 1px solid var(--mb-border);
        color: var(--mb-text); border-radius: 100px; padding: 7px 14px;
        font: inherit; font-size: 14px; font-weight: 700; cursor: pointer;
      }
      .back ha-icon { --mdc-icon-size: 15px; }
      .detail-img { flex: none; height: 260px; border-radius: 16px; overflow: hidden; }
      .detail-img.missing { display: none; }
      h2 { margin: 0; font-size: 23px; font-weight: 800; }
      .desc { margin: 0; font-size: 15px; color: var(--mb-muted); line-height: 1.5; }
      .meta { display: flex; flex-wrap: wrap; gap: 14px; }
      .meta-item { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 700; color: var(--mb-muted); }
      .meta-item ha-icon { --mdc-icon-size: 16px; color: var(--mb-accent); }
      .columns { display: grid; grid-template-columns: 1fr 1.4fr; gap: 20px; }
      h3 { font-size: 14px; text-transform: uppercase; letter-spacing: .06em; color: var(--mb-muted); margin: 0 0 8px; }
      .ingredients ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 7px; }
      .ingredients li { font-size: 14.5px; padding-left: 14px; position: relative; }
      .ingredients li::before {
        content: ''; position: absolute; left: 0; top: 6px; width: 5px; height: 5px;
        border-radius: 50%; background: var(--mb-accent);
      }
      .instructions ol { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 12px; }
      .instructions li { font-size: 15px; line-height: 1.5; }
      .step-title { font-weight: 700; color: var(--mb-accent); font-size: 13.5px; text-transform: uppercase; margin-bottom: 2px; }
      @media (max-width: 620px) {
        .columns { grid-template-columns: 1fr; }
      }
    `;
  }
}

if (!customElements.get('mealie-browser-card')) {
  customElements.define('mealie-browser-card', MealieBrowserCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'mealie-browser-card',
    name: 'Mealie Browser',
    description: STRINGS[(navigator.language || 'en').split('-')[0]]?.description || STRINGS.en.description,
    documentationURL: 'https://github.com/Patafoin/ha-mealie-browser',
  });
  console.info(`%c MEALIE-BROWSER-CARD %c ${CARD_VERSION} `, 'color:white;background:#E58325', 'color:#E58325');
}
