const IS_LOCAL =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1');

const REMOTE_DATA_BASE =
  'https://raw.githubusercontent.com/1nAir/WEwr/data/public/data';

/**
 * Centralized Data Loader & Application State Store.
 * - On localhost: reads static JSON slices from local `data/*.json`.
 * - On production (Vercel): reads live JSON slices directly from the GitHub `data` branch
 *   so data updates every 20 minutes without triggering any Vercel redeployments.
 */
class DataStore {
  constructor() {
    this.cache = new Map();
    this.inflight = new Map();
    this.meta = null;
    this.state = {
      section: 'profitability',
      marketSubtab: 'orderbook',
      expandedItem: null,
    };
  }

  /**
   * Clears the in-memory JSON cache so subsequent tab views fetch fresh data slices.
   */
  clearCache() {
    this.cache.clear();
    this.inflight.clear();
    this.meta = null;
  }

  /**
   * Fetches a JSON slice from GitHub `data` branch (or local `data/<filename>` on localhost).
   * @param {string} filename - e.g. 'meta.json', 'profitability.json'
   * @param {boolean} forceRefresh - bypasses memory & browser cache
   */
  async fetchSlice(filename, forceRefresh = false) {
    if (!forceRefresh && this.cache.has(filename)) {
      return this.cache.get(filename);
    }

    if (!forceRefresh && this.inflight.has(filename)) {
      return this.inflight.get(filename);
    }

    const baseUrl = IS_LOCAL ? `data/${filename}` : `${REMOTE_DATA_BASE}/${filename}`;
    const cacheBust = forceRefresh
      ? `?t=${Date.now()}`
      : `?v=${Math.floor(Date.now() / 60000)}`;
    const url = `${baseUrl}${cacheBust}`;

    const promise = fetch(url, {
      cache: forceRefresh ? 'no-store' : 'default',
    })
      .then(async (res) => {
        if (!res.ok && !IS_LOCAL) {
          const fallbackRes = await fetch(`data/${filename}${cacheBust}`);
          if (fallbackRes.ok) return fallbackRes.json();
        }
        if (!res.ok) {
          throw new Error(`Failed to fetch ${filename}: HTTP ${res.status}`);
        }
        return res.json();
      })
      .then((data) => {
        this.cache.set(filename, data);
        this.inflight.delete(filename);
        if (filename === 'meta.json') {
          this.meta = data;
        }
        return data;
      })
      .catch((err) => {
        this.inflight.delete(filename);
        throw err;
      });

    this.inflight.set(filename, promise);
    return promise;
  }

  async ensureMeta(forceRefresh = false) {
    if (!forceRefresh && this.meta) return this.meta;
    return this.fetchSlice('meta.json', forceRefresh);
  }

  getItemMeta(code) {
    if (!this.meta || !this.meta.items || !this.meta.items[code]) {
      return {
        code,
        name: code,
        short: code,
        pp: 1,
        color: '#6366f1',
        category: 'manufactured',
        line: 'Other',
        needs: {},
      };
    }
    return this.meta.items[code];
  }

  clearCache() {
    this.cache.clear();
    this.meta = null;
  }
}

export const store = new DataStore();

