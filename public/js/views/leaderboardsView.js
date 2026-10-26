import { store } from '../store.js';
import {
  formatPrice,
  formatInt,
  formatMoney,
  formatCompact,
  formatPct,
  escapeHtml,
  renderItemName,
} from '../utils/format.js';
import { renderEntityInline } from '../components/entityBadge.js';

/**
 * View Module: Market Subtab 3 — Top-25 Market Leaderboards.
 * Supports:
 * - Scope: All Commodities (or Specific Commodity selected from the wrapped multi-row pill grid)
 * - 4 Ranking Metrics: Live Sell, Live Buy, Top Buyers (₿), Top Sellers (₿)
 * - Time Window (for Realized Trades): 24h, 7d, 30d, all
 * - Expandable Multi-Commodity Breakdown Drawer per participant
 */
export class LeaderboardsView {
  constructor(mountEl) {
    this.mountEl = mountEl;
    this.data = null;
    this.scope = 'all'; // 'all' | 'item'
    this.selectedItem = 'steel';
    this.metric = 'live_sell'; // 'live_sell' | 'live_buy' | 'trade_buyers' | 'trade_sellers'
    this.window = '24h'; // '24h' | '7d' | '30d' | 'all'
    this.expandedRows = new Set();
  }

  async init(forceRefresh = false) {
    await store.ensureMeta(forceRefresh);
    this.data = await store.fetchSlice('leaderboards.json', forceRefresh);
    this.render();
  }

  isTradesMetric() {
    return !this.metric.startsWith('live_');
  }

  getActiveLeaderboardList() {
    if (!this.data) return { list: [], primaryLabel: 'Value' };

    if (this.scope === 'all') {
      const block = this.data.global_pp || {};
      if (this.metric === 'live_sell') {
        return {
          primaryLabel: 'Active Sell (PP)',
          primaryFormat: (v) => `${formatInt(v)} PP`,
          secondaryFormat: (v, entry) =>
            v > 0 && v !== entry?.value ? `${formatInt(v)} pcs` : '',
          list: block.live_depth?.top_sellers_pp || [],
        };
      }
      if (this.metric === 'live_buy') {
        return {
          primaryLabel: 'Locked Capital (₿)',
          primaryFormat: (v) => `${formatMoney(v)} ₿`,
          secondaryFormat: (v) => (v > 0 ? `${formatInt(v)} PP` : ''),
          list: block.live_depth?.top_buyers_pp || [],
        };
      }

      const tPeriod = (block.trades && block.trades[this.window]) || {};
      if (this.metric === 'trade_buyers') {
        return {
          primaryLabel: `Total Spent (${this.window.toUpperCase()})`,
          primaryFormat: (v) => `${formatMoney(v)} ₿`,
          secondaryFormat: (v) => (v > 0 ? `${formatInt(v)} PP` : ''),
          list: tPeriod.top_buyers || tPeriod.top_buyers_money || [],
        };
      }
      return {
        primaryLabel: `Total Earned (${this.window.toUpperCase()})`,
        primaryFormat: (v) => `${formatMoney(v)} ₿`,
        secondaryFormat: (v) => (v > 0 ? `${formatInt(v)} PP` : ''),
        list: tPeriod.top_sellers || tPeriod.top_sellers_money || [],
      };
    }

    // Specific Item Scope
    const itemMeta = store.getItemMeta(this.selectedItem);
    const block = (this.data.by_item && this.data.by_item[this.selectedItem]) || {};
    if (this.metric === 'live_sell') {
      return {
        primaryLabel: itemMeta.pp > 0 ? `${itemMeta.short || itemMeta.name} Supply (PP)` : `${itemMeta.short || itemMeta.name} (Units)`,
        primaryFormat: (v) =>
          itemMeta.pp > 0 ? `${formatInt(v * itemMeta.pp)} PP` : `${formatInt(v)} pcs`,
        secondaryFormat: (v, entry) =>
          itemMeta.pp > 1
            ? `${formatInt(entry?.value)} pcs (${formatPct(v, 1)})`
            : `${formatPct(v, 1)} share`,
        list: block.live_depth?.top_sellers || [],
      };
    }
    if (this.metric === 'live_buy') {
      return {
        primaryLabel: `${itemMeta.short || itemMeta.name} Bids (₿)`,
        primaryFormat: (v) => `${formatMoney(v)} ₿`,
        secondaryFormat: (v) =>
          itemMeta.pp > 0 ? `${formatInt(v * itemMeta.pp)} PP` : `${formatInt(v)} pcs`,
        list: block.live_depth?.top_buyers || [],
      };
    }

    const tPeriod = (block.trades && block.trades[this.window]) || {};
    const isBuy = this.metric === 'trade_buyers';
    const list = isBuy
      ? tPeriod.top_buyers || tPeriod.top_buyers_money || []
      : tPeriod.top_sellers || tPeriod.top_sellers_money || [];

    return {
      primaryLabel: isBuy
        ? `Spent on ${itemMeta.short || itemMeta.name} (${this.window.toUpperCase()})`
        : `Earned on ${itemMeta.short || itemMeta.name} (${this.window.toUpperCase()})`,
      primaryFormat: (v) => `${formatMoney(v)} ₿`,
      secondaryFormat: (v) =>
        itemMeta.pp > 0 ? `${formatInt(v * itemMeta.pp)} PP` : `${formatInt(v)} pcs`,
      list,
    };
  }

  render() {
    if (!this.mountEl || !this.data) return;

    const allItemCodes = Object.keys((store.meta && store.meta.items) || {});
    const itemPillsHtml = allItemCodes
      .map((code) => {
        const m = store.getItemMeta(code);
        const isActive = this.scope === 'item' && this.selectedItem === code;
        return `
          <button
            type="button"
            class="lb-item-chip ${isActive ? 'active' : ''}"
            data-select-item="${escapeHtml(code)}"
          >
            <img src="assets/${escapeHtml(code)}.webp" alt="" class="lb-chip-icon" />
            <span>${escapeHtml(m.short || m.name)}</span>
          </button>
        `;
      })
      .join('');

    const activeBoard = this.getActiveLeaderboardList();
    const allItemsSubNote =
      this.metric === 'live_sell'
        ? `<span class="count-tag">(excl. Cases &amp; Scraps)</span>`
        : '';

    this.mountEl.innerHTML = `
      <!-- Clean Multi-Row Filter Bar (No horizontal scroll required) -->
      <div class="table-card" style="padding:10px 12px;display:flex;flex-direction:column;gap:10px">
        <!-- Row 1: 4 Ranking Metrics + Time Window (for Trades) -->
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
          <div class="filter-pills" style="flex-wrap:wrap">
            <button type="button" class="filter-pill ${this.metric === 'live_sell' ? 'active' : ''}" data-lb-metric="live_sell">
              🏷️ Live Sell
            </button>
            <button type="button" class="filter-pill ${this.metric === 'live_buy' ? 'active' : ''}" data-lb-metric="live_buy">
              🛒 Live Buy
            </button>
            <button type="button" class="filter-pill ${this.metric === 'trade_buyers' ? 'active' : ''}" data-lb-metric="trade_buyers">
              🛒 Top Buyers (₿)
            </button>
            <button type="button" class="filter-pill ${this.metric === 'trade_sellers' ? 'active' : ''}" data-lb-metric="trade_sellers">
              🏷️ Top Sellers (₿)
            </button>
          </div>

          ${
            this.isTradesMetric()
              ? `
              <div class="filter-pills">
                <button type="button" class="filter-pill ${this.window === '24h' ? 'active' : ''}" data-lb-window="24h">24H</button>
                <button type="button" class="filter-pill ${this.window === '7d' ? 'active' : ''}" data-lb-window="7d">7D</button>
                <button type="button" class="filter-pill ${this.window === '30d' ? 'active' : ''}" data-lb-window="30d">30D</button>
                <button type="button" class="filter-pill ${this.window === 'all' ? 'active' : ''}" data-lb-window="all">All Time</button>
              </div>`
              : ''
          }
        </div>

        <!-- Row 2+: Wrapped Multi-Row Commodity Pills -->
        <div class="lb-items-grid">
          <button
            type="button"
            class="lb-item-chip ${this.scope === 'all' ? 'active' : ''}"
            data-scope="all"
          >
            <span>🌐 All Items</span>
            ${allItemsSubNote}
          </button>
          ${itemPillsHtml}
        </div>
      </div>

      <!-- Leaderboard Table Card (Starts directly with table header, no extra banner) -->
      <div class="table-card">
        <table class="terminal-table">
          <thead>
            <tr>
              <th style="width:52px;text-align:center">#</th>
              <th style="text-align:left">Participant</th>
              <th style="width:38%;text-align:right">${escapeHtml(activeBoard.primaryLabel)}</th>
            </tr>
          </thead>
          <tbody data-role="lb-tbody">
            ${this.renderLeaderboardRows(activeBoard)}
          </tbody>
        </table>
      </div>
    `;

    this.bindEvents();
  }

  renderLeaderboardRows(board) {
    const list = board.list || [];
    if (!list.length) {
      return `
        <tr>
          <td colspan="3" class="text-center text-muted" style="padding:28px">
            No participants found for this leaderboard filter.
          </td>
        </tr>
      `;
    }

    const rowsHtml = [];
    list.slice(0, 25).forEach((entry, idx) => {
      const rank = idx + 1;
      const rowKey = `${entry.id || idx}`;
      const isExpanded = this.expandedRows.has(rowKey);
      const rankClass = rank <= 3 ? `rank-${rank}` : '';

      const primaryStr = board.primaryFormat(entry.value, entry);
      const secondaryStr = board.secondaryFormat(entry.sub_value, entry);

      rowsHtml.push(`
        <tr class="item-row ${isExpanded ? 'expanded' : ''}" data-lb-row="${escapeHtml(rowKey)}">
          <td class="text-center">
            <span class="rank-badge ${rankClass}">#${rank}</span>
          </td>
          <td>
            <div style="display:flex;align-items:center;gap:8px;min-width:0">
              <span class="expand-caret">▶</span>
              ${renderEntityInline(entry, true)}
            </div>
          </td>
          <td class="text-right">
            <span class="metric-primary text-buy">${escapeHtml(primaryStr)}</span>
            ${secondaryStr ? `<span class="metric-sub">${escapeHtml(secondaryStr)}</span>` : ''}
          </td>
        </tr>
      `);

      if (isExpanded) {
        rowsHtml.push(this.renderParticipantBreakdown(entry));
      }
    });

    return rowsHtml.join('');
  }

  renderParticipantBreakdown(entry) {
    const breakdown = entry.by_item || [];
    if (!breakdown.length) {
      return `
        <tr class="drawer-row">
          <td colspan="3">
            <div class="drawer-container">
              <span class="text-muted">No per-commodity breakdown available.</span>
            </div>
          </td>
        </tr>
      `;
    }

    const cardsHtml = breakdown
      .map((b) => {
        const code = b.item;
        const meta = store.getItemMeta(code);
        const ordersHtml = (b.orders || [])
          .map(
            (o) =>
              `<span class="order-lot-pill">${formatCompact(o.quantity ?? o.q)} @ ${formatPrice(o.price ?? o.p)} ₿</span>`
          )
          .join('');

        const itemPp =
          b.pp > 0 ? b.pp : meta.pp > 0 ? (Number(b.units) || 0) * meta.pp : 0;
        const showPcs = itemPp === 0 || (meta.pp > 1 && b.units > 0 && b.units !== itemPp);

        return `
          <div class="lb-commodity-card">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:6px">
              <div style="display:flex;align-items:center;gap:6px">
                <img src="assets/${escapeHtml(code)}.webp" alt="" style="width:22px;height:22px;object-fit:contain" />
                <strong style="font-size:0.82rem">${renderItemName(meta)}</strong>
              </div>
              ${b.avg_price > 0 ? `<span class="text-muted mono" style="font-size:0.7rem">~${formatPrice(b.avg_price)} ₿</span>` : ''}
            </div>
            <div class="mono" style="font-size:0.74rem;display:flex;gap:8px;flex-wrap:wrap">
              ${itemPp > 0 ? `<span class="text-pp">${formatInt(itemPp)} PP</span>` : ''}
              ${showPcs ? `<span>${formatInt(b.units)} pcs</span>` : ''}
              ${b.money > 0 ? `<span class="text-btc">${formatMoney(b.money)} ₿</span>` : ''}
            </div>
            ${ordersHtml ? `<div class="order-pills-row">${ordersHtml}</div>` : ''}
          </div>
        `;
      })
      .join('');

    return `
      <tr class="drawer-row">
        <td colspan="3">
          <div class="drawer-container">
            <div class="top3-strip-label">
              <span>Commodity Breakdown (${breakdown.length} item${breakdown.length > 1 ? 's' : ''})</span>
            </div>
            <div class="lb-breakdown-grid">
              ${cardsHtml}
            </div>
          </div>
        </td>
      </tr>
    `;
  }

  bindEvents() {
    this.mountEl.querySelectorAll('[data-scope]').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.scope = btn.dataset.scope;
        this.expandedRows.clear();
        this.render();
      });
    });

    this.mountEl.querySelectorAll('[data-select-item]').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.scope = 'item';
        this.selectedItem = btn.dataset.selectItem;
        this.expandedRows.clear();
        this.render();
      });
    });

    this.mountEl.querySelectorAll('[data-lb-metric]').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.metric = btn.dataset.lbMetric;
        this.expandedRows.clear();
        this.render();
      });
    });

    this.mountEl.querySelectorAll('[data-lb-window]').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.window = btn.dataset.lbWindow;
        this.expandedRows.clear();
        this.render();
      });
    });

    this.mountEl.querySelectorAll('[data-lb-row]').forEach((row) => {
      row.addEventListener('click', () => {
        const key = row.dataset.lbRow;
        if (this.expandedRows.has(key)) {
          this.expandedRows.delete(key);
        } else {
          this.expandedRows.add(key);
        }
        this.render();
      });
    });
  }
}
