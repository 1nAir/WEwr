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

function formatMetric(val) {
  const n = Number(val) || 0;
  const abs = Math.abs(n);
  if (abs > 0 && abs < 50) {
    const rounded1 = Math.round(n * 10) / 10;
    return Number.isInteger(rounded1)
      ? rounded1.toLocaleString('en-US')
      : rounded1.toLocaleString('en-US', {
          minimumFractionDigits: 1,
          maximumFractionDigits: 1,
        });
  }
  return Math.round(n).toLocaleString('en-US');
}

/**
 * Returns bar and text RGB colors for Traded vs Output %:
 * - < 100%: Blue (--color-pp), dimming from 90% -> 100%
 * - >= 100%: Green (--color-buy), dimming from 110% -> 100%
 */
function getTradedPctColors(pct) {
  const n = Number(pct) || 0;
  const isOver100 = n >= 100;
  const baseBar = isOver100 ? [16, 185, 129] : [56, 189, 248];
  const baseText = isOver100 ? [52, 211, 153] : [125, 211, 252];

  const dist = Math.min(10, Math.abs(n - 100));
  const t = dist / 10; // 1.0 outside [90..110], 0.0 at 100%
  const barScale = 0.45 + 0.55 * t;
  const textScale = 0.55 + 0.45 * t;

  const barRgb = baseBar.map((c) => Math.round(c * barScale)).join(', ');
  const textRgb = baseText.map((c) => Math.round(c * textScale)).join(', ');
  return {
    barColor: `rgb(${barRgb})`,
    textColor: `rgb(${textRgb})`,
  };
}

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

    this.countrySortField = 'wages_hr'; // 'name' | 'companies' | 'wages_hr' | 'tax_total_hr'
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

  getCountryFlagUrl(c, cKey) {
    const rawCode = String((c && c.code) || cKey || '')
      .split('_')[0]
      .trim()
      .toLowerCase();
    return rawCode
      ? `https://flagcdn.com/w40/${encodeURIComponent(rawCode)}.png`
      : 'assets/guide.webp';
  }

  render() {
    if (!this.mountEl || !this.data) return;

    const summary = this.data.summary || {};
    const countriesMap = this.data.by_countries || {};
    const itemsCount = Object.keys(this.data.by_items || {}).length;
    const countriesCount = Object.keys(countriesMap).length;

    let globalWageTaxHr = 0;
    for (const c of Object.values(countriesMap)) {
      const taxes = c.taxes || {};
      const incRate = (Number(taxes.income) || 0) / 100;
      const mgrRate = (Number(taxes.manager) || 0) / 100;
      globalWageTaxHr +=
        (Number(c.emp_wages_hr) || 0) * incRate +
        (Number(c.mgr_wages_hr) || 0) * mgrRate;
    }

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
              placeholder="Search country..."
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
          </div>
          <div class="kpi-sub mono">
            Players 15+ Lvl: ${formatInt(summary.eligible_players)}
          </div>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">Global Output (PP/hr)</div>
          <div class="kpi-value mono text-pp">
            ${formatMetric(summary.total_pp_hr)} PP/h
          </div>
          <div class="kpi-sub mono">
            ${formatMetric(summary.total_pp_24h)} PP / 24h
          </div>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">Total Wages (Emp + Mgr)</div>
          <div class="kpi-value mono text-btc">
            ${formatMetric(summary.total_wages_hr)} ₿/h
          </div>
          <div class="kpi-sub mono">
            ${formatMetric(summary.total_wages_24h)} ₿ / 24h
          </div>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">Total Tax (Emp + Mgr)</div>
          <div class="kpi-value mono text-buy">
            +${formatMetric(globalWageTaxHr)} ₿/h
          </div>
          <div class="kpi-sub mono">
            +${formatMetric(globalWageTaxHr * 24)} ₿ / 24h
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
            <th class="sortable ${sf === 'market_vs_prod_pct' ? 'sorted' : ''}" data-sort-item="market_vs_prod_pct" style="width:30%;text-align:left" title="Sort by 24h Market Traded vs Output (%)">
              Traded % ${this.renderSortArrow(sf, 'market_vs_prod_pct', sd)}
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
              <span class="desktop-only">Wages (₿/hr)</span>
              <span class="mobile-only">Wages</span>
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
            <th class="sortable ${sf === 'name' ? 'sorted' : ''}" data-sort-country="name" style="width:40%;text-align:left">
              Country &amp; Tax ${this.renderSortArrow(sf, 'name', sd)}
            </th>
            <th class="sortable ${sf === 'companies' ? 'sorted' : ''}" data-sort-country="companies" style="width:28%;text-align:right">
              Companies ${this.renderSortArrow(sf, 'companies', sd)}
            </th>
            <th class="sortable ${sf === 'wages_hr' ? 'sorted' : ''}" data-sort-country="wages_hr" style="width:32%;text-align:right">
              <span class="desktop-only">Wages &amp; Tax (₿/hr)</span>
              <span class="mobile-only">Wages &amp; Tax</span>
              ${this.renderSortArrow(sf, 'wages_hr', sd)}
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
      let cmp = valA - valB;
      if (cmp === 0) {
        const nameA = store.getItemMeta(a).name || a;
        const nameB = store.getItemMeta(b).name || b;
        cmp = nameA.localeCompare(nameB);
      }
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
      const mktPct = Number(it.market_vs_prod_pct) || 0;
      const mktBarWidth = Math.max(0, Math.min(100, mktPct));
      const { barColor: mktBarColor, textColor: mktTextColor } =
        getTradedPctColors(mktPct);

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
                <div class="liquidity-group">
                  <div class="liquidity-bar-track" style="background:rgba(255,255,255,0.08)" title="24h Traded vs Output: ${formatPct(mktPct, 0)} (${formatMetric(it.traded_pp_24h)} / ${formatMetric(it.pp_24h)} PP)">
                    <div class="liquidity-bar-buy" style="width:${mktBarWidth}%;background:${mktBarColor}"></div>
                  </div>
                  <span class="liquidity-pct" style="color:${mktTextColor}" title="24h Traded vs Output">${formatPct(mktPct, 0)}</span>
                </div>
              </div>
            </div>
          </td>
          <td class="text-right">
            <span class="metric-primary">${formatInt(it.companies)}</span>
            ${this.renderShareSubLine(it.companies_share_pct, 'var(--accent-primary)')}
          </td>
          <td class="text-right">
            <span class="metric-primary text-pp">${formatMetric(it.pp_hr)} <span class="desktop-only">PP/h</span></span>
            ${this.renderShareSubLine(it.pp_share_pct, 'var(--color-pp)')}
          </td>
          <td class="text-right">
            <span class="metric-primary text-btc">${formatMetric(it.wages_hr)} <span class="desktop-only">₿/h</span><span class="mobile-only">₿</span></span>
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
  }

  renderItemDrawer(code, it) {
    const mktPct = Number(it.market_vs_prod_pct) || 0;
    const { textColor: mktTextColor } = getTradedPctColors(mktPct);

    return `
      <tr class="drawer-row">
        <td colspan="4">
          <div class="drawer-container">
            <div class="recipe-grid">
              <!-- Card 1: Production & Market Absorption (Output vs Market) -->
              <div class="recipe-card conservative">
                <div class="recipe-card-header">
                  <span class="recipe-card-title text-pp">Production &amp; Market Volume</span>
                  <span class="recipe-card-badge">24h Output vs Market</span>
                </div>
                <div class="formula-line">
                  <span>Daily Output (24h)</span>
                  <span class="mono text-pp">${formatMetric(it.pp_24h)} PP</span>
                </div>
                <div class="formula-line">
                  <span>Market Volume (24h)</span>
                  <span class="mono text-btc">${formatMetric(it.traded_pp_24h)} PP</span>
                </div>
                <div class="formula-result-banner">
                  <span class="text-secondary">Traded vs Output (24h)</span>
                  <strong style="color:${mktTextColor}">${formatPct(mktPct, 0)} Traded</strong>
                </div>
              </div>

              <!-- Card 2: Workforce Payroll (Employees + Managers) -->
              <div class="recipe-card optimistic">
                <div class="recipe-card-header">
                  <span class="recipe-card-title text-btc">Workforce Payroll</span>
                  <span class="recipe-card-badge">Employees + Managers</span>
                </div>
                <div class="formula-line">
                  <span>Employees (1h / 24h)</span>
                  <span class="mono">${formatMetric(it.emp_wages_hr)} ₿/h • ${formatMetric((it.emp_wages_hr || 0) * 24)} ₿</span>
                </div>
                <div class="formula-line">
                  <span>Managers (1h / 24h)</span>
                  <span class="mono">${formatMetric(it.mgr_wages_hr)} ₿/h • ${formatMetric((it.mgr_wages_hr || 0) * 24)} ₿</span>
                </div>
                <div class="formula-result-banner">
                  <span class="text-secondary">Daily Payroll (24h)</span>
                  <strong class="text-btc">${formatMetric(it.wages_24h)} ₿ / 24h</strong>
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
        return (
          cKey.toLowerCase().includes(q) ||
          (c.name && c.name.toLowerCase().includes(q))
        );
      })
      .sort((a, b) => {
        const cA = countriesMap[a];
        const cB = countriesMap[b];
        if (this.countrySortField === 'name') {
          const cmp = (cA.name || a).localeCompare(cB.name || b);
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
          <td colspan="3" class="text-center text-muted" style="padding:28px">
            No matching countries found.
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
      const incRate = (Number(taxes.income) || 0) / 100;
      const mgrRate = (Number(taxes.manager) || 0) / 100;
      const flagUrl = this.getCountryFlagUrl(c, cKey);
      const wageTaxHr =
        (Number(c.emp_wages_hr) || 0) * incRate +
        (Number(c.mgr_wages_hr) || 0) * mgrRate;

      rowsHtml.push(`
        <tr class="item-row ${isExpanded ? 'expanded' : ''}" data-comp-country-row="${escapeHtml(cKey)}">
          <td>
            <div class="product-cell">
              <span class="expand-caret">▶</span>
              <img
                src="${flagUrl}"
                alt=""
                class="comp-country-flag"
                loading="lazy"
                onerror="this.onerror=null;this.src='assets/guide.webp';"
              />
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
            <span class="metric-primary text-btc">${formatMetric(c.wages_hr)} <span class="desktop-only">₿/h</span><span class="mobile-only">₿</span></span>
            <span class="metric-sub">Tax: <span class="text-buy">+${formatMetric(wageTaxHr)} ₿/h</span></span>
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
  }

  renderCountryDrawer(cKey, c) {
    const taxes = c.taxes || {};
    const incRate = (Number(taxes.income) || 0) / 100;
    const mgrRate = (Number(taxes.manager) || 0) / 100;
    const empTax = (Number(c.emp_wages_hr) || 0) * incRate;
    const mgrTax = (Number(c.mgr_wages_hr) || 0) * mgrRate;
    const totalWageTax = empTax + mgrTax;

    const regions = [...(c.regions || [])].sort(
      (a, b) => (Number(b.wages_hr) || 0) - (Number(a.wages_hr) || 0)
    );

    const regionRowsHtml = regions.length
      ? regions
          .map((r) => {
            const rEmpTax = (Number(r.emp_wages_hr) || 0) * incRate;
            const rMgrTax = (Number(r.mgr_wages_hr) || 0) * mgrRate;
            const rWageTax = rEmpTax + rMgrTax;

            return `
              <tr class="comp-region-row">
                <td>
                  <div class="comp-region-name">${escapeHtml(r.name)}</div>
                </td>
                <td class="text-right">
                  <span class="mono font-semibold">${formatInt(r.companies)}</span>
                  ${this.renderShareSubLine(r.companies_country_share_pct, 'var(--accent-primary)')}
                </td>
                <td class="text-right">
                  <div class="mono font-semibold text-btc">${formatMetric(r.wages_hr)} ₿/h</div>
                  <div class="comp-region-tax-sub mono">
                    <div>Emp: ${formatMetric(r.emp_wages_hr)} • Mgr: ${formatMetric(r.mgr_wages_hr)}</div>
                    <div class="text-buy">Tax: +${formatMetric(rWageTax)} ₿/h</div>
                  </div>
                </td>
              </tr>
            `;
          })
          .join('')
      : `<tr><td colspan="3" class="text-center text-muted" style="padding:14px">No regions controlled by this country.</td></tr>`;

    return `
      <tr class="drawer-row">
        <td colspan="3">
          <div class="drawer-container">
            <!-- 3-Card Country Wage & Tax Breakdown Grid -->
            <div class="comp-country-cards-grid">
              <div class="comp-stat-box">
                <div class="comp-stat-label">Total Tax (Emp + Mgr)</div>
                <div class="comp-stat-val mono text-buy">+${formatMetric(totalWageTax)} ₿/h</div>
                <div class="comp-stat-sub mono">+${formatMetric(totalWageTax * 24)} ₿ / 24h</div>
              </div>

              <div class="comp-stat-box">
                <div class="comp-stat-label">Employee Tax (${formatPct(taxes.income, 0)})</div>
                <div class="comp-stat-val mono text-pp">+${formatMetric(empTax)} ₿/h</div>
                <div class="comp-stat-sub mono">Emp Wages: <span class="text-btc">${formatMetric(c.emp_wages_hr)} ₿/h</span></div>
              </div>

              <div class="comp-stat-box">
                <div class="comp-stat-label">Manager Tax (${formatPct(taxes.manager, 0)})</div>
                <div class="comp-stat-val mono text-pp">+${formatMetric(mgrTax)} ₿/h</div>
                <div class="comp-stat-sub mono">Mgr Wages: <span class="text-btc">${formatMetric(c.mgr_wages_hr)} ₿/h</span></div>
              </div>
            </div>

            <!-- Regional Breakdown Table inside the Country -->
            <div class="comp-regions-panel">
              <div class="comp-regions-header">
                <span>Regions in ${escapeHtml(c.name)} (${regions.length})</span>
              </div>
              <div class="comp-regions-table-wrap">
                <table class="terminal-table comp-regions-table">
                  <thead>
                    <tr>
                      <th style="width:36%;text-align:left">Region</th>
                      <th style="width:24%;text-align:right">Companies</th>
                      <th style="width:40%;text-align:right">Wages &amp; Tax (₿/h)</th>
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
      const wDiff =
        (Number(countriesMap[b].wages_hr) || 0) -
        (Number(countriesMap[a].wages_hr) || 0);
      if (wDiff !== 0) return wDiff;
      return (
        (Number(countriesMap[b].companies) || 0) -
        (Number(countriesMap[a].companies) || 0)
      );
    });

    const out = {};
    sortedKeys.forEach((cKey, idx) => {
      const c = countriesMap[cKey];
      const name = c.name || cKey.toUpperCase();
      const short = name.length > 11 ? `${name.slice(0, 10)}.` : name;
      out[cKey] = {
        code: cKey,
        name,
        short,
        iconUrl: this.getCountryFlagUrl(c, cKey),
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
                yFormatter: (v) => `${formatMetric(v)} PP`,
                itemFormatter: (v) => `${formatMetric(v)} PP/h`,
              },
              {
                key: 'companies',
                label: 'Companies',
                yFormatter: (v) => formatInt(v),
                itemFormatter: (v) => formatInt(v),
              },
              {
                key: 'wages_hr',
                label: 'Wages (₿/hr)',
                yFormatter: (v) => `${formatMetric(v)} ₿`,
                itemFormatter: (v) => `${formatMetric(v)} ₿/h`,
              },
            ],
            defaultMetric: 'pp_hr',
            includeCases: false,
          });
        } else {
          const countryEntities = this.buildCountryEntitiesMap();
          this.chartWidget = new HistoryChartWidget({
            mountEl: chartMount,
            title: 'Companies History — By Countries',
            historyKey: 'countries',
            customEntities: countryEntities,
            defaultVisibleCount: 5,
            metrics: [
              {
                key: 'wages_hr',
                label: 'Wages (₿/hr)',
                yFormatter: (v) => `${formatMetric(v)} ₿`,
                itemFormatter: (v) => `${formatMetric(v)} ₿/h`,
              },
              {
                key: 'companies',
                label: 'Companies',
                yFormatter: (v) => formatInt(v),
                itemFormatter: (v) => formatInt(v),
              },
            ],
            defaultMetric: 'wages_hr',
          });
        }

        this.chartWidget.setData(this.historyData);
      } catch (err) {
        chartMount.innerHTML = `<div class="skeleton-loader">Failed to load Companies History: ${escapeHtml(err.message)}</div>`;
      }
    });
  }
}
