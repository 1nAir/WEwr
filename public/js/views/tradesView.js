import { store } from '../store.js';
import {
  formatPrice,
  formatInt,
  formatMoney,
  formatCompact,
  formatPct,
  formatIsoShort,
  escapeHtml,
  renderItemName,
} from '../utils/format.js';
import { observeOnce } from '../utils/dom.js';
import { renderEntityInline } from '../components/entityBadge.js';
import { renderSparklineSvg } from '../components/sparkline.js';
import { HistoryChartWidget } from '../components/historyChart.js';

/**
 * View Module: Market Subtab 2 — Executed Market Transactions & Volume Profile (POC).
 */
export class TradesView {
  constructor(mountEl) {
    this.mountEl = mountEl;
    this.data = null;
    this.activeWindow = '24h'; // '24h' | '7d' | '30d' | 'all'
    this.sortField = 'total_money'; // 'name' | 'total_pp' | 'total_money' | 'vwap'
    this.sortDesc = true;
    this.expandedItems = new Set();
    this.showFullProfile = new Set();
    this.chartWidget = null;
  }

  async init(forceRefresh = false) {
    await store.ensureMeta(forceRefresh);
    this.data = await store.fetchSlice('trades.json', forceRefresh);
    this.render();
  }

  getActivePeriodBlock() {
    if (!this.data) return { items: {}, summary: {} };
    const periods = this.data.periods || {};
    if (periods[this.activeWindow]) {
      const p = periods[this.activeWindow];
      return {
        summary: {
          total_market_money: p.total_market_money || 0,
          total_market_pp: p.total_market_pp || 0,
          total_market_units: p.total_market_units || 0,
          total_market_tx: p.total_market_tx || 0,
        },
        items: p.items || {},
      };
    }
    return {
      summary: this.data.summary || {},
      items: this.data.items || {},
    };
  }

  render() {
    if (!this.mountEl || !this.data) return;
    const { summary } = this.getActivePeriodBlock();

    const windows = [
      { key: '24h', label: '24 Hours' },
      { key: '7d', label: '7 Days' },
      { key: '30d', label: '30 Days' },
      { key: 'all', label: 'All Time' },
    ];

    const windowBtnsHtml = windows
      .map(
        (w) => `
        <button type="button" class="filter-pill ${w.key === this.activeWindow ? 'active' : ''}" data-window="${w.key}">
          ${escapeHtml(w.label)}
        </button>`
      )
      .join('');

    this.mountEl.innerHTML = `
      <!-- KPI Ribbon -->
      <div class="kpi-ribbon">
        <div class="kpi-card">
          <span class="kpi-label">${escapeHtml(this.activeWindow.toUpperCase())} Traded Volume</span>
          <span class="kpi-value text-buy">${formatCompact(summary.total_market_pp || 0)} PP</span>
          <span class="kpi-sub">${formatInt(summary.total_market_units || 0)} units traded</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">${escapeHtml(this.activeWindow.toUpperCase())} Market Turnover</span>
          <span class="kpi-value text-btc">${formatCompact(summary.total_market_money || 0)} ₿</span>
          <span class="kpi-sub">${formatMoney(summary.total_market_money || 0)} ₿ exchanged</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">${escapeHtml(this.activeWindow.toUpperCase())} Trades Executed</span>
          <span class="kpi-value text-pp">${formatInt(summary.total_market_tx || 0)}</span>
          <span class="kpi-sub">Completed transactions</span>
        </div>
      </div>

      <!-- Time Window Toolbar -->
      <div class="section-toolbar">
        <div class="filter-pills">
          <span class="text-muted mono" style="font-size:0.72rem;padding:0 6px">WINDOW:</span>
          ${windowBtnsHtml}
        </div>
      </div>

      <!-- Trades Commodity Table (4 lock-aligned columns on all screens) -->
      <div class="table-card">
        <table class="terminal-table">
          <thead>
            <tr>
              <th class="sortable ${this.sortField === 'name' ? 'sorted' : ''}" data-sort="name" style="width:28%;text-align:left">
                Product ${this.renderSortArrow('name')}
              </th>
              <th class="sortable ${this.sortField === 'total_pp' ? 'sorted' : ''}" data-sort="total_pp" style="width:24%;text-align:right">
                <span class="desktop-only">Traded Volume</span>
                <span class="mobile-only">Volume</span>
                ${this.renderSortArrow('total_pp')}
              </th>
              <th class="sortable ${this.sortField === 'total_money' ? 'sorted' : ''}" data-sort="total_money" style="width:25%;text-align:right">
                Turnover (₿) ${this.renderSortArrow('total_money')}
              </th>
              <th class="sortable ${this.sortField === 'vwap' ? 'sorted' : ''}" data-sort="vwap" style="width:23%;text-align:right">
                VWAP (₿) ${this.renderSortArrow('vwap')}
              </th>
            </tr>
          </thead>
          <tbody data-role="tbody"></tbody>
        </table>
      </div>

      <div id="trades-history-mount">
        <div class="skeleton-loader">Scroll to load Market Transactions History Chart...</div>
      </div>
    `;

    this.renderTableRows();
    this.bindEvents();
    this.setupLazyChart();
  }

  renderSortArrow(field) {
    if (this.sortField !== field) return '';
    return `<span class="sort-arrow">${this.sortDesc ? '↓' : '↑'}</span>`;
  }

  renderTableRows() {
    const tbody = this.mountEl.querySelector('[data-role="tbody"]');
    if (!tbody) return;

    const { items } = this.getActivePeriodBlock();

    const codes = Object.keys(items).sort((a, b) => {
      const itA = items[a];
      const itB = items[b];
      let cmp = 0;
      if (this.sortField === 'name') {
        cmp = store.getItemMeta(a).name.localeCompare(store.getItemMeta(b).name);
      } else if (this.sortField === 'total_pp') {
        const valA = Number(itA.total_pp) || Number(itA.total_units) || 0;
        const valB = Number(itB.total_pp) || Number(itB.total_units) || 0;
        cmp = valA - valB;
      } else {
        cmp = (Number(itA[this.sortField]) || 0) - (Number(itB[this.sortField]) || 0);
      }
      return this.sortDesc ? -cmp : cmp;
    });

    if (!codes.length) {
      tbody.innerHTML = `
        <tr>
          <td colspan="4" class="text-center text-muted" style="padding:28px">
            No trade data available.
          </td>
        </tr>
      `;
      return;
    }

    const rowsHtml = [];
    for (const code of codes) {
      const it = items[code];
      const meta = store.getItemMeta(code);
      const isExpanded = this.expandedItems.has(code);

      const volPrimary =
        meta.pp > 0
          ? `${formatCompact(it.total_pp)} PP`
          : `${formatCompact(it.total_units)} pcs`;
      const volSub =
        meta.pp > 1
          ? `${formatInt(it.total_units)} pcs`
          : '';

      rowsHtml.push(`
        <tr class="item-row ${isExpanded ? 'expanded' : ''}" data-trade-row="${escapeHtml(code)}">
          <td>
            <div class="product-cell">
              <span class="expand-caret">▶</span>
              <img src="assets/${escapeHtml(code)}.webp" alt="" class="item-icon" loading="lazy" />
              <div class="item-title-group">
                <div class="item-name-line">
                  ${renderItemName(meta)}
                </div>
              </div>
            </div>
          </td>
          <td class="text-right">
            <span class="metric-primary text-buy">${escapeHtml(volPrimary)}</span>
            ${volSub ? `<span class="metric-sub">${escapeHtml(volSub)}</span>` : ''}
          </td>
          <td class="text-right">
            <span class="metric-primary text-btc">${formatCompact(it.total_money)} ₿</span>
            <span class="metric-sub">${formatInt(it.tx_count)} trades</span>
          </td>
          <td class="text-right">
            <span class="metric-primary text-pp">${formatPrice(it.vwap)} ₿</span>
            <span class="metric-sub">POC: ${formatPrice(it.poc_price)} ₿</span>
          </td>
        </tr>
      `);

      if (isExpanded) {
        rowsHtml.push(this.renderExpandedTradeDrawer(code, it, meta));
      }
    }

    tbody.innerHTML = rowsHtml.join('');

    tbody.querySelectorAll('[data-trade-row]').forEach((row) => {
      row.addEventListener('click', () => {
        const code = row.dataset.tradeRow;
        if (this.expandedItems.has(code)) {
          this.expandedItems.delete(code);
        } else {
          this.expandedItems.add(code);
        }
        this.renderTableRows();
      });
    });

    tbody.querySelectorAll('[data-toggle-profile]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const code = btn.dataset.toggleProfile;
        if (this.showFullProfile.has(code)) {
          this.showFullProfile.delete(code);
        } else {
          this.showFullProfile.add(code);
        }
        this.renderTableRows();
      });
    });
  }

  renderExpandedTradeDrawer(code, it, meta) {
    const sparkMap = (this.data && this.data.sparklines_7d) || {};
    const spark = sparkMap[code] || {};
    const periodSpark =
      Array.isArray(it.sparkline_vwap) && it.sparkline_vwap.length >= 2
        ? it.sparkline_vwap
        : spark.vwap || [];
    const sparkSvg = renderSparklineSvg({
      seriesA: periodSpark,
      colorA: '#38bdf8',
    });

    const topBuyers = it.top_buyers || [];
    const topSellers = it.top_sellers || [];
    const profile = it.price_profile || [];
    const recentTrades =
      it.recent_trades ||
      (this.data.items && this.data.items[code] && this.data.items[code].recent_trades) ||
      [];

    const renderParticipantList = (list, isBuyer) => {
      if (!list.length) {
        return `<div class="text-muted" style="font-size:0.75rem">No trades recorded.</div>`;
      }
      return list
        .map((p, idx) => {
          const tiers = (p.orders || [])
            .map(
              (o) =>
                `<span class="order-lot-pill">${formatCompact(o.quantity ?? o.q)} @ ${formatPrice(o.price ?? o.p)} ₿</span>`
            )
            .join('');
          const participantVol =
            meta.pp > 1
              ? `${formatInt(p.units * meta.pp)} PP (${formatInt(p.units)} pcs)`
              : meta.pp === 1
              ? `${formatInt(p.units)} PP`
              : `${formatInt(p.units)} pcs`;
          return `
            <div class="top3-mini-card">
              <div class="top3-mini-main">
                <div style="display:flex;align-items:center;gap:6px;min-width:0">
                  <span class="pp-badge">#${idx + 1}</span>
                  ${renderEntityInline(p, true)}
                </div>
                <div class="mono" style="font-size:0.75rem;flex-shrink:0">
                  <span class="${isBuyer ? 'text-buy' : 'text-btc'}">${formatMoney(p.money)} ₿</span>
                  <span class="text-muted">(${formatPct(p.share_pct, 1)})</span>
                </div>
              </div>
              <div class="text-muted mono" style="font-size:0.7rem">
                ${participantVol}
                ${tiers ? '• Executed tiers:' : ''}
              </div>
              ${tiers ? `<div class="order-pills-row">${tiers}</div>` : ''}
            </div>
          `;
        })
        .join('');
    };

    const PROFILE_COMPACT_LIMIT = 12;
    const isFullProf = this.showFullProfile.has(code);
    let visibleProfile = profile;
    if (!isFullProf && profile.length > PROFILE_COMPACT_LIMIT) {
      const topByVol = [...profile]
        .sort((a, b) => (Number(b.units) || 0) - (Number(a.units) || 0))
        .slice(0, PROFILE_COMPACT_LIMIT);
      visibleProfile = topByVol.sort((a, b) => (Number(a.price) || 0) - (Number(b.price) || 0));
    }

    const maxShare = Math.max(1, ...profile.map((r) => Number(r.share_pct) || 0));
    const profileRowsHtml = visibleProfile
      .map((lvl) => {
        const isPoc =
          it.poc_price > 0 && Math.abs(lvl.price - it.poc_price) < 0.0005;
        const barW = Math.min(100, Math.max(2, Math.round((lvl.share_pct / maxShare) * 100)));
        return `
          <tr class="ladder-row">
            <td class="text-pp" style="font-weight:600">
              ${formatPrice(lvl.price)} ₿
              ${isPoc ? `<span class="poc-badge" title="Point of Control — Highest Traded Volume Level">★ POC</span>` : ''}
            </td>
            <td class="text-right">${formatInt(lvl.units)}</td>
            <td class="text-right text-btc">${formatMoney(lvl.money)} ₿</td>
            <td class="text-right dom-fill-cell">
              <div class="dom-fill-bar ${isPoc ? 'sell-bar' : 'buy-bar'}" style="width:${barW}%;background:${isPoc ? 'rgba(245,158,11,0.22)' : 'rgba(56,189,248,0.14)'}"></div>
              <span style="position:relative;z-index:2">${formatPct(lvl.share_pct, 1)}</span>
            </td>
          </tr>
        `;
      })
      .join('');

    const profileExpandBtnHtml =
      profile.length > PROFILE_COMPACT_LIMIT
        ? `
          <button
            type="button"
            class="ladder-expand-btn"
            data-toggle-profile="${escapeHtml(code)}"
          >
            ${
              isFullProf
                ? `▲ Collapse to Top ${PROFILE_COMPACT_LIMIT} price tiers`
                : `▼ Show all ${profile.length} price tiers (+${profile.length - visibleProfile.length} more)`
            }
          </button>
        `
        : '';

    const recentHtml = recentTrades.length
      ? `
        <div class="orderbook-column" style="margin-top:4px">
          <div class="ob-col-header">
            <span class="ob-col-title text-secondary">Recent Executed Transactions</span>
            <span class="ob-col-summary">Latest ${recentTrades.length} fills</span>
          </div>
          <table class="ladder-table">
            <thead>
              <tr>
                <th style="text-align:left">Time</th>
                <th style="text-align:right">Price</th>
                <th style="text-align:right">Qty</th>
                <th style="text-align:right">Total (₿)</th>
              </tr>
            </thead>
            <tbody>
              ${recentTrades
                .slice(0, 10)
                .map(
                  (tx) => `
                  <tr class="ladder-row">
                    <td class="text-muted">${escapeHtml(formatIsoShort(tx.time))}</td>
                    <td class="text-right text-pp">${formatPrice(tx.price)} ₿</td>
                    <td class="text-right">${formatInt(tx.quantity)}</td>
                    <td class="text-right text-btc">${formatMoney(tx.money)} ₿</td>
                  </tr>`
                )
                .join('')}
            </tbody>
          </table>
        </div>
      `
      : '';

    return `
      <tr class="drawer-row">
        <td colspan="4">
          <div class="drawer-container">
            <div class="drawer-top-strip">
              <div class="drawer-meta-info">
                <div class="drawer-meta-title">
                  <span>${escapeHtml(meta.name)} — ${escapeHtml(this.activeWindow.toUpperCase())} Trade Breakdown</span>
                  <span class="pp-badge">VWAP: ${formatPrice(it.vwap)} ₿</span>
                  <span class="pp-badge">POC: ${formatPrice(it.poc_price)} ₿</span>
                </div>
                <div class="drawer-meta-subtitle">
                  Range: ${formatPrice(it.min_price)} – ${formatPrice(it.max_price)} ₿ •
                  Volume: ${
                    meta.pp > 1
                      ? `${formatInt(it.total_pp)} PP (${formatInt(it.total_units)} pcs)`
                      : meta.pp === 1
                      ? `${formatInt(it.total_pp)} PP`
                      : `${formatInt(it.total_units)} pcs`
                  } •
                  Turnover: ${formatMoney(it.total_money)} ₿ across ${formatInt(it.tx_count)} trades
                </div>
              </div>

              <div class="sparkline-box" title="${escapeHtml(this.activeWindow.toUpperCase())} VWAP Price Trend">
                <div class="sparkline-labels">
                  <span class="text-pp">${escapeHtml(this.activeWindow.toUpperCase())} VWAP: ${formatPrice(it.vwap)} ₿</span>
                  <span class="text-btc">POC: ${formatPrice(it.poc_price)} ₿</span>
                </div>
                <div class="sparkline-canvas-wrap">
                  ${sparkSvg}
                </div>
              </div>
            </div>

            <!-- Top 3 Buyers & Top 3 Sellers -->
            <div class="orderbook-dual-grid">
              <div class="orderbook-column buy-col">
                <div class="ob-col-header">
                  <span class="ob-col-title text-buy">🟢 Top 3 Buyers</span>
                </div>
                <div class="top3-strip">
                  ${renderParticipantList(topBuyers, true)}
                </div>
              </div>

              <div class="orderbook-column sell-col">
                <div class="ob-col-header">
                  <span class="ob-col-title text-sell">🔴 Top 3 Sellers</span>
                </div>
                <div class="top3-strip">
                  ${renderParticipantList(topSellers, false)}
                </div>
              </div>
            </div>

            <!-- Volume Profile (Price Distribution & POC) -->
            <div class="orderbook-column">
              <div class="ob-col-header">
                <span class="ob-col-title text-secondary">Volume Profile</span>
                <span class="ob-col-summary">POC: <strong class="text-btc">${formatPrice(it.poc_price)} ₿</strong></span>
              </div>
              <table class="ladder-table">
                <thead>
                  <tr>
                    <th style="text-align:left">Price (₿)</th>
                    <th style="text-align:right">Volume</th>
                    <th style="text-align:right">Turnover (₿)</th>
                    <th style="text-align:right">Share %</th>
                  </tr>
                </thead>
                <tbody>
                  ${
                    profileRowsHtml ||
                    `<tr><td colspan="4" class="text-center text-muted" style="padding:14px">No volume profile data</td></tr>`
                  }
                </tbody>
              </table>
              ${profileExpandBtnHtml}
            </div>

            ${recentHtml}
          </div>
        </td>
      </tr>
    `;
  }

  bindEvents() {
    this.mountEl.querySelectorAll('[data-window]').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.activeWindow = btn.dataset.window;
        this.render();
      });
    });

    this.mountEl.querySelectorAll('th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const field = th.dataset.sort;
        if (this.sortField === field) {
          this.sortDesc = !this.sortDesc;
        } else {
          this.sortField = field;
          this.sortDesc = field !== 'name';
        }
        this.render();
      });
    });
  }

  setupLazyChart() {
    const chartMount = this.mountEl.querySelector('#trades-history-mount');
    if (!chartMount) return;

    observeOnce(chartMount, async () => {
      try {
        const histData = await store.fetchSlice('trades_history.json');
        this.chartWidget = new HistoryChartWidget({
          mountEl: chartMount,
          title: 'Market Transactions History',
          metrics: [
            { key: 'hourly_pp', label: 'Volume (PP)' },
            { key: 'hourly_money', label: 'Turnover (₿)' },
            { key: 'hourly_vwap', label: 'VWAP (₿)' },
            { key: 'hourly_tx', label: 'Trades Count' },
          ],
          defaultMetric: 'hourly_pp',
          includeCases: true,
          yFormatter: (v) => formatCompact(v),
        });
        this.chartWidget.setData(histData);
      } catch (err) {
        chartMount.innerHTML = `<div class="skeleton-loader">Failed to load trades history: ${escapeHtml(err.message)}</div>`;
      }
    });
  }
}
