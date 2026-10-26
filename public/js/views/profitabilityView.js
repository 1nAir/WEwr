import { store } from '../store.js';
import { formatPrice, formatPPPrice, escapeHtml, renderItemName } from '../utils/format.js';
import { observeOnce } from '../utils/dom.js';
import { renderSparklineSvg } from '../components/sparkline.js';
import { HistoryChartWidget } from '../components/historyChart.js';

/**
 * View Module: Section 1 — Profitability (Dry 1 PP Production Calculation).
 */
export class ProfitabilityView {
  constructor(mountEl) {
    this.mountEl = mountEl;
    this.data = null;
    this.sortField = 'min_pp'; // 'min_pp' | 'max_pp'
    this.sortDesc = true;
    this.expandedItems = new Set();
    this.chartWidget = null;
  }

  async init(forceRefresh = false) {
    await store.ensureMeta(forceRefresh);
    this.data = await store.fetchSlice('profitability.json', forceRefresh);
    this.render();
  }

  render() {
    if (!this.mountEl || !this.data) return;

    this.mountEl.innerHTML = `
      <div class="table-card">
        <table class="terminal-table">
          <thead>
            <tr>
              <th style="width:30%;text-align:left">
                Product
              </th>
              <th style="width:28%;text-align:right">
                <span class="desktop-only">Bid / Ask (₿)</span>
                <span class="mobile-only">Bid / Ask</span>
              </th>
              <th class="sortable ${this.sortField === 'min_pp' ? 'sorted' : ''}" data-sort="min_pp" style="width:21%;text-align:right">
                Min ₿/PP ${this.renderSortArrow('min_pp')}
              </th>
              <th class="sortable ${this.sortField === 'max_pp' ? 'sorted' : ''}" data-sort="max_pp" style="width:21%;text-align:right">
                Max ₿/PP ${this.renderSortArrow('max_pp')}
              </th>
            </tr>
          </thead>
          <tbody data-role="tbody"></tbody>
        </table>
      </div>

      <div id="profitability-history-mount">
        <div class="skeleton-loader">Scroll to load Profitability History Chart...</div>
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

  getSortedCodes() {
    const itemsMap = (this.data && this.data.items) || {};

    return Object.keys(itemsMap).sort((a, b) => {
      const itemA = itemsMap[a];
      const itemB = itemsMap[b];
      const cmp = (Number(itemA[this.sortField]) || 0) - (Number(itemB[this.sortField]) || 0);
      return this.sortDesc ? -cmp : cmp;
    });
  }

  renderTableRows() {
    const tbody = this.mountEl.querySelector('[data-role="tbody"]');
    if (!tbody) return;

    const itemsMap = this.data.items || {};
    const codes = this.getSortedCodes();

    if (!codes.length) {
      tbody.innerHTML = `
        <tr>
          <td colspan="4" class="text-center text-muted" style="padding:28px">
            No items available.
          </td>
        </tr>
      `;
      return;
    }

    const rowsHtml = [];
    for (const code of codes) {
      const it = itemsMap[code];
      const meta = store.getItemMeta(code);
      const isExpanded = this.expandedItems.has(code);

      const minPPClass = it.min_pp >= 0 ? 'text-pp' : 'text-sell';
      const maxPPClass = it.max_pp >= 0 ? 'text-buy' : 'text-sell';

      rowsHtml.push(`
        <tr class="item-row ${isExpanded ? 'expanded' : ''}" data-item-row="${escapeHtml(code)}">
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
            <div class="bid-ask-inline mono">
              <span class="text-buy" title="Top-3 Buy Order Avg (Bid)">${formatPrice(it.bid)}</span>
              <span class="text-muted">/</span>
              <span class="text-sell" title="Top-3 Sell Order Avg (Ask)">${formatPrice(it.ask)}</span>
            </div>
          </td>
          <td class="text-right">
            <span class="metric-primary ${minPPClass}">${formatPPPrice(it.min_pp)}</span>
          </td>
          <td class="text-right">
            <span class="metric-primary ${maxPPClass}">${formatPPPrice(it.max_pp)}</span>
          </td>
        </tr>
      `);

      if (isExpanded) {
        rowsHtml.push(this.renderExpandedDrawer(code, it, meta));
      }
    }

    tbody.innerHTML = rowsHtml.join('');

    tbody.querySelectorAll('[data-item-row]').forEach((row) => {
      row.addEventListener('click', () => {
        const code = row.dataset.itemRow;
        if (this.expandedItems.has(code)) {
          this.expandedItems.delete(code);
        } else {
          this.expandedItems.add(code);
        }
        this.renderTableRows();
      });
    });
  }

  renderExpandedDrawer(code, it, meta) {
    const spark = it.sparkline_7d || {};
    const sparkSvg = renderSparklineSvg({
      seriesA: spark.min_pp || [],
      seriesB: spark.max_pp || [],
      colorA: '#38bdf8',
      colorB: '#10b981',
    });

    const ingredientsMinHtml =
      it.ingredients && it.ingredients.length
        ? it.ingredients
            .map(
              (ing) => `
              <div class="formula-line sub-ingredient">
                <span>− ${ing.qty} × ${escapeHtml(ing.name)} <span class="text-muted mono">(@ ${formatPrice(ing.ask_price)} ₿ Top-3 Sell)</span></span>
                <span class="mono text-sell">−${formatPrice(ing.cost_min_scenario)} ₿</span>
              </div>`
            )
            .join('')
        : `<div class="formula-line sub-ingredient"><span class="text-muted">No raw ingredients required (Base Resource)</span><span class="mono">0.000 ₿</span></div>`;

    const ingredientsMaxHtml =
      it.ingredients && it.ingredients.length
        ? it.ingredients
            .map(
              (ing) => `
              <div class="formula-line sub-ingredient">
                <span>− ${ing.qty} × ${escapeHtml(ing.name)} <span class="text-muted mono">(@ ${formatPrice(ing.bid_price)} ₿ Top-3 Buy)</span></span>
                <span class="mono text-sell">−${formatPrice(ing.cost_max_scenario)} ₿</span>
              </div>`
            )
            .join('')
        : `<div class="formula-line sub-ingredient"><span class="text-muted">No raw ingredients required (Base Resource)</span><span class="mono">0.000 ₿</span></div>`;

    return `
      <tr class="drawer-row">
        <td colspan="4">
          <div class="drawer-container">
            <div class="drawer-top-strip">
              <div class="drawer-meta-info">
                <div class="drawer-meta-title">
                  <span>${escapeHtml(meta.name)}</span>
                </div>
                <div class="drawer-meta-subtitle">
                  Buy Orders (Bid): <span class="text-buy">${formatPrice(it.bid)} ₿</span> •
                  Sell Orders (Ask): <span class="text-sell">${formatPrice(it.ask)} ₿</span> •
                  Avg: ${formatPrice(it.avg)} ₿
                </div>
              </div>

              <div class="sparkline-box" title="7-Day Profitability Trend (Solid: Min ₿/PP, Dashed: Max ₿/PP)">
                <div class="sparkline-labels">
                  <span class="text-pp">7D Min: ${formatPPPrice(it.min_pp)}</span>
                  <span class="text-buy">7D Max: ${formatPPPrice(it.max_pp)}</span>
                </div>
                <div class="sparkline-canvas-wrap">
                  ${sparkSvg}
                </div>
              </div>
            </div>

            <div class="recipe-grid">
              <!-- Min ₿/PP Card -->
              <div class="recipe-card conservative">
                <div class="recipe-card-header">
                  <span class="recipe-card-title text-pp">Min ₿/PP</span>
                  <span class="recipe-card-badge">Fast Trade (Sell to Buyers • Buy from Sellers)</span>
                </div>
                <div class="formula-line">
                  <span>Sell 1× ${escapeHtml(meta.name)} <span class="text-muted mono">(Top-3 Buy)</span></span>
                  <span class="mono text-buy">+${formatPrice(it.bid)} ₿</span>
                </div>
                ${ingredientsMinHtml}
                <div class="formula-line total-line">
                  <span>Net Profit per 1 Unit</span>
                  <span class="mono ${it.min_net_profit >= 0 ? 'text-buy' : 'text-sell'}">
                    ${it.min_net_profit >= 0 ? '+' : ''}${formatPrice(it.min_net_profit)} ₿
                  </span>
                </div>
                <div class="formula-result-banner">
                  <span class="text-secondary">${formatPrice(it.min_net_profit)} ₿ ÷ ${it.pp} PP</span>
                  <strong class="text-pp">${formatPPPrice(it.min_pp)} ₿/PP</strong>
                </div>
              </div>

              <!-- Max ₿/PP Card -->
              <div class="recipe-card optimistic">
                <div class="recipe-card-header">
                  <span class="recipe-card-title text-buy">Max ₿/PP</span>
                  <span class="recipe-card-badge">Own Orders (Place Sell Order • Buy via Buy Orders)</span>
                </div>
                <div class="formula-line">
                  <span>Sell 1× ${escapeHtml(meta.name)} <span class="text-muted mono">(Top-3 Sell)</span></span>
                  <span class="mono text-buy">+${formatPrice(it.ask)} ₿</span>
                </div>
                ${ingredientsMaxHtml}
                <div class="formula-line total-line">
                  <span>Net Profit per 1 Unit</span>
                  <span class="mono ${it.max_net_profit >= 0 ? 'text-buy' : 'text-sell'}">
                    ${it.max_net_profit >= 0 ? '+' : ''}${formatPrice(it.max_net_profit)} ₿
                  </span>
                </div>
                <div class="formula-result-banner">
                  <span class="text-secondary">${formatPrice(it.max_net_profit)} ₿ ÷ ${it.pp} PP</span>
                  <strong class="text-buy">${formatPPPrice(it.max_pp)} ₿/PP</strong>
                </div>
              </div>
            </div>
          </div>
        </td>
      </tr>
    `;
  }

  bindEvents() {
    this.mountEl.querySelectorAll('th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const field = th.dataset.sort;
        if (this.sortField === field) {
          this.sortDesc = !this.sortDesc;
        } else {
          this.sortField = field;
          this.sortDesc = true;
        }
        this.render();
      });
    });
  }

  setupLazyChart() {
    const chartMount = this.mountEl.querySelector('#profitability-history-mount');
    if (!chartMount) return;

    observeOnce(chartMount, async () => {
      try {
        const histData = await store.fetchSlice('profitability_history.json');
        this.chartWidget = new HistoryChartWidget({
          mountEl: chartMount,
          title: 'Profitability History',
          metrics: [
            { key: 'min_pp', label: 'Min ₿/PP' },
            { key: 'max_pp', label: 'Max ₿/PP' },
          ],
          defaultMetric: 'min_pp',
          includeCases: false,
          yFormatter: (v) => `${Number(v).toFixed(3)} ₿`,
        });
        this.chartWidget.setData(histData);
      } catch (err) {
        chartMount.innerHTML = `<div class="skeleton-loader">Failed to load history chart: ${escapeHtml(err.message)}</div>`;
      }
    });
  }
}
