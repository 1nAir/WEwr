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
import { observeOnce } from '../utils/dom.js';
import { renderEntityInline, renderTierPills } from '../components/entityBadge.js';
import { renderSparklineSvg } from '../components/sparkline.js';
import { HistoryChartWidget } from '../components/historyChart.js';

const COMPACT_TIER_LIMIT = 8;

/**
 * View Module: Market Subtab 1 — Unified Order Book (Buy & Sell Depth Combined).
 * - Buy Demand column is sorted & measured primarily by Money on market (₿).
 * - Sell Supply column is sorted & measured primarily by Production Points (PP) on market.
 * - Price ladders render cumulative market volume shading across each row and inline
 *   Buyout / Sellout simulator cards directly below the clicked price tier.
 */
export class OrderBookView {
  constructor(mountEl) {
    this.mountEl = mountEl;
    this.data = null;
    this.sortField = 'sell_pp'; // 'name' | 'spread' | 'buy_btc' | 'sell_pp'
    this.sortDesc = true;
    this.expandedItems = new Set();

    // Per-item UI state inside expanded drawers
    this.mobileBookMode = new Map(); // code -> 'buy' | 'sell' | 'both'
    this.showFullBuyLadder = new Set();
    this.showFullSellLadder = new Set();
    this.buySimSelection = new Map(); // code -> tierIndex
    this.sellSimSelection = new Map(); // code -> tierIndex
    this.chartWidget = null;
  }

  async init(forceRefresh = false) {
    await store.ensureMeta(forceRefresh);
    this.data = await store.fetchSlice('orderbook.json', forceRefresh);
    this.render();
  }

  render() {
    if (!this.mountEl || !this.data) return;

    this.mountEl.innerHTML = `
      <div class="table-card">
        <table class="terminal-table">
          <thead>
            <tr>
              <th class="sortable ${this.sortField === 'name' ? 'sorted' : ''}" data-sort="name" style="width:28%;text-align:left" title="Sort by 75% Depth Liquidity (%)">
                Product ${this.renderSortArrow('name')}
              </th>
              <th class="sortable ${this.sortField === 'spread' ? 'sorted' : ''}" data-sort="spread" style="width:28%;text-align:right">
                <span class="desktop-only">Best Bid / Ask</span>
                <span class="mobile-only">Bid / Ask</span>
                ${this.renderSortArrow('spread')}
              </th>
              <th class="sortable ${this.sortField === 'buy_btc' ? 'sorted' : ''}" data-sort="buy_btc" style="width:22%;text-align:right">
                Buy (₿)
                ${this.renderSortArrow('buy_btc')}
              </th>
              <th class="sortable ${this.sortField === 'sell_pp' ? 'sorted' : ''}" data-sort="sell_pp" style="width:22%;text-align:right">
                Sell (PP)
                ${this.renderSortArrow('sell_pp')}
              </th>
            </tr>
          </thead>
          <tbody data-role="tbody"></tbody>
        </table>
      </div>

      <div id="orderbook-history-mount">
        <div class="skeleton-loader">Scroll to load Order Book Depth History Chart...</div>
      </div>
    `;

    this.renderTableRows();
    this.bindToolbarEvents();
    this.setupLazyChart();
  }

  renderSortArrow(field) {
    if (this.sortField !== field) return '';
    return `<span class="sort-arrow">${this.sortDesc ? '↓' : '↑'}</span>`;
  }

  /**
   * Buy Demand is always primary in ₿ (money left on market), with PP/units as auxiliary sub-info.
   */
  formatBuyDisplay(buyObj, ppPerUnit) {
    const btc = Number(buyObj?.total_money_btc || 0);
    const pp = Number(buyObj?.total_pp || 0);
    const units = Number(buyObj?.total_units || 0);

    const main = `${formatCompact(btc)} ₿`;
    const sub = ppPerUnit > 0 ? `${formatCompact(pp)} PP` : `${formatCompact(units)} pcs`;
    return { main, sub };
  }

  /**
   * Sell Supply is always primary in PP (goods on market; or units for 0-PP items),
   * with ~₿ value (and units as auxiliary info) underneath.
   */
  formatSellDisplay(sellObj, ppPerUnit) {
    const btc = Number(sellObj?.total_value_btc || 0);
    const pp = Number(sellObj?.total_pp || 0);
    const units = Number(sellObj?.total_units || 0);

    if (ppPerUnit === 0) {
      return {
        main: `${formatCompact(units)} pcs`,
        sub: `~${formatCompact(btc)} ₿`,
      };
    }
    if (ppPerUnit === 1) {
      return {
        main: `${formatCompact(pp)} PP`,
        sub: `~${formatCompact(btc)} ₿`,
      };
    }
    return {
      main: `${formatCompact(pp)} PP`,
      sub: `~${formatCompact(btc)} ₿ • ${formatCompact(units)} pcs`,
    };
  }

  getSortedCodes() {
    const itemsMap = (this.data && this.data.items) || {};

    return Object.keys(itemsMap).sort((a, b) => {
      const itA = itemsMap[a];
      const itB = itemsMap[b];
      const metaA = store.getItemMeta(a);
      const metaB = store.getItemMeta(b);
      let cmp = 0;

      if (this.sortField === 'name') {
        const buyA = this.compute75DepthMoney(itA.buy, itA.best_bid, true);
        const sellA = this.compute75DepthMoney(itA.sell, itA.best_ask, false);
        const totA = buyA + sellA;
        const pctA = totA > 0 ? (buyA / totA) * 100 : 50;

        const buyB = this.compute75DepthMoney(itB.buy, itB.best_bid, true);
        const sellB = this.compute75DepthMoney(itB.sell, itB.best_ask, false);
        const totB = buyB + sellB;
        const pctB = totB > 0 ? (buyB / totB) * 100 : 50;

        cmp = pctA - pctB;
        if (cmp === 0) {
          cmp = (metaA?.name || a).localeCompare(metaB?.name || b);
        }
      } else if (this.sortField === 'spread') {
        cmp = (Number(itA.spread_pct) || 0) - (Number(itB.spread_pct) || 0);
      } else if (this.sortField === 'buy_btc') {
        const mA = Number(itA.buy?.total_money_btc || 0);
        const mB = Number(itB.buy?.total_money_btc || 0);
        cmp = mA - mB;
        if (cmp === 0) {
          cmp = (Number(itA.buy?.total_pp) || 0) - (Number(itB.buy?.total_pp) || 0);
        }
        if (cmp === 0) {
          cmp = (Number(itA.buy?.total_units) || 0) - (Number(itB.buy?.total_units) || 0);
        }
      } else if (this.sortField === 'sell_pp') {
        const ppA = Number(itA.sell?.total_pp || 0);
        const ppB = Number(itB.sell?.total_pp || 0);
        cmp = ppA - ppB;
        if (cmp === 0) {
          cmp = (Number(itA.sell?.total_units) || 0) - (Number(itB.sell?.total_units) || 0);
        }
        if (cmp === 0) {
          cmp = (Number(itA.sell?.total_value_btc) || 0) - (Number(itB.sell?.total_value_btc) || 0);
        }
      }
      return this.sortDesc ? -cmp : cmp;
    });
  }

  /**
   * Computes cumulative ₿ (Received for Buy book / Total Cost for Sell book)
   * across regular price tiers until cumulative quantity crosses >= 75%
   * of regular book units (Demand Cleared / Market Share >= 75%).
   * The tier that crosses the 75% threshold is included in full.
   */
  compute75DepthMoney(sideData, bestPrice, isBuy) {
    const rawLadder = sideData?.ladder || [];
    if (!rawLadder.length) return 0;

    const normalTiers = [];
    const thresholdPrice = bestPrice > 0 ? (isBuy ? bestPrice * 0.5 : bestPrice * 2.0) : 0;

    for (const row of rawLadder) {
      if (bestPrice > 0) {
        if (isBuy && row.p < thresholdPrice - 1e-9) continue;
        if (!isBuy && row.p >= thresholdPrice - 1e-9) continue;
      }
      normalTiers.push(row);
    }

    const regularTotalUnits = normalTiers.reduce(
      (sum, r) => sum + Number(r.q || 0),
      0
    );
    if (regularTotalUnits <= 0) return 0;

    const targetUnits = regularTotalUnits * 0.75;
    let runningCumQty = 0;
    let runningCumMoney = 0;

    for (const row of normalTiers) {
      const qty = Number(row.q || 0);
      const tierMoney = Number(row.m ?? row.p * qty);
      runningCumQty += qty;
      runningCumMoney += tierMoney;
      if (runningCumQty >= targetUnits - 1e-9) {
        break;
      }
    }

    return runningCumMoney;
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

      const buyDisp = this.formatBuyDisplay(it.buy, meta.pp);
      const sellDisp = this.formatSellDisplay(it.sell, meta.pp);

      const buyReceived75 = this.compute75DepthMoney(it.buy, it.best_bid, true);
      const sellCost75 = this.compute75DepthMoney(it.sell, it.best_ask, false);
      const totalLiq = buyReceived75 + sellCost75;
      const buyRatioPct = totalLiq > 0 ? Math.round((buyReceived75 / totalLiq) * 100) : 50;
      const hasSpread = it.best_bid > 0 && it.best_ask > 0;
      const spreadQualityClass = it.spread_pct > 5.0 ? 'spread-wide' : 'spread-normal';

      rowsHtml.push(`
        <tr class="item-row ${isExpanded ? 'expanded' : ''}" data-ob-row="${escapeHtml(code)}">
          <td>
            <div class="product-cell">
              <span class="expand-caret">▶</span>
              <img src="assets/${escapeHtml(code)}.webp" alt="" class="item-icon" loading="lazy" />
              <div class="item-title-group">
                <div class="item-name-line">
                  ${renderItemName(meta)}
                </div>
                <div style="display:inline-flex;align-items:center;gap:6px;margin-top:4px;">
                  <div class="liquidity-bar-track" style="width:80px;flex-shrink:0" title="Liquidity Balance (≥75% Depth): ${buyRatioPct}% Buy (${formatCompact(buyReceived75)} ₿) / ${100 - buyRatioPct}% Sell (${formatCompact(sellCost75)} ₿)">
                    <div class="liquidity-bar-buy" style="width:${buyRatioPct}%"></div>
                    <div class="liquidity-bar-sell"></div>
                  </div>
                  <span class="mono text-xs ${buyRatioPct >= 50 ? 'text-buy' : 'text-sell'}" style="font-size:0.7rem;font-weight:600" title="Liquidity Balance">${buyRatioPct}%</span>
                </div>
              </div>
            </div>
          </td>
          <td class="text-right">
            <div class="bid-ask-group">
              <div class="bid-ask-line">
                <span class="text-buy" title="Best Bid (Highest Buy Order)">${formatPrice(it.best_bid)}</span>
                <span class="text-muted">↔</span>
                <span class="text-sell" title="Best Ask (Lowest Sell Order)">${formatPrice(it.best_ask)}</span>
              </div>
              ${hasSpread ? `
                <span class="spread-pill ${spreadQualityClass}">
                  ${formatPct(it.spread_pct, 1)} (${formatPrice(it.spread_btc)} ₿)
                </span>
              ` : ''}
            </div>
          </td>
          <td class="text-right">
            <span class="metric-primary text-buy">${escapeHtml(buyDisp.main)}</span>
            <span class="metric-sub">${escapeHtml(buyDisp.sub)}</span>
          </td>
          <td class="text-right">
            <span class="metric-primary text-sell">${escapeHtml(sellDisp.main)}</span>
            <span class="metric-sub">${escapeHtml(sellDisp.sub)}</span>
          </td>
        </tr>
      `);

      if (isExpanded) {
        rowsHtml.push(this.renderExpandedOrderBook(code, it, meta));
      }
    }

    tbody.innerHTML = rowsHtml.join('');
    this.bindRowAndDrawerEvents(tbody);
  }

  renderExpandedOrderBook(code, it, meta) {
    const mobileMode = this.mobileBookMode.get(code) || 'buy';
    const spark = it.sparkline_7d || {};
    const sparkSvg = renderSparklineSvg({
      seriesA: spark.buy_pp?.length ? spark.buy_pp : spark.buy_units || [],
      seriesB: spark.sell_pp?.length ? spark.sell_pp : spark.sell_units || [],
      colorA: '#10b981',
      colorB: '#f43f5e',
    });

    const buyBookHtml = this.renderBookSideColumn({
      code,
      side: 'buy',
      sideData: it.buy,
      bestPrice: it.best_bid,
      ppPerUnit: meta.pp,
    });

    const sellBookHtml = this.renderBookSideColumn({
      code,
      side: 'sell',
      sideData: it.sell,
      bestPrice: it.best_ask,
      ppPerUnit: meta.pp,
    });

    const splitBookHtml =
      mobileMode === 'both' ? this.renderMobileSplitTBook(code, it) : '';

    const sellMainLabel =
      meta.pp > 0
        ? `${formatInt(it.sell?.total_pp)} PP`
        : `${formatInt(it.sell?.total_units)} units`;
    const sellCompactLabel =
      meta.pp > 0
        ? `${formatCompact(it.sell?.total_pp)} PP`
        : `${formatCompact(it.sell?.total_units)} pcs`;

    return `
      <tr class="drawer-row">
        <td colspan="4">
          <div class="drawer-container" data-drawer-code="${escapeHtml(code)}">
            <!-- Top Summary & 7d Depth Sparkline -->
            <div class="drawer-top-strip">
              <div class="drawer-meta-info">
                <div class="drawer-meta-title">
                  <span>${escapeHtml(meta.name)} Order Book</span>
                  <span class="pp-badge">Bid: ${formatPrice(it.best_bid)} ₿</span>
                  <span class="pp-badge">Ask: ${formatPrice(it.best_ask)} ₿</span>
                  <span class="pp-badge">Spread: ${formatPct(it.spread_pct, 1)}</span>
                </div>
                <div class="drawer-meta-subtitle">
                  Buy: <span class="text-buy">${formatMoney(it.buy?.total_money_btc)} ₿</span> (${meta.pp > 0 ? `${formatInt(it.buy?.total_pp)} PP` : `${formatInt(it.buy?.total_units)} units`}) •
                  Sell: <span class="text-sell">${sellMainLabel}</span> (~${formatMoney(it.sell?.total_value_btc)} ₿)
                </div>
              </div>

              <div class="sparkline-box" title="7-Day Order Book Depth Trend (Green: Buy, Coral: Sell)">
                <div class="sparkline-labels">
                  <span class="text-buy">Buy: ${formatCompact(it.buy?.total_money_btc)} ₿</span>
                  <span class="text-sell">Sell: ${sellCompactLabel}</span>
                </div>
                <div class="sparkline-canvas-wrap">
                  ${sparkSvg}
                </div>
              </div>
            </div>

            <!-- Mobile Segmented Switcher [ Buy | Sell | Both ] -->
            <div class="mobile-book-switcher">
              <button type="button" class="book-switch-btn ${mobileMode === 'buy' ? 'active' : ''}" data-switch-code="${escapeHtml(code)}" data-mode="buy">
                🟢 Buy (${formatCompact(it.buy?.total_money_btc)} ₿)
              </button>
              <button type="button" class="book-switch-btn ${mobileMode === 'sell' ? 'active' : ''}" data-switch-code="${escapeHtml(code)}" data-mode="sell">
                🔴 Sell (${sellCompactLabel})
              </button>
              <button type="button" class="book-switch-btn ${mobileMode === 'both' ? 'active' : ''}" data-switch-code="${escapeHtml(code)}" data-mode="both">
                ⚡ Split Book
              </button>
            </div>

            ${
              mobileMode === 'both'
                ? `<div class="mobile-only" style="display:block">${splitBookHtml}</div>`
                : ''
            }

            <!-- Desktop Side-by-Side / Mobile Selected Column -->
            <div class="orderbook-dual-grid ${mobileMode === 'both' ? 'desktop-only' : ''}" data-mobile-mode="${escapeHtml(mobileMode)}">
              ${buyBookHtml}
              ${sellBookHtml}
            </div>
          </div>
        </td>
      </tr>
    `;
  }

  renderBookSideColumn({ code, side, sideData, bestPrice, ppPerUnit }) {
    const isBuy = side === 'buy';
    const participants = isBuy
      ? sideData?.top_buyers || []
      : sideData?.top_sellers || [];
    const rawLadder = sideData?.ladder || [];

    // Partition regular tiers vs extreme outlier tiers (<=0.5x Bid or >=2x Ask)
    const normalTiers = [];
    const outlierTiers = [];
    const thresholdPrice = bestPrice > 0 ? (isBuy ? bestPrice * 0.5 : bestPrice * 2.0) : 0;

    for (const row of rawLadder) {
      if (bestPrice > 0) {
        if (isBuy && row.p < thresholdPrice - 1e-9) {
          outlierTiers.push(row);
          continue;
        }
        if (!isBuy && row.p >= thresholdPrice - 1e-9) {
          outlierTiers.push(row);
          continue;
        }
      }
      normalTiers.push(row);
    }

    const isFull = isBuy
      ? this.showFullBuyLadder.has(code)
      : this.showFullSellLadder.has(code);

    const selectedSimIdx = isBuy
      ? this.buySimSelection.get(code)
      : this.sellSimSelection.get(code);

    // Ensure if a user selected a tier beyond COMPACT_TIER_LIMIT, it stays visible
    const effectiveLimit =
      selectedSimIdx !== undefined && selectedSimIdx !== null
        ? Math.max(COMPACT_TIER_LIMIT, selectedSimIdx + 1)
        : COMPACT_TIER_LIMIT;

    const visibleTiers = isFull
      ? normalTiers
      : normalTiers.slice(0, effectiveLimit);

    const regularTotalUnits = normalTiers.reduce(
      (sum, r) => sum + Number(r.q || 0),
      0
    );

    const top3Html = participants.length
      ? participants
          .map((p, idx) => {
            const lots = renderTierPills(p.orders, 6);
            const sellerUnits = Number(p.units ?? p.quantity ?? 0);
            const sellerPrimary =
              ppPerUnit > 0
                ? `${formatCompact(sellerUnits * ppPerUnit)} PP`
                : `${formatCompact(sellerUnits)} pcs`;
            const metricRight = isBuy
              ? `<span class="mono text-btc">${formatCompact(p.money_btc ?? p.money)} ₿</span> <span class="text-muted mono">(${formatPct(p.share_pct, 1)})</span>`
              : `<span class="mono text-sell">${sellerPrimary}</span> <span class="text-muted mono">(${formatPct(p.share_pct, 1)})</span>`;

            return `
              <div class="top3-mini-card">
                <div class="top3-mini-main">
                  <div style="display:flex;align-items:center;gap:6px;min-width:0">
                    <span class="pp-badge">#${idx + 1}</span>
                    ${renderEntityInline(p, true)}
                  </div>
                  <div style="flex-shrink:0;font-size:0.76rem">${metricRight}</div>
                </div>
                ${lots ? `<div class="order-pills-row">${lots}</div>` : ''}
              </div>
            `;
          })
          .join('')
      : `<div class="text-muted" style="font-size:0.75rem;padding:4px 0">No active ${isBuy ? 'buy' : 'sell'} orders.</div>`;

    // Build ladder rows with cumulative market depth shading + inline Buyout/Sellout simulator card
    let runningCumQty = 0;
    let runningCumMoney = 0;
    const ladderRowsParts = [];

    visibleTiers.forEach((row, idx) => {
      const qty = Number(row.q || 0);
      const tierMoney = Number(row.m ?? row.p * qty);
      runningCumQty += qty;
      runningCumMoney += tierMoney;

      const depthPct =
        regularTotalUnits > 0
          ? Math.min(100, Math.round((runningCumQty / regularTotalUnits) * 100))
          : 0;

      const isSwept =
        selectedSimIdx !== undefined &&
        selectedSimIdx !== null &&
        idx <= selectedSimIdx;
      const isTarget =
        selectedSimIdx !== undefined &&
        selectedSimIdx !== null &&
        idx === selectedSimIdx;

      const rowClasses = ['ladder-row'];
      if (isSwept) {
        rowClasses.push(isBuy ? 'is-swept-buy' : 'is-swept-sell');
      }
      if (isTarget) {
        rowClasses.push(isBuy ? 'is-target-buy' : 'is-target-sell');
      }

      // Cumulative market volume fill gradient across the full row
      const fillRgba = isBuy
        ? 'rgba(16, 185, 129, 0.18)'
        : 'rgba(56, 189, 248, 0.18)';
      const rowBgStyle = isSwept
        ? ''
        : `style="background: linear-gradient(to right, ${fillRgba} ${depthPct}%, transparent ${depthPct}%);"`;

      const checkmarkHtml = isSwept
        ? `<span class="sim-checkmark ${isBuy ? 'text-buy' : 'text-pp'}">✓</span>`
        : '';

      ladderRowsParts.push(`
        <tr
          class="${rowClasses.join(' ')}"
          ${rowBgStyle}
          data-ladder-tier="${idx}"
          data-ladder-code="${escapeHtml(code)}"
          data-ladder-side="${side}"
          title="Click to simulate ${isBuy ? 'selling down to' : 'buying up to'} ${formatPrice(row.p)} ₿ (Cumulative: ${depthPct}% of book)"
        >
          <td class="${isBuy ? 'text-buy' : 'text-sell'}" style="font-weight:600">
            ${checkmarkHtml}${formatPrice(row.p)} ₿
          </td>
          <td class="text-right">${formatInt(qty)}</td>
          <td class="text-right text-secondary">${formatMoney(tierMoney)} ₿</td>
        </tr>
      `);

      // Inline Buyout / Sellout Summary Row directly underneath the target row
      if (isTarget) {
        const sharePct =
          regularTotalUnits > 0 ? (runningCumQty / regularTotalUnits) * 100 : 0;
        const avgExec = runningCumQty > 0 ? runningCumMoney / runningCumQty : 0;

        ladderRowsParts.push(`
          <tr class="depth-buyout-summary-row ${isBuy ? 'summary-buy' : 'summary-sell'}">
            <td colspan="3" style="padding: 2px 6px 6px;">
              <div class="depth-buyout-card ${isBuy ? 'card-buy' : 'card-sell'}">
                <div class="depth-buyout-card-header">
                  <div class="depth-buyout-card-title">
                    <span>${isBuy ? '⚡' : '🛒'}</span>
                    <strong>${isBuy ? 'Sellout down to' : 'Buyout up to'} ${formatPrice(row.p)} ₿:</strong>
                    <span class="text-muted mono" style="font-size:0.7rem">(Avg: ${formatPrice(avgExec)} ₿)</span>
                  </div>
                  <button
                    type="button"
                    class="depth-buyout-close-btn"
                    data-reset-sim="${escapeHtml(code)}"
                    data-side="${side}"
                  >✕ Dismiss</button>
                </div>
                <div class="depth-buyout-stats-grid">
                  <div class="depth-buyout-stat-box">
                    <div class="depth-buyout-stat-label">${isBuy ? 'Received' : 'Total Cost'}</div>
                    <div class="depth-buyout-stat-val text-btc">${formatMoney(runningCumMoney)} ₿</div>
                  </div>
                  <div class="depth-buyout-stat-box">
                    <div class="depth-buyout-stat-label">${isBuy ? 'Units Sold' : 'Units Bought'}</div>
                    <div class="depth-buyout-stat-val text-buy">${formatInt(runningCumQty)}</div>
                    ${ppPerUnit > 1 ? `<div class="depth-buyout-stat-sub">(${formatCompact(runningCumQty * ppPerUnit)} PP)</div>` : ''}
                  </div>
                  <div class="depth-buyout-stat-box">
                    <div class="depth-buyout-stat-label">${isBuy ? 'Demand Cleared' : 'Market Share'}</div>
                    <div class="depth-buyout-stat-val text-pp">${formatPct(sharePct, 1)}</div>
                  </div>
                </div>
              </div>
            </td>
          </tr>
        `);
      }
    });

    // Grouped 2x+ / 2x- outlier row inside the ladder table (like in v1)
    if (outlierTiers.length > 0 && thresholdPrice > 0) {
      const groupedQty = outlierTiers.reduce((s, t) => s + Number(t.q || 0), 0);
      const groupedCost = isBuy
        ? outlierTiers.reduce((s, t) => s + Number(t.m ?? t.p * t.q), 0)
        : groupedQty * thresholdPrice;
      const badgeLabel = `${isBuy ? '2x-' : '2x+'} (${outlierTiers.length})`;

      ladderRowsParts.push(`
        <tr class="depth-ladder-grouped-row">
          <td style="font-weight:700;color:var(--color-btc-bright)">
            <span>${isBuy ? '≤' : '≥'} ${formatPrice(thresholdPrice)} ₿</span>
            <span class="depth-grouped-badge" title="Grouped ${outlierTiers.length} extreme price tiers">${badgeLabel}</span>
          </td>
          <td class="text-right" style="font-weight:700">${formatInt(groupedQty)}</td>
          <td class="text-right text-secondary" style="font-weight:600">${formatMoney(groupedCost)} ₿</td>
        </tr>
      `);
    }

    const hiddenCount = normalTiers.length - visibleTiers.length;
    const expandBtnHtml =
      normalTiers.length > COMPACT_TIER_LIMIT
        ? `
          <button
            type="button"
            class="ladder-expand-btn"
            data-toggle-ladder="${escapeHtml(code)}"
            data-side="${side}"
          >
            ${
              isFull
                ? `▲ Collapse to Top ${COMPACT_TIER_LIMIT} price tiers`
                : `▼ Show all ${normalTiers.length} price tiers (+${hiddenCount} more)`
            }
          </button>
        `
        : '';

    const colSummaryText = isBuy
      ? `${formatMoney(sideData?.total_money_btc)} ₿ • ${ppPerUnit > 0 ? `${formatCompact(sideData?.total_pp)} PP` : `${formatCompact(sideData?.total_units)} pcs`}`
      : `${ppPerUnit > 0 ? `${formatInt(sideData?.total_pp)} PP` : `${formatInt(sideData?.total_units)} pcs`} • ~${formatMoney(sideData?.total_value_btc)} ₿`;

    return `
      <div class="orderbook-column ${isBuy ? 'buy-col' : 'sell-col'}">
        <div class="ob-col-header">
          <div class="ob-col-title ${isBuy ? 'text-buy' : 'text-sell'}">
            <span>${isBuy ? '🟢 Buy Depth (Bids)' : '🔴 Sell Depth (Asks)'}</span>
          </div>
          <div class="ob-col-summary">
            ${colSummaryText}
          </div>
        </div>

        <div class="top3-strip">
          <div class="top3-strip-label">
            <span>Top 3 ${isBuy ? 'Buyers' : 'Sellers'}</span>
            <span>Top-3 Share: ${formatPct(sideData?.top3_share_pct, 1)}</span>
          </div>
          ${top3Html}
        </div>

        <table class="ladder-table">
          <thead>
            <tr>
              <th style="text-align:left;width:44%">${isBuy ? 'Bid Price ↓' : 'Ask Price ↑'}</th>
              <th style="text-align:right;width:26%">Quantity</th>
              <th style="text-align:right;width:30%">Total (₿)</th>
            </tr>
          </thead>
          <tbody>
            ${
              ladderRowsParts.join('') ||
              `<tr><td colspan="3" class="text-center text-muted" style="padding:16px">Order book empty</td></tr>`
            }
          </tbody>
        </table>
        ${expandBtnHtml}
      </div>
    `;
  }

  renderMobileSplitTBook(code, it) {
    const bestBid = it.best_bid || 0;
    const bestAsk = it.best_ask || 0;
    const bidLimit = bestBid > 0 ? bestBid * 0.5 : 0;
    const askLimit = bestAsk > 0 ? bestAsk * 2.0 : 0;

    const normalBuy = (it.buy?.ladder || []).filter(
      (r) => bidLimit === 0 || r.p >= bidLimit - 1e-9
    );
    const normalSell = (it.sell?.ladder || []).filter(
      (r) => askLimit === 0 || r.p < askLimit - 1e-9
    );

    const buyLadder = normalBuy.slice(0, 10);
    const sellLadder = normalSell.slice(0, 10);
    const maxRows = Math.max(buyLadder.length, sellLadder.length, 1);

    const totalBuyQty = buyLadder.reduce((s, r) => s + Number(r.q || 0), 0) || 1;
    const totalSellQty = sellLadder.reduce((s, r) => s + Number(r.q || 0), 0) || 1;
    let cumBuy = 0;
    let cumSell = 0;

    const rows = [];
    for (let i = 0; i < maxRows; i++) {
      const b = buyLadder[i];
      const s = sellLadder[i];
      if (b) cumBuy += Number(b.q || 0);
      if (s) cumSell += Number(s.q || 0);
      const bPct = b ? Math.min(100, Math.round((cumBuy / totalBuyQty) * 100)) : 0;
      const sPct = s ? Math.min(100, Math.round((cumSell / totalSellQty) * 100)) : 0;

      rows.push(`
        <tr>
          <td class="text-right text-secondary" style="${b ? `background: linear-gradient(to left, rgba(16, 185, 129, 0.14) ${bPct}%, transparent ${bPct}%)` : ''}">${b ? formatCompact(b.q) : '—'}</td>
          <td class="text-right text-buy split-divider" style="font-weight:600">${b ? formatPrice(b.p) : '—'}</td>
          <td class="text-sell" style="font-weight:600">${s ? formatPrice(s.p) : '—'}</td>
          <td class="text-right text-secondary" style="${s ? `background: linear-gradient(to right, rgba(56, 189, 248, 0.14) ${sPct}%, transparent ${sPct}%)` : ''}">${s ? formatCompact(s.q) : '—'}</td>
        </tr>
      `);
    }

    return `
      <table class="split-t-book">
        <thead>
          <tr>
            <th style="text-align:right">Bid Qty</th>
            <th class="split-divider" style="text-align:right;color:var(--color-buy-bright)">Bid ₿</th>
            <th style="text-align:left;color:var(--color-sell-bright)">Ask ₿</th>
            <th style="text-align:right">Ask Qty</th>
          </tr>
        </thead>
        <tbody>
          ${rows.join('')}
        </tbody>
      </table>
    `;
  }

  bindToolbarEvents() {
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

  bindRowAndDrawerEvents(tbody) {
    tbody.querySelectorAll('[data-ob-row]').forEach((row) => {
      row.addEventListener('click', () => {
        const code = row.dataset.obRow;
        if (this.expandedItems.has(code)) {
          this.expandedItems.delete(code);
        } else {
          this.expandedItems.add(code);
        }
        this.renderTableRows();
      });
    });

    tbody.querySelectorAll('[data-switch-code]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const code = btn.dataset.switchCode;
        const mode = btn.dataset.mode;
        this.mobileBookMode.set(code, mode);
        this.renderTableRows();
      });
    });

    tbody.querySelectorAll('[data-toggle-ladder]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const code = btn.dataset.toggleLadder;
        const side = btn.dataset.side;
        const targetSet =
          side === 'buy' ? this.showFullBuyLadder : this.showFullSellLadder;
        if (targetSet.has(code)) {
          targetSet.delete(code);
        } else {
          targetSet.add(code);
        }
        this.renderTableRows();
      });
    });

    tbody.querySelectorAll('[data-ladder-tier]').forEach((tr) => {
      tr.addEventListener('click', (e) => {
        e.stopPropagation();
        const code = tr.dataset.ladderCode;
        const side = tr.dataset.ladderSide;
        const idx = Number(tr.dataset.ladderTier);
        const map = side === 'buy' ? this.buySimSelection : this.sellSimSelection;
        if (map.get(code) === idx) {
          map.delete(code);
        } else {
          map.set(code, idx);
        }
        this.renderTableRows();
      });
    });

    tbody.querySelectorAll('[data-reset-sim]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const code = btn.dataset.resetSim;
        const side = btn.dataset.side;
        if (side === 'buy') this.buySimSelection.delete(code);
        else this.sellSimSelection.delete(code);
        this.renderTableRows();
      });
    });
  }

  setupLazyChart() {
    const chartMount = this.mountEl.querySelector('#orderbook-history-mount');
    if (!chartMount) return;

    observeOnce(chartMount, async () => {
      try {
        const histData = await store.fetchSlice('orderbook_history.json');
        this.chartWidget = new HistoryChartWidget({
          mountEl: chartMount,
          title: 'Order Book History',
          metrics: [
            {
              key: 'liquidity_pct',
              label: 'Liquidity (%)',
              yFormatter: (v) => `${Math.round(Number(v))}%`,
              itemFormatter: (v) => `${Number(v).toFixed(1)}%`,
            },
            {
              key: 'buy_money_btc',
              label: 'Buy (₿)',
              yFormatter: (v) => `${formatCompact(v)} ₿`,
              itemFormatter: (v) => `${formatCompact(v)} ₿`,
            },
            {
              key: 'sell_supply',
              label: 'Sell (PP)',
              getSeries: (seriesObj, meta) =>
                seriesObj.sell_supply ||
                (meta.pp > 0 ? seriesObj.total_pp : seriesObj.total_units) ||
                [],
              yFormatter: (v) => formatCompact(v),
              itemFormatter: (v, meta) =>
                meta.pp > 0 ? `${formatCompact(v)} PP` : `${formatCompact(v)} pcs`,
            },
          ],
          defaultMetric: 'liquidity_pct',
          includeCases: true,
          yFormatter: (v) => formatCompact(v),
        });
        this.chartWidget.setData(histData);
      } catch (err) {
        chartMount.innerHTML = `<div class="skeleton-loader">Failed to load order book history: ${escapeHtml(err.message)}</div>`;
      }
    });
  }
}
