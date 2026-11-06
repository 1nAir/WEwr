import { store } from '../store.js';
import {
  formatInt,
  formatMoney,
  formatCompact,
  formatPct,
  escapeHtml,
  renderItemName,
} from '../utils/format.js';
import { observeOnce } from '../utils/dom.js';
import { renderSparklineSvg } from '../components/sparkline.js';
import { HistoryChartWidget } from '../components/historyChart.js';

const COUNTRY_PALETTE = [
  '#38bdf8', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#f97316',
  '#22d3ee', '#84cc16', '#f43f5e', '#6366f1', '#14b8a6', '#eab308',
  '#a855f7', '#fb7185', '#60a5fa', '#34d399', '#fbbf24', '#c084fc',
  '#4ade80', '#f87171', '#2dd4bf', '#a3e635', '#fb923c', '#94a3b8',
];

/**
 * View Module: Section 3 — Companies (Global Level 15+ Production, Wages & Country/Regional Taxes).
 * Divided into 2 Subtabs:
 *   1. By Items (По предметам)
 *   2. By Countries (По странам + выдвижной блок по регионам)
 */
export class CompaniesView {
  constructor(mountEl) {
    this.mountEl = mountEl;
    this.data = null;
    this.historyData = null;
    this.subtab = 'items'; // 'items' | 'countries'
    this.countrySearchQuery = '';

    // Sorting state per subtab
    this.itemSortField = 'pp_hr'; // 'name' | 'companies' | 'pp_hr' | 'wages_hr'
    this.itemSortDesc = true;

    this.countrySortField = 'pp_hr'; // 'name' | 'companies' | 'pp_hr' | 'tax_total_hr'
    this.countrySortDesc = true;

    this.expandedItems = new Set();
    this.expandedCountries = new Set();
    this.chartWidget = null;
  }

  async init(forceRefresh = false, initialSubtab = null) {
    if (initialSubtab && ['items', 'countries'].includes(initialSubtab)) {
      this.subtab = initialSubtab;
    }
    await store.ensureMeta(forceRefresh);
    this.data = await store.fetchSlice('companies.json', forceRefresh);
    if (forceRefresh) {
      this.historyData = null;
    }
    this.render();
  }

  setSubtab(subtab) {
    if (!['items', 'countries'].includes(subtab)) return;
    this.subtab = subtab;
    if (this.data) {
      this.render();
    }
  }

  renderSortArrow(currentField, targetField, isDesc) {
    if (currentField !== targetField) return '';
    return `<span class="sort-arrow">${isDesc ? '↓' : '↑'}</span>`;
  }

  renderDeltaBadge(val, isPct = true) {
    const n = Number(val) || 0;
    if (Math.abs(n) < 0.05) return '';
    const cls = n > 0 ? 'text-buy' : 'text-sell';
    const sign = n > 0 ? '+' : '';
    const formatted = isPct ? `${sign}${n.toFixed(1)}%` : `${sign}${formatInt(n)}`;
    return `<span class="comp-delta-pill mono ${cls}">${formatted}</span>`;
  }

  render() {
    if (!this.mountEl || !this.data) return;

    const summary = this.data.summary || {};
    const taxInc = summary.global_tax_income || {};
    const itemsCount = Object.keys(this.data.by_items || {}).length;
    const countriesCount = Object.keys(this.data.by_countries || {}).length;

    const empPlusMgrTax =
      (Number(taxInc.employee_tax) || 0) + (Number(taxInc.manager_tax) || 0);

    const searchHtml =
      this.subtab === 'countries'
        ? `
        <div class="toolbar-right">
          <div class="search-box">
            <svg class="search-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="8.5" cy="8.5" r="5.5" />
              <path d="M13 13l4 4" stroke-linecap="round" />
            </svg>
            <input
              type="search"
              class="search-input"
              data-role="comp-country-search"
              placeholder="Search country or region..."
              value="${escapeHtml(this.countrySearchQuery)}"
            />
          </div>
        </div>`
        : '';

    this.mountEl.innerHTML = `
      <!-- Sub-Navigation Bar (By Items / By Countries) -->
      <div class="market-subnav-bar comp-subnav-bar">
        <div class="market-subnav-pills" role="tablist">
          <button type="button" class="subnav-pill ${this.subtab === 'items' ? 'active' : ''}" data-comp-subtab="items">
            <span class="pill-indicator pp"></span>
            <span>By Items</span>
            <span class="pill-badge">${itemsCount}</span>
          </button>
          <button type="button" class="subnav-pill ${this.subtab === 'countries' ? 'active' : ''}" data-comp-subtab="countries">
            <span class="pill-indicator btc"></span>
            <span>By Countries</span>
            <span class="pill-badge">${countriesCount}</span>
          </button>
        </div>
        ${searchHtml}
      </div>

      <!-- Global KPI Summary Ribbon -->
      <div class="kpi-ribbon comp-kpi-ribbon">
        <div class="kpi-card">
          <div class="kpi-label">Active Companies (15+ Lvl)</div>
          <div class="kpi-value mono">
            ${formatInt(summary.total_companies)}
            ${this.renderDeltaBadge(summary.delta_companies, false)}
          </div>
          <div class="kpi-sub mono">
            Players 15+ Lvl: ${formatInt(summary.eligible_players)}
          </div>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">Global Output (PP/hr)</div>
          <div class="kpi-value mono text-pp">
            ${formatCompact(summary.total_pp_hr)} PP/h
            ${this.renderDeltaBadge(summary.delta_pp_pct, true)}
          </div>
          <div class="kpi-sub mono">
            ${formatCompact(summary.total_pp_24h)} PP / 24h
          </div>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">Total Wages (Emp + Mgr)</div>
          <div class="kpi-value mono text-btc">
            ${formatMoney(summary.total_wages_hr, 2)} ₿/h
          </div>
          <div class="kpi-sub mono">
            ${formatCompact(summary.total_wages_24h)} ₿ / 24h
          </div>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">Global State Revenue</div>
          <div class="kpi-value mono text-buy">
            +${formatMoney(taxInc.total, 2)} ₿/h
          </div>
          <div class="kpi-sub mono">
            Tax: ${formatMoney(empPlusMgrTax, 2)} • Dev: ${formatMoney(taxInc.development, 2)} ₿/h
          </div>
        </div>
      </div>

      <!-- Main Data Table Card -->
      <div class="table-card" data-role="table-wrap">
        ${this.subtab === 'items' ? this.renderItemsTableShell() : this.renderCountriesTableShell()}
      </div>

      <!-- Historical Trends Chart -->
      <div id="companies-history-mount">
        <div class="skeleton-loader">Scroll to load Companies Historical Chart...</div>
      </div>
    `;

    this.renderActiveTableRows();
    this.bindEvents();
    this.setupLazyChart();
  }

  renderItemsTableShell() {
    const sf = this.itemSortField;
    const sd = this.itemSortDesc;
    return `
      <table class="terminal-table">
        <thead>
          <tr>
            <th class="sortable ${sf === 'name' ? 'sorted' : ''}" data-sort-item="name" style="width:30%;text-align:left">
              Product ${this.renderSortArrow(sf, 'name', sd)}
            </th>
            <th class="sortable ${sf === 'companies' ? 'sorted' : ''}" data-sort-item="companies" style="width:22%;text-align:right">
              Companies ${this.renderSortArrow(sf, 'companies', sd)}
            </th>
            <th class="sortable ${sf === 'pp_hr' ? 'sorted' : ''}" data-sort-item="pp_hr" style="width:25%;text-align:right">
              <span class="desktop-only">Output (PP/hr)</span>
              <span class="mobile-only">PP/hr</span>
              ${this.renderSortArrow(sf, 'pp_hr', sd)}
            </th>
            <th class="sortable ${sf === 'wages_hr' ? 'sorted' : ''}" data-sort-item="wages_hr" style="width:23%;text-align:right">
              <span class="desktop-only">Wages / Output</span>
              <span class="mobile-only">Wages (₿/h)</span>
              ${this.renderSortArrow(sf, 'wages_hr', sd)}
            </th>
          </tr>
        </thead>
        <tbody data-role="tbody"></tbody>
      </table>
    `;
  }

  renderCountriesTableShell() {
    const sf = this.countrySortField;
    const sd = this.countrySortDesc;
    return `
      <table class="terminal-table">
        <thead>
          <tr>
            <th class="sortable ${sf === 'name' ? 'sorted' : ''}" data-sort-country="name" style="width:31%;text-align:left">
              Country &amp; Tax ${this.renderSortArrow(sf, 'name', sd)}
            </th>
            <th class="sortable ${sf === 'companies' ? 'sorted' : ''}" data-sort-country="companies" style="width:21%;text-align:right">
              Companies ${this.renderSortArrow(sf, 'companies', sd)}
            </th>
            <th class="sortable ${sf === 'pp_hr' ? 'sorted' : ''}" data-sort-country="pp_hr" style="width:24%;text-align:right">
              <span class="desktop-only">Output (PP/hr)</span>
              <span class="mobile-only">PP/hr</span>
              ${this.renderSortArrow(sf, 'pp_hr', sd)}
            </th>
            <th class="sortable ${sf === 'tax_total_hr' ? 'sorted' : ''}" data-sort-country="tax_total_hr" style="width:24%;text-align:right">
              <span class="desktop-only">Treasury (₿/hr)</span>
              <span class="mobile-only">Treasury</span>
              ${this.renderSortArrow(sf, 'tax_total_hr', sd)}
            </th>
          </tr>
        </thead>
        <tbody data-role="tbody"></tbody>
      </table>
    `;
  }

  renderActiveTableRows() {
    if (this.subtab === 'items') {
      this.renderItemsRows();
    } else {
      this.renderCountriesRows();
    }
  }

  renderShareSubLine(pct, colorVar = 'var(--color-pp)') {
    const clamped = Math.max(0, Math.min(100, Number(pct) || 0));
    return `
      <div class="comp-share-sub">
        <div class="comp-share-bar-track">
          <div class="comp-share-bar-fill" style="width:${clamped}%;background:${colorVar}"></div>
        </div>
        <span class="comp-share-pct mono">${formatPct(pct, 1)}</span>
      </div>
    `;
  }

  // ===========================================================================
  // SUBTAB 1: BY ITEMS
  // ===========================================================================

  getSortedItemCodes() {
    const itemsMap = (this.data && this.data.by_items) || {};

    return Object.keys(itemsMap).sort((a, b) => {
      const itA = itemsMap[a];
      const itB = itemsMap[b];
      if (this.itemSortField === 'name') {
        const nameA = store.getItemMeta(a).name || a;
        const nameB = store.getItemMeta(b).name || b;
        const cmp = nameA.localeCompare(nameB);
        return this.itemSortDesc ? -cmp : cmp;
      }
      const valA = Number(itA[this.itemSortField]) || 0;
      const valB = Number(itB[this.itemSortField]) || 0;
      const cmp = valA - valB;
      return this.itemSortDesc ? -cmp : cmp;
    });
  }

  renderItemsRows() {
    const tbody = this.mountEl.querySelector('[data-role="tbody"]');
    if (!tbody) return;

    const itemsMap = this.data.by_items || {};
    const codes = this.getSortedItemCodes();

    if (!codes.length) {
      tbody.innerHTML = `
        <tr>
          <td colspan="4" class="text-center text-muted" style="padding:28px">
            No matching items found.
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

      rowsHtml.push(`
        <tr class="item-row ${isExpanded ? 'expanded' : ''}" data-comp-item-row="${escapeHtml(code)}">
          <td>
            <div class="product-cell">
              <span class="expand-caret">▶</span>
              <img src="assets/${escapeHtml(code)}.webp" alt="" class="item-icon" loading="lazy" />
              <div class="item-title-group">
                <div class="item-name-line">
                  ${renderItemName(meta)}
                </div>
                <div class="item-sub-line desktop-only">
                  <span>1 pcs = ${it.pp_per_unit} PP</span>
                </div>
              </div>
            </div>
          </td>
          <td class="text-right">
            <span class="metric-primary">${formatInt(it.companies)}</span>
            ${this.renderShareSubLine(it.companies_share_pct, 'var(--accent-primary)')}
          </td>
          <td class="text-right">
            <span class="metric-primary text-pp">${formatCompact(it.pp_hr)} <span class="desktop-only">PP/h</span></span>
            ${this.renderShareSubLine(it.pp_share_pct, 'var(--color-pp)')}
          </td>
          <td class="text-right">
            <span class="metric-primary text-btc">${formatMoney(it.wages_hr, 2)} ₿</span>
            <span class="metric-sub">${formatCompact(it.units_hr)} pcs/h</span>
          </td>
        </tr>
      `);

      if (isExpanded) {
        rowsHtml.push(this.renderItemDrawer(code, it, meta));
      }
    }

    tbody.innerHTML = rowsHtml.join('');

    tbody.querySelectorAll('[data-comp-item-row]').forEach((row) => {
      row.addEventListener('click', () => {
        const code = row.dataset.compItemRow;
        if (this.expandedItems.has(code)) {
          this.expandedItems.delete(code);
        } else {
          this.expandedItems.add(code);
        }
        this.renderItemsRows();
      });
    });

    this.bindIsolateChartButtons(tbody);
  }

  renderItemDrawer(code, it, meta) {
    const spark = it.sparkline_7d || {};
    const sparkSvg = renderSparklineSvg({
      seriesA: spark.pp_hr || [],
      seriesB: spark.wages_hr || [],
      colorA: '#38bdf8',
      colorB: '#f59e0b',
    });

    const mktPct = Number(it.market_vs_prod_pct) || 0;
    const mktColorClass =
      mktPct >= 80 ? 'text-buy' : mktPct >= 30 ? 'text-pp' : 'text-secondary';

    return `
      <tr class="drawer-row">
        <td colspan="4">
          <div class="drawer-container">
            <div class="drawer-top-strip">
              <div class="drawer-meta-info">
                <div class="drawer-meta-title">
                  <span>${escapeHtml(meta.name)}</span>
                  <span class="pp-badge">1 pcs = ${it.pp_per_unit} PP</span>
                  <button type="button" class="comp-isolate-btn" data-isolate-entity="${escapeHtml(code)}" title="Isolate ${escapeHtml(meta.name)} on History Chart">
                    📈 Chart
                  </button>
                </div>
                <div class="drawer-meta-subtitle">
                  Active Companies: <strong class="text-primary">${formatInt(it.companies)}</strong> (${formatPct(it.companies_share_pct, 2)} share) •
                  Output Share: <strong class="text-pp">${formatPct(it.pp_share_pct, 2)}</strong>
                </div>
              </div>

              <div class="sparkline-box" title="7-Day Trend (Solid Blue: Output PP/hr • Dashed Gold: Wages ₿/hr)">
                <div class="sparkline-labels">
                  <span class="text-pp">PP/h: ${formatCompact(it.pp_hr)}</span>
                  <span class="text-btc">Wages: ${formatMoney(it.wages_hr, 2)} ₿/h</span>
                </div>
                <div class="sparkline-canvas-wrap">
                  ${sparkSvg}
                </div>
              </div>
            </div>

            <div class="recipe-grid">
              <!-- Card 1: Production & Market Absorption (Supply vs Demand) -->
              <div class="recipe-card conservative">
                <div class="recipe-card-header">
                  <span class="recipe-card-title text-pp">Production &amp; Market Volume</span>
                  <span class="recipe-card-badge">Supply vs 24h Traded</span>
                </div>
                <div class="formula-line">
                  <span>Hourly Output (AE + Employees)</span>
                  <span class="mono text-pp">${formatInt(it.pp_hr)} PP/hr (${formatPct(it.pp_share_pct, 2)})</span>
                </div>
                <div class="formula-line sub-ingredient">
                  <span>Daily Output (24h PP)</span>
                  <span class="mono">${formatInt(it.pp_24h)} PP / 24h</span>
                </div>
                <div class="formula-line">
                  <span>Units Produced (1h / 24h)</span>
                  <span class="mono text-primary">${formatCompact(it.units_hr)} pcs/h • <strong>${formatInt(it.units_24h)} pcs/24h</strong></span>
                </div>
                <div class="formula-line sub-ingredient">
                  <span>24h Market Traded Volume</span>
                  <span class="mono text-btc">${formatInt(it.traded_units_24h)} pcs/24h (${formatCompact(it.traded_pp_24h)} PP)</span>
                </div>
                <div class="formula-result-banner">
                  <span class="text-secondary">Market Turnover vs 24h Production</span>
                  <strong class="${mktColorClass}">${formatPct(mktPct, 1)} Traded on Market</strong>
                </div>
              </div>

              <!-- Card 2: Workforce Payroll (Employees + Managers) -->
              <div class="recipe-card optimistic">
                <div class="recipe-card-header">
                  <span class="recipe-card-title text-btc">Workforce Payroll</span>
                  <span class="recipe-card-badge">Employees + Managers</span>
                </div>
                <div class="formula-line">
                  <span>Employee Wages (1h / 24h)</span>
                  <span class="mono">${formatMoney(it.emp_wages_hr, 3)} ₿/h • ${formatMoney(it.emp_wages_hr * 24, 2)} ₿/24h</span>
                </div>
                <div class="formula-line">
                  <span>Manager Wages (1h / 24h)</span>
                  <span class="mono">${formatMoney(it.mgr_wages_hr, 3)} ₿/h • ${formatMoney(it.mgr_wages_hr * 24, 2)} ₿/24h</span>
                </div>
                <div class="formula-line total-line">
                  <span>Total Hourly Payroll (Emp + Mgr)</span>
                  <span class="mono text-btc">${formatMoney(it.wages_hr, 3)} ₿/hr</span>
                </div>
                <div class="formula-result-banner">
                  <span class="text-secondary">Total Daily Payroll (24h)</span>
                  <strong class="text-btc">${formatMoney(it.wages_24h, 2)} ₿ / 24h</strong>
                </div>
              </div>
            </div>
          </div>
        </td>
      </tr>
    `;
  }

  // ===========================================================================
  // SUBTAB 2: BY COUNTRIES (+ REGIONAL BREAKDOWN DRAWER)
  // ===========================================================================

  getSortedCountryCodes() {
    const countriesMap = (this.data && this.data.by_countries) || {};
    const q = this.countrySearchQuery.trim().toLowerCase();

    return Object.keys(countriesMap)
      .filter((cKey) => {
        if (!q) return true;
        const c = countriesMap[cKey];
        if (
          cKey.toLowerCase().includes(q) ||
          (c.name && c.name.toLowerCase().includes(q))
        ) {
          return true;
        }
        const regs = c.regions || [];
        return regs.some(
          (r) =>
            (r.name && r.name.toLowerCase().includes(q)) ||
            (r.code && r.code.toLowerCase().includes(q))
        );
      })
      .sort((a, b) => {
        const cA = countriesMap[a];
        const cB = countriesMap[b];
        if (this.countrySortField === 'name') {
          const cmp = (cA.name || a).localeCompare(cB.name || b);
          return this.countrySortDesc ? -cmp : cmp;
        }
        if (this.countrySortField === 'tax_total_hr') {
          const incA = Number((cA.income || {}).total) || 0;
          const incB = Number((cB.income || {}).total) || 0;
          const cmp = incA - incB;
          return this.countrySortDesc ? -cmp : cmp;
        }
        const valA = Number(cA[this.countrySortField]) || 0;
        const valB = Number(cB[this.countrySortField]) || 0;
        const cmp = valA - valB;
        return this.countrySortDesc ? -cmp : cmp;
      });
  }

  renderCountriesRows() {
    const tbody = this.mountEl.querySelector('[data-role="tbody"]');
    if (!tbody) return;

    const countriesMap = this.data.by_countries || {};
    const cKeys = this.getSortedCountryCodes();

    if (!cKeys.length) {
      tbody.innerHTML = `
        <tr>
          <td colspan="4" class="text-center text-muted" style="padding:28px">
            No matching countries or regions found.
          </td>
        </tr>
      `;
      return;
    }

    const rowsHtml = [];
    for (const cKey of cKeys) {
      const c = countriesMap[cKey];
      const isExpanded = this.expandedCountries.has(cKey);
      const taxes = c.taxes || {};
      const inc = c.income || {};
      const badgeCode = String(c.code || cKey).slice(0, 3).toUpperCase();

      rowsHtml.push(`
        <tr class="item-row ${isExpanded ? 'expanded' : ''}" data-comp-country-row="${escapeHtml(cKey)}">
          <td>
            <div class="product-cell">
              <span class="expand-caret">▶</span>
              <span class="country-code-badge">${escapeHtml(badgeCode)}</span>
              <div class="item-title-group">
                <div class="item-name-line">
                  <span>${escapeHtml(c.name)}</span>
                  <span class="pp-badge desktop-only">${c.region_count || 0} reg</span>
                </div>
                <div class="item-sub-line">
                  <span class="desktop-only">Inc Tax: <strong class="text-secondary">${formatPct(taxes.income, 0)}</strong> • Mgr Tax: <strong class="text-secondary">${formatPct(taxes.manager, 0)}</strong></span>
                  <span class="mobile-only">Tax: ${formatPct(taxes.income, 0)} / ${formatPct(taxes.manager, 0)}</span>
                </div>
              </div>
            </div>
          </td>
          <td class="text-right">
            <span class="metric-primary">${formatInt(c.companies)}</span>
            ${this.renderShareSubLine(c.companies_share_pct, 'var(--accent-primary)')}
          </td>
          <td class="text-right">
            <span class="metric-primary text-pp">${formatCompact(c.pp_hr)} <span class="desktop-only">PP/h</span></span>
            ${this.renderShareSubLine(c.pp_share_pct, 'var(--color-pp)')}
          </td>
          <td class="text-right">
            <span class="metric-primary text-buy">+${formatMoney(inc.total, 2)} ₿</span>
            <span class="metric-sub desktop-only">Wages: ${formatMoney(c.wages_hr, 2)} ₿/h</span>
            <span class="metric-sub mobile-only">Tax: ${formatMoney((inc.employee_tax || 0) + (inc.manager_tax || 0), 2)} ₿</span>
          </td>
        </tr>
      `);

      if (isExpanded) {
        rowsHtml.push(this.renderCountryDrawer(cKey, c));
      }
    }

    tbody.innerHTML = rowsHtml.join('');

    tbody.querySelectorAll('[data-comp-country-row]').forEach((row) => {
      row.addEventListener('click', () => {
        const cKey = row.dataset.compCountryRow;
        if (this.expandedCountries.has(cKey)) {
          this.expandedCountries.delete(cKey);
        } else {
          this.expandedCountries.add(cKey);
        }
        this.renderCountriesRows();
      });
    });

    this.bindIsolateChartButtons(tbody);
  }

  renderCountryDrawer(cKey, c) {
    const taxes = c.taxes || {};
    const inc = c.income || {};
    const spark = c.sparkline_7d || {};
    const sparkSvg = renderSparklineSvg({
      seriesA: spark.pp_hr || [],
      seriesB: spark.tax_total_hr || [],
      colorA: '#38bdf8',
      colorB: '#10b981',
    });

    const regions = c.regions || [];
    const q = this.countrySearchQuery.trim().toLowerCase();

    const regionRowsHtml = regions.length
      ? regions
          .map((r) => {
            const rInc = r.income || {};
            const isMatched =
              q &&
              ((r.name && r.name.toLowerCase().includes(q)) ||
                (r.code && r.code.toLowerCase().includes(q)));
            return `
              <tr class="comp-region-row ${isMatched ? 'region-match-highlight' : ''}">
                <td>
                  <div class="comp-region-name">${escapeHtml(r.name)}</div>
                  <div class="comp-region-sub mono">
                    Wages: <span class="text-btc">${formatMoney(r.wages_hr, 3)} ₿/h</span>
                    <span class="desktop-only">(${formatMoney(r.wages_24h, 2)} ₿/24h)</span>
                  </div>
                </td>
                <td class="text-right">
                  <span class="mono font-semibold">${formatInt(r.companies)}</span>
                  ${this.renderShareSubLine(r.companies_country_share_pct, 'var(--accent-primary)')}
                </td>
                <td class="text-right">
                  <span class="mono font-semibold text-pp">${formatCompact(r.pp_hr)}</span>
                  ${this.renderShareSubLine(r.pp_country_share_pct, 'var(--color-pp)')}
                </td>
                <td class="text-right">
                  <div class="mono font-semibold text-buy">+${formatMoney(rInc.total, 3)} ₿/h</div>
                  <div class="comp-region-tax-sub mono">
                    <span>Emp: ${formatMoney(rInc.employee_tax, 3)}</span>
                    <span>• Mgr: ${formatMoney(rInc.manager_tax, 3)}</span>
                    <span>• Dev: ${formatMoney(rInc.development, 3)}</span>
                  </div>
                </td>
              </tr>
            `;
          })
          .join('')
      : `<tr><td colspan="4" class="text-center text-muted" style="padding:14px">No regions controlled by this country.</td></tr>`;

    return `
      <tr class="drawer-row">
        <td colspan="4">
          <div class="drawer-container">
            <!-- Top Strip: Country Info, Tax Rates & 7D Trend Sparkline -->
            <div class="drawer-top-strip">
              <div class="drawer-meta-info">
                <div class="drawer-meta-title">
                  <span>${escapeHtml(c.name)}</span>
                  <span class="pp-badge">${regions.length} Regions</span>
                  <button type="button" class="comp-isolate-btn" data-isolate-entity="${escapeHtml(cKey)}" title="Isolate ${escapeHtml(c.name)} on History Chart">
                    📈 Chart
                  </button>
                </div>
                <div class="drawer-meta-subtitle">
                  Employee Income Tax: <strong class="text-primary">${formatPct(taxes.income, 1)}</strong> •
                  Manager Tax: <strong class="text-primary">${formatPct(taxes.manager, 1)}</strong> •
                  Total Wages Paid: <strong class="text-btc">${formatMoney(c.wages_hr, 2)} ₿/h</strong> (${formatMoney(c.wages_24h, 2)} ₿/24h)
                </div>
              </div>

              <div class="sparkline-box" title="7-Day Trend (Solid Blue: Output PP/hr • Dashed Green: Treasury Income ₿/hr)">
                <div class="sparkline-labels">
                  <span class="text-pp">PP/h: ${formatCompact(c.pp_hr)}</span>
                  <span class="text-buy">Treasury: +${formatMoney(inc.total, 2)} ₿/h</span>
                </div>
                <div class="sparkline-canvas-wrap">
                  ${sparkSvg}
                </div>
              </div>
            </div>

            <!-- 4-Card Country Treasury & Payroll Breakdown Grid -->
            <div class="comp-country-cards-grid">
              <div class="comp-stat-box">
                <div class="comp-stat-label">Total Treasury (total)</div>
                <div class="comp-stat-val mono text-buy">+${formatMoney(inc.total, 3)} ₿/h</div>
                <div class="comp-stat-sub mono">+${formatMoney((inc.total || 0) * 24, 2)} ₿ / 24h</div>
              </div>

              <div class="comp-stat-box">
                <div class="comp-stat-label">Employee Tax (${formatPct(taxes.income, 0)})</div>
                <div class="comp-stat-val mono text-pp">+${formatMoney(inc.employee_tax, 3)} ₿/h</div>
                <div class="comp-stat-sub mono">+${formatMoney((inc.employee_tax || 0) * 24, 2)} ₿ / 24h</div>
              </div>

              <div class="comp-stat-box">
                <div class="comp-stat-label">Manager Tax (${formatPct(taxes.manager, 0)})</div>
                <div class="comp-stat-val mono text-pp">+${formatMoney(inc.manager_tax, 3)} ₿/h</div>
                <div class="comp-stat-sub mono">+${formatMoney((inc.manager_tax || 0) * 24, 2)} ₿ / 24h</div>
              </div>

              <div class="comp-stat-box">
                <div class="comp-stat-label">Development &amp; Wages</div>
                <div class="comp-stat-val mono">+${formatMoney(inc.development, 3)} ₿/h <span class="text-muted" style="font-size:0.7rem">Dev</span></div>
                <div class="comp-stat-sub mono text-btc">Wages: ${formatMoney(c.wages_hr, 2)} ₿/h</div>
              </div>
            </div>

            <!-- Regional Breakdown Table inside the Country -->
            <div class="comp-regions-panel">
              <div class="comp-regions-header">
                <span>Regions in ${escapeHtml(c.name)} (Share % inside country)</span>
                <span class="mono text-muted">${formatInt(c.companies)} Companies • ${formatCompact(c.pp_hr)} PP/hr</span>
              </div>
              <div class="comp-regions-table-wrap">
                <table class="terminal-table comp-regions-table">
                  <thead>
                    <tr>
                      <th style="width:29%;text-align:left">Region</th>
                      <th style="width:20%;text-align:right">Companies</th>
                      <th style="width:21%;text-align:right">PP/hr</th>
                      <th style="width:30%;text-align:right">Region Income (₿/h)</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${regionRowsHtml}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </td>
      </tr>
    `;
  }

  // ===========================================================================
  // EVENTS & HISTORICAL CHART
  // ===========================================================================

  bindIsolateChartButtons(container) {
    container.querySelectorAll('[data-isolate-entity]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const code = btn.dataset.isolateEntity;
        const chartMount = this.mountEl.querySelector('#companies-history-mount');
        if (chartMount) {
          chartMount.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        if (this.chartWidget) {
          this.chartWidget.isolateEntity(code);
        }
      });
    });
  }

  bindEvents() {
    this.mountEl.querySelectorAll('[data-comp-subtab]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const targetSub = btn.dataset.compSubtab;
        if (this.subtab !== targetSub) {
          window.location.hash = `#companies/${targetSub}`;
        }
      });
    });

    const countrySearchInput = this.mountEl.querySelector('[data-role="comp-country-search"]');
    if (countrySearchInput) {
      countrySearchInput.addEventListener('input', (e) => {
        this.countrySearchQuery = e.target.value || '';
        this.renderCountriesRows();
      });
    }

    this.mountEl.querySelectorAll('[data-sort-item]').forEach((th) => {
      th.addEventListener('click', () => {
        const field = th.dataset.sortItem;
        if (this.itemSortField === field) {
          this.itemSortDesc = !this.itemSortDesc;
        } else {
          this.itemSortField = field;
          this.itemSortDesc = field !== 'name';
        }
        const tableWrap = this.mountEl.querySelector('[data-role="table-wrap"]');
        if (tableWrap) {
          tableWrap.innerHTML = this.renderItemsTableShell();
          this.renderItemsRows();
          this.bindTableSortHeaders();
        }
      });
    });

    this.mountEl.querySelectorAll('[data-sort-country]').forEach((th) => {
      th.addEventListener('click', () => {
        const field = th.dataset.sortCountry;
        if (this.countrySortField === field) {
          this.countrySortDesc = !this.countrySortDesc;
        } else {
          this.countrySortField = field;
          this.countrySortDesc = field !== 'name';
        }
        const tableWrap = this.mountEl.querySelector('[data-role="table-wrap"]');
        if (tableWrap) {
          tableWrap.innerHTML = this.renderCountriesTableShell();
          this.renderCountriesRows();
          this.bindTableSortHeaders();
        }
      });
    });
  }

  bindTableSortHeaders() {
    this.mountEl.querySelectorAll('[data-sort-item]').forEach((th) => {
      th.addEventListener('click', () => {
        const field = th.dataset.sortItem;
        if (this.itemSortField === field) {
          this.itemSortDesc = !this.itemSortDesc;
        } else {
          this.itemSortField = field;
          this.itemSortDesc = field !== 'name';
        }
        const tableWrap = this.mountEl.querySelector('[data-role="table-wrap"]');
        if (tableWrap) {
          tableWrap.innerHTML = this.renderItemsTableShell();
          this.renderItemsRows();
          this.bindTableSortHeaders();
        }
      });
    });

    this.mountEl.querySelectorAll('[data-sort-country]').forEach((th) => {
      th.addEventListener('click', () => {
        const field = th.dataset.sortCountry;
        if (this.countrySortField === field) {
          this.countrySortDesc = !this.countrySortDesc;
        } else {
          this.countrySortField = field;
          this.countrySortDesc = field !== 'name';
        }
        const tableWrap = this.mountEl.querySelector('[data-role="table-wrap"]');
        if (tableWrap) {
          tableWrap.innerHTML = this.renderCountriesTableShell();
          this.renderCountriesRows();
          this.bindTableSortHeaders();
        }
      });
    });
  }

  buildCountryEntitiesMap() {
    const countriesMap = (this.data && this.data.by_countries) || {};
    const sortedKeys = Object.keys(countriesMap).sort((a, b) => {
      const ppDiff = (Number(countriesMap[b].pp_hr) || 0) - (Number(countriesMap[a].pp_hr) || 0);
      if (ppDiff !== 0) return ppDiff;
      return (Number(countriesMap[b].companies) || 0) - (Number(countriesMap[a].companies) || 0);
    });

    // Display top 24 countries on the chart chip grid so it stays clean and fast
    const topKeys = sortedKeys.slice(0, 24);
    const out = {};
    topKeys.forEach((cKey, idx) => {
      const c = countriesMap[cKey];
      const name = c.name || cKey.toUpperCase();
      const short = name.length > 11 ? `${name.slice(0, 10)}.` : name;
      out[cKey] = {
        code: cKey,
        name,
        short,
        badgeText: String(c.code || cKey).slice(0, 2).toUpperCase(),
        color: COUNTRY_PALETTE[idx % COUNTRY_PALETTE.length],
        pp: 1,
      };
    });
    return out;
  }

  setupLazyChart() {
    const chartMount = this.mountEl.querySelector('#companies-history-mount');
    if (!chartMount) return;

    if (this.chartWidget) {
      this.chartWidget.destroy();
      this.chartWidget = null;
    }

    observeOnce(chartMount, async () => {
      try {
        if (!this.historyData) {
          this.historyData = await store.fetchSlice('companies_history.json');
        }

        if (this.subtab === 'items') {
          this.chartWidget = new HistoryChartWidget({
            mountEl: chartMount,
            title: 'Companies History — By Items',
            historyKey: 'items',
            metrics: [
              {
                key: 'pp_hr',
                label: 'Output (PP/hr)',
                yFormatter: (v) => `${formatCompact(v)} PP`,
                itemFormatter: (v) => `${formatCompact(v)} PP/h`,
              },
              {
                key: 'companies',
                label: 'Companies',
                yFormatter: (v) => formatCompact(v),
                itemFormatter: (v) => formatInt(v),
              },
              {
                key: 'wages_hr',
                label: 'Wages (₿/hr)',
                yFormatter: (v) => `${formatMoney(v, 2)} ₿`,
                itemFormatter: (v) => `${formatMoney(v, 2)} ₿/h`,
              },
            ],
            defaultMetric: 'pp_hr',
            includeCases: false,
          });
        } else {
          const countryEntities = this.buildCountryEntitiesMap();
          this.chartWidget = new HistoryChartWidget({
            mountEl: chartMount,
            title: 'Companies History — Top Countries',
            historyKey: 'countries',
            customEntities: countryEntities,
            metrics: [
              {
                key: 'pp_hr',
                label: 'Output (PP/hr)',
                yFormatter: (v) => `${formatCompact(v)} PP`,
                itemFormatter: (v) => `${formatCompact(v)} PP/h`,
              },
              {
                key: 'companies',
                label: 'Companies',
                yFormatter: (v) => formatCompact(v),
                itemFormatter: (v) => formatInt(v),
              },
              {
                key: 'wages_hr',
                label: 'Wages (₿/hr)',
                yFormatter: (v) => `${formatMoney(v, 2)} ₿`,
                itemFormatter: (v) => `${formatMoney(v, 2)} ₿/h`,
              },
              {
                key: 'tax_total_hr',
                label: 'Treasury (₿/hr)',
                yFormatter: (v) => `${formatMoney(v, 2)} ₿`,
                itemFormatter: (v) => `+${formatMoney(v, 2)} ₿/h`,
              },
            ],
            defaultMetric: 'pp_hr',
          });
        }

        this.chartWidget.setData(this.historyData);
      } catch (err) {
        chartMount.innerHTML = `<div class="skeleton-loader">Failed to load Companies History: ${escapeHtml(err.message)}</div>`;
      }
    });
  }
}
