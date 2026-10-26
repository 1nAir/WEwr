import { GUIDE_CONTENT } from './config.js';
import { store } from './store.js';
import { timeAgo } from './utils/format.js';
import { ProfitabilityView } from './views/profitabilityView.js';
import { OrderBookView } from './views/orderbookView.js';
import { TradesView } from './views/tradesView.js';
import { LeaderboardsView } from './views/leaderboardsView.js';

/**
 * Main Application Controller & Hash Router for Wealthrate v2.0.
 */
class WealthrateApp {
  constructor() {
    this.profitabilityView = new ProfitabilityView(
      document.getElementById('profitability-mount')
    );
    this.orderbookView = new OrderBookView(
      document.getElementById('subview-orderbook')
    );
    this.tradesView = new TradesView(
      document.getElementById('subview-trades')
    );
    this.leaderboardsView = new LeaderboardsView(
      document.getElementById('subview-leaderboards')
    );

    this.loadedViews = new Set();
  }

  async start() {
    this.bindGlobalNavigation();
    this.bindUtilityActions();

    await store.ensureMeta();
    this.updateTimestampDisplay();

    window.addEventListener('hashchange', () => this.handleRouteChange());
    await this.handleRouteChange();
  }

  parseHash() {
    const raw = (window.location.hash || '#profitability').slice(1);
    const [pathPart] = raw.split('?');
    const segments = pathPart.split('/').filter(Boolean);

    if (segments[0] === 'market') {
      const sub = ['orderbook', 'trades', 'leaderboards'].includes(segments[1])
        ? segments[1]
        : store.state.marketSubtab || 'orderbook';
      return { section: 'market', subtab: sub };
    }
    return { section: 'profitability', subtab: null };
  }

  async handleRouteChange(forceRefresh = false) {
    const { section, subtab } = this.parseHash();
    store.state.section = section;
    if (subtab) {
      store.state.marketSubtab = subtab;
    }

    // Sync top navigation buttons & section visibility
    document.querySelectorAll('.nav-tab[data-section]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.section === section);
    });

    const profSection = document.getElementById('view-profitability');
    const mktSection = document.getElementById('view-market');
    if (profSection) profSection.hidden = section !== 'profitability';
    if (mktSection) mktSection.hidden = section !== 'market';

    if (section === 'profitability') {
      if (forceRefresh || !this.loadedViews.has('profitability')) {
        await this.profitabilityView.init(forceRefresh);
        this.loadedViews.add('profitability');
      }
    } else if (section === 'market') {
      const activeSub = store.state.marketSubtab || 'orderbook';

      document.querySelectorAll('.subnav-pill[data-subtab]').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.subtab === activeSub);
      });

      const subviews = {
        orderbook: document.getElementById('subview-orderbook'),
        trades: document.getElementById('subview-trades'),
        leaderboards: document.getElementById('subview-leaderboards'),
      };
      for (const [k, el] of Object.entries(subviews)) {
        if (el) el.hidden = k !== activeSub;
      }

      if (activeSub === 'orderbook' && (forceRefresh || !this.loadedViews.has('orderbook'))) {
        await this.orderbookView.init(forceRefresh);
        this.loadedViews.add('orderbook');
      } else if (activeSub === 'trades' && (forceRefresh || !this.loadedViews.has('trades'))) {
        await this.tradesView.init(forceRefresh);
        this.loadedViews.add('trades');
      } else if (
        activeSub === 'leaderboards' &&
        (forceRefresh || !this.loadedViews.has('leaderboards'))
      ) {
        await this.leaderboardsView.init(forceRefresh);
        this.loadedViews.add('leaderboards');
      }
    }

    this.updateTimestampDisplay();
  }

  updateTimestampDisplay() {
    const meta = store.meta;
    if (!meta || !meta.timestamps) return;

    const section = store.state.section;
    const sub = store.state.marketSubtab;
    const tsKey = section === 'profitability' ? 'profitability' : sub || 'orderbook';
    const ts = meta.timestamps[tsKey] || meta.generated_at;

    const headerText = document.getElementById('header-updated-text');
    if (headerText) {
      headerText.textContent = `Updated ${timeAgo(ts)}`;
    }

    const footerSync = document.getElementById('footer-sync-info');
    if (footerSync && ts) {
      const dateStr = new Date(ts * 1000).toLocaleString();
      footerSync.textContent = `Snapshot: ${dateStr}`;
    }
  }

  bindGlobalNavigation() {
    document.querySelectorAll('.nav-tab[data-section]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const sec = btn.dataset.section;
        if (sec === 'market') {
          window.location.hash = `#market/${store.state.marketSubtab || 'orderbook'}`;
        } else {
          window.location.hash = `#${sec}`;
        }
      });
    });

    document.querySelectorAll('.subnav-pill[data-subtab]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const sub = btn.dataset.subtab;
        window.location.hash = `#market/${sub}`;
      });
    });
  }

  bindUtilityActions() {
    const refreshBtn = document.getElementById('btn-live-refresh');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', async () => {
        refreshBtn.classList.add('spinning');
        try {
          await store.ensureMeta(true);
          await this.handleRouteChange(true);
        } finally {
          setTimeout(() => refreshBtn.classList.remove('spinning'), 350);
        }
      });
    }

    const guideBtn = document.getElementById('btn-open-guide');
    const closeGuideBtn = document.getElementById('btn-close-guide');
    const modal = document.getElementById('modal-guide');
    const modalBody = document.getElementById('modal-guide-content');

    if (guideBtn && modal && modalBody) {
      guideBtn.addEventListener('click', () => {
        const key =
          store.state.section === 'profitability'
            ? 'profitability'
            : store.state.marketSubtab || 'orderbook';
        modalBody.innerHTML = GUIDE_CONTENT[key] || GUIDE_CONTENT.profitability;
        modal.hidden = false;
      });
    }

    if (closeGuideBtn && modal) {
      closeGuideBtn.addEventListener('click', () => {
        modal.hidden = true;
      });
    }

    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.hidden = true;
      });
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const app = new WealthrateApp();
  app.start();
});

