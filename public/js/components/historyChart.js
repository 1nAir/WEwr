import { store } from '../store.js';
import { escapeHtml, renderItemName } from '../utils/format.js';

const CANONICAL_LINE_ORDER = [
  'fish', 'cookedFish',
  'livestock', 'steak',
  'grain', 'bread',
  'coca', 'cocaine',
  'petroleum', 'oil',
  'lead', 'lightAmmo', 'ammo', 'heavyAmmo',
  'iron', 'steel',
  'limestone', 'concrete',
  'wood', 'paper',
  'case1', 'case2', 'case3', 'scraps',
];

/**
 * Reusable Historical Chart.js Manager:
 * - Period Filters (24H, 3D, 7D, All Time) & Metric Switchers
 * - Custom Vertical Crosshair + Multi-Column Desktop Floating Tooltip (never clipped)
 * - Mobile Touch Scrubbing Readout + Interactive Icon Chip Grid with Live Values
 *   sorted by Production Line, with a single Toggle All switch placed first.
 */
export class HistoryChartWidget {
  constructor({
    mountEl,
    title,
    periods = [
      { key: '24h', label: '24H', hours: 24 },
      { key: '3d', label: '3D', hours: 72 },
      { key: '7d', label: '7D', hours: 168 },
      { key: 'all', label: 'All Time', hours: 0 },
    ],
    metrics = [],
    defaultPeriod = '24h',
    defaultMetric = '',
    includeCases = false,
    yFormatter = (v) => v,
  }) {
    this.mountEl = mountEl;
    this.title = title;
    this.periods = periods;
    this.metrics = metrics;
    this.activePeriod = defaultPeriod;
    this.activeMetric = defaultMetric || (metrics[0] && metrics[0].key) || '';
    this.includeCases = includeCases;
    this.yFormatter = yFormatter;

    this.historyData = null;
    this.chartInstance = null;
    this.hiddenItems = new Set();
    this.activeHoverIndex = null;
    this.currentSlicedLabels = [];
    this.currentDatasets = [];
  }

  setData(historyData) {
    this.historyData = historyData;
    this.renderShell();
    this.updateChart();
  }

  getAvailableItemCodes() {
    const itemsMap = (this.historyData && this.historyData.items) || {};
    const prodLines = store.meta && store.meta.production_lines;
    const orderedRef = prodLines
      ? Object.values(prodLines).flat()
      : CANONICAL_LINE_ORDER;
    const orderIdx = new Map(orderedRef.map((c, idx) => [c, idx]));

    return Object.keys(itemsMap)
      .filter((code) => {
        const meta = store.getItemMeta(code);
        return this.includeCases || meta.pp > 0;
      })
      .sort((a, b) => {
        const idxA = orderIdx.has(a) ? orderIdx.get(a) : 999;
        const idxB = orderIdx.has(b) ? orderIdx.get(b) : 999;
        return idxA - idxB;
      });
  }

  getActiveMetricDef() {
    return (
      this.metrics.find((m) => m.key === this.activeMetric) ||
      this.metrics[0] ||
      null
    );
  }

  resolveItemSeries(seriesObj, meta) {
    if (!seriesObj) return [];
    const mDef = this.getActiveMetricDef();
    if (mDef && typeof mDef.getSeries === 'function') {
      return mDef.getSeries(seriesObj, meta) || [];
    }
    return seriesObj[this.activeMetric] || [];
  }

  formatAxisVal(v) {
    const mDef = this.getActiveMetricDef();
    if (mDef && typeof mDef.yFormatter === 'function') {
      return mDef.yFormatter(v);
    }
    return this.yFormatter(v);
  }

  formatItemVal(v, meta) {
    const mDef = this.getActiveMetricDef();
    if (mDef && typeof mDef.itemFormatter === 'function') {
      return mDef.itemFormatter(v, meta);
    }
    if (mDef && typeof mDef.yFormatter === 'function') {
      return mDef.yFormatter(v);
    }
    return this.yFormatter(v);
  }

  getLatestValueForCode(code) {
    const itemsMap = (this.historyData && this.historyData.items) || {};
    const meta = store.getItemMeta(code);
    const arr = this.resolveItemSeries(itemsMap[code], meta);
    for (let i = arr.length - 1; i >= 0; i--) {
      const v = arr[i];
      if (v !== null && v !== undefined && v !== 0) {
        return Number(v);
      }
    }
    return 0;
  }

  renderShell() {
    if (!this.mountEl) return;

    const periodBtns = this.periods
      .map(
        (p) => `
        <button type="button" class="filter-pill ${p.key === this.activePeriod ? 'active' : ''}" data-period="${p.key}">
          ${escapeHtml(p.label)}
        </button>`
      )
      .join('');

    const metricBtns = this.metrics
      .map(
        (m) => `
        <button type="button" class="filter-pill ${m.key === this.activeMetric ? 'active' : ''}" data-metric="${m.key}">
          ${escapeHtml(m.label)}
        </button>`
      )
      .join('');

    const itemCodes = this.getAvailableItemCodes();
    const allHidden = itemCodes.length > 0 && this.hiddenItems.size >= itemCodes.length;

    const toggleAllBtnHtml = `
      <button
        type="button"
        class="chart-item-chip chart-toggle-all-chip ${allHidden ? 'is-hidden' : ''}"
        data-action="toggle-all"
        title="Click to toggle all items ON / OFF"
      >
        <span class="chart-chip-bar" style="background:var(--accent-primary)"></span>
        <span class="chart-chip-name">⚡ Toggle All</span>
      </button>
    `;

    const chipsHtml = itemCodes
      .map((code) => {
        const meta = store.getItemMeta(code);
        const isHidden = this.hiddenItems.has(code);
        const latestVal = this.getLatestValueForCode(code);
        return `
          <button
            type="button"
            class="chart-item-chip ${isHidden ? 'is-hidden' : ''}"
            data-item-code="${escapeHtml(code)}"
            style="--chip-color: ${escapeHtml(meta.color)}"
            title="Click to toggle • Double-click to isolate ${escapeHtml(meta.name)}"
          >
            <span class="chart-chip-bar" style="background:${escapeHtml(meta.color)}"></span>
            <img src="assets/${escapeHtml(code)}.webp" alt="" class="chart-chip-icon" loading="lazy" />
            <span class="chart-chip-name">${renderItemName(meta)}</span>
            <span class="chart-chip-val mono" data-chip-val="${escapeHtml(code)}">
              ${latestVal ? escapeHtml(this.formatItemVal(latestVal, meta)) : '—'}
            </span>
          </button>
        `;
      })
      .join('');

    this.mountEl.innerHTML = `
      <div class="chart-panel">
        <div class="chart-header">
          <div class="chart-title-group">
            <div class="chart-title">${escapeHtml(this.title)}</div>
            <span class="chart-scrub-badge mono" data-role="scrub-time">Latest Snapshot</span>
          </div>
          <div class="chart-controls">
            <div class="filter-pills" data-role="periods">${periodBtns}</div>
            <div class="filter-pills" data-role="metrics">${metricBtns}</div>
          </div>
        </div>

        <div class="chart-canvas-container" data-role="canvas-wrap">
          <canvas data-role="canvas"></canvas>
          <div class="chart-html-tooltip" data-role="html-tooltip" hidden></div>
        </div>

        <!-- Compact Interactive Item Chips with Live Scrubbed Values -->
        <div class="chart-chips-grid" data-role="chips-grid">
          ${toggleAllBtnHtml}
          ${chipsHtml}
        </div>
      </div>
    `;

    this.bindEvents();
  }

  bindEvents() {
    this.mountEl.querySelectorAll('[data-period]').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.activePeriod = btn.dataset.period;
        this.mountEl
          .querySelectorAll('[data-period]')
          .forEach((b) => b.classList.toggle('active', b === btn));
        this.updateChart();
      });
    });

    this.mountEl.querySelectorAll('[data-metric]').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.activeMetric = btn.dataset.metric;
        this.mountEl
          .querySelectorAll('[data-metric]')
          .forEach((b) => b.classList.toggle('active', b === btn));
        this.updateChart();
        this.updateChipValues(null);
      });
    });

    const btnToggleAll = this.mountEl.querySelector('[data-action="toggle-all"]');
    if (btnToggleAll) {
      btnToggleAll.addEventListener('click', () => {
        const allCodes = this.getAvailableItemCodes();
        if (this.hiddenItems.size === 0) {
          allCodes.forEach((c) => this.hiddenItems.add(c));
        } else {
          this.hiddenItems.clear();
        }
        this.syncChipClasses();
        this.updateChart();
      });
    }

    this.mountEl.querySelectorAll('[data-item-code]').forEach((el) => {
      const code = el.dataset.itemCode;
      el.addEventListener('click', () => {
        if (this.hiddenItems.has(code)) {
          this.hiddenItems.delete(code);
        } else {
          this.hiddenItems.add(code);
        }
        this.syncChipClasses();
        this.updateChart();
      });

      el.addEventListener('dblclick', (e) => {
        e.preventDefault();
        const allCodes = this.getAvailableItemCodes();
        allCodes.forEach((c) => {
          if (c !== code) this.hiddenItems.add(c);
        });
        this.hiddenItems.delete(code);
        this.syncChipClasses();
        this.updateChart();
      });
    });

    const canvasWrap = this.mountEl.querySelector('[data-role="canvas-wrap"]');
    if (canvasWrap) {
      canvasWrap.addEventListener('mouseleave', () => {
        this.hideExternalTooltip();
        this.updateChipValues(null);
      });
    }
  }

  syncChipClasses() {
    this.mountEl.querySelectorAll('[data-item-code]').forEach((el) => {
      el.classList.toggle('is-hidden', this.hiddenItems.has(el.dataset.itemCode));
    });
    const btnToggleAll = this.mountEl.querySelector('[data-action="toggle-all"]');
    if (btnToggleAll) {
      const allCodes = this.getAvailableItemCodes();
      btnToggleAll.classList.toggle(
        'is-hidden',
        allCodes.length > 0 && this.hiddenItems.size >= allCodes.length
      );
    }
  }

  updateChipValues(dataIndex = null) {
    const scrubTimeEl = this.mountEl.querySelector('[data-role="scrub-time"]');
    if (dataIndex === null || !this.currentSlicedLabels.length) {
      if (scrubTimeEl) {
        scrubTimeEl.textContent = 'Latest Snapshot';
        scrubTimeEl.classList.remove('is-scrubbing');
      }
      for (const ds of this.currentDatasets) {
        const valEl = this.mountEl.querySelector(`[data-chip-val="${ds.itemCode}"]`);
        if (!valEl) continue;
        const meta = store.getItemMeta(ds.itemCode);
        let lastVal = null;
        for (let i = ds.data.length - 1; i >= 0; i--) {
          if (ds.data[i] !== null && ds.data[i] !== undefined) {
            lastVal = ds.data[i];
            break;
          }
        }
        valEl.textContent = lastVal !== null ? this.formatItemVal(lastVal, meta) : '—';
      }
      return;
    }

    if (scrubTimeEl) {
      scrubTimeEl.textContent = `📍 ${this.currentSlicedLabels[dataIndex] || ''}`;
      scrubTimeEl.classList.add('is-scrubbing');
    }

    for (const ds of this.currentDatasets) {
      const valEl = this.mountEl.querySelector(`[data-chip-val="${ds.itemCode}"]`);
      if (!valEl) continue;
      const meta = store.getItemMeta(ds.itemCode);
      const v = ds.data[dataIndex];
      valEl.textContent = v !== null && v !== undefined ? this.formatItemVal(v, meta) : '—';
    }
  }

  hideExternalTooltip() {
    const tooltipEl = this.mountEl.querySelector('[data-role="html-tooltip"]');
    if (tooltipEl) {
      tooltipEl.hidden = true;
    }
  }

  renderExternalTooltip(context) {
    const { chart, tooltip } = context;
    const tooltipEl = this.mountEl.querySelector('[data-role="html-tooltip"]');
    if (!tooltipEl) return;

    if (tooltip.opacity === 0 || !tooltip.dataPoints || !tooltip.dataPoints.length) {
      tooltipEl.hidden = true;
      this.updateChipValues(null);
      return;
    }

    const dataIndex = tooltip.dataPoints[0].dataIndex;
    this.updateChipValues(dataIndex);

    const isMobile = window.innerWidth <= 768;
    const visiblePoints = tooltip.dataPoints
      .filter((dp) => dp.raw !== null && dp.raw !== undefined)
      .sort((a, b) => Number(b.raw) - Number(a.raw));

    // On mobile, if more than 4 lines are active, don't cover the chart with a big box —
    // the live values update directly in the commodity chips below and header badge above!
    if (isMobile && visiblePoints.length > 4) {
      tooltipEl.hidden = true;
      return;
    }

    const title = tooltip.title?.[0] || '';
    const rowsHtml = visiblePoints
      .map((dp) => {
        const code = dp.dataset.itemCode;
        const meta = store.getItemMeta(code);
        return `
          <div class="chart-tt-item">
            <span class="chart-tt-left">
              <span class="chart-tt-dot" style="background:${escapeHtml(meta.color)}"></span>
              <span class="chart-tt-name">${escapeHtml(meta.short || meta.name)}</span>
            </span>
            <span class="chart-tt-val mono">${escapeHtml(this.formatItemVal(dp.raw, meta))}</span>
          </div>
        `;
      })
      .join('');

    const useTwoCols = !isMobile && visiblePoints.length > 6;
    tooltipEl.innerHTML = `
      <div class="chart-tt-header mono">${escapeHtml(title)}</div>
      <div class="chart-tt-grid ${useTwoCols ? 'two-cols' : 'one-col'}">
        ${rowsHtml}
      </div>
    `;
    tooltipEl.hidden = false;

    const canvasWidth = chart.width || 600;
    const caretX = tooltip.caretX || 0;
    if (isMobile) {
      tooltipEl.style.left = '8px';
      tooltipEl.style.right = 'auto';
      tooltipEl.style.top = '8px';
    } else if (caretX > canvasWidth * 0.52) {
      tooltipEl.style.left = '14px';
      tooltipEl.style.right = 'auto';
      tooltipEl.style.top = '10px';
    } else {
      tooltipEl.style.left = 'auto';
      tooltipEl.style.right = '14px';
      tooltipEl.style.top = '10px';
    }
  }

  updateChart() {
    if (!this.historyData || !window.Chart) return;
    const rawLabels = this.historyData.labels || [];
    const itemsMap = this.historyData.items || {};
    if (!rawLabels.length) return;

    const pObj = this.periods.find((p) => p.key === this.activePeriod) || this.periods[0];
    const latestTs = rawLabels[rawLabels.length - 1];
    const cutoffTs = pObj.hours > 0 ? latestTs - pObj.hours * 3600 : 0;

    let startIdx = 0;
    if (cutoffTs > 0) {
      const found = rawLabels.findIndex((ts) => ts >= cutoffTs);
      startIdx = found >= 0 ? found : Math.max(0, rawLabels.length - 48);
    }

    const slicedTimestamps = rawLabels.slice(startIdx);
    const slicedLabels = slicedTimestamps.map((ts) => {
      const d = new Date(ts * 1000);
      const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
      if (pObj.hours > 0 && pObj.hours <= 24) {
        return timeStr;
      }
      const dateStr = d.toLocaleDateString([], { month: 'short', day: 'numeric' });
      return `${dateStr}, ${timeStr}`;
    });

    const isMobile = typeof window !== 'undefined' && window.innerWidth <= 768;
    const formatTick = (val) => {
      const ts = slicedTimestamps[val];
      if (!ts) return '';
      const d = new Date(ts * 1000);
      if (pObj.hours > 0 && pObj.hours <= 24) {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
      }
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    };

    const datasets = [];
    for (const [code, seriesObj] of Object.entries(itemsMap)) {
      const meta = store.getItemMeta(code);
      if (!this.includeCases && meta.pp === 0) continue;
      const rawSeries = this.resolveItemSeries(seriesObj, meta);
      if (!rawSeries.length) continue;

      const slicedValues = rawSeries
        .slice(startIdx)
        .map((v) => (v === 0 || v === null || v === undefined ? null : Number(v)));

      datasets.push({
        label: meta.name,
        itemCode: code,
        data: slicedValues,
        borderColor: meta.color,
        backgroundColor: meta.color,
        borderWidth: 1.8,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.25,
        spanGaps: true,
        hidden: this.hiddenItems.has(code),
      });
    }

    this.currentSlicedLabels = slicedLabels;
    this.currentDatasets = datasets;
    this.updateChipValues(null);

    const canvas = this.mountEl.querySelector('[data-role="canvas"]');
    if (!canvas) return;

    if (this.chartInstance) {
      this.chartInstance.data.labels = slicedLabels;
      this.chartInstance.data.datasets = datasets;
      this.chartInstance.options.scales.x.ticks.maxTicksLimit = isMobile ? 4 : 7;
      this.chartInstance.options.scales.x.ticks.callback = (val) => formatTick(val);
      this.chartInstance.options.scales.y.ticks.callback = (v) => this.formatAxisVal(v);
      this.chartInstance.update('none');
      return;
    }

    const crosshairPlugin = {
      id: 'verticalCrosshair',
      afterDraw: (chart) => {
        if (chart.tooltip?._active && chart.tooltip._active.length) {
          const activePoint = chart.tooltip._active[0];
          const ctx = chart.ctx;
          const x = activePoint.element.x;
          const topY = chart.scales.y.top;
          const bottomY = chart.scales.y.bottom;

          ctx.save();
          ctx.beginPath();
          ctx.moveTo(x, topY);
          ctx.lineTo(x, bottomY);
          ctx.lineWidth = 1;
          ctx.strokeStyle = 'rgba(148, 163, 184, 0.35)';
          ctx.setLineDash([4, 4]);
          ctx.stroke();
          ctx.restore();
        }
      },
    };

    this.chartInstance = new window.Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: slicedLabels,
        datasets,
      },
      plugins: [crosshairPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            enabled: false,
            external: (ctx) => this.renderExternalTooltip(ctx),
          },
        },
        scales: {
          x: {
            grid: { color: 'rgba(255, 255, 255, 0.04)' },
            ticks: {
              color: '#64748b',
              maxRotation: 0,
              minRotation: 0,
              autoSkip: true,
              maxTicksLimit: isMobile ? 4 : 7,
              font: { family: 'JetBrains Mono', size: 10 },
              callback: (val) => formatTick(val),
            },
          },
          y: {
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: {
              color: '#94a3b8',
              font: { family: 'JetBrains Mono', size: 11 },
              callback: (v) => this.formatAxisVal(v),
            },
          },
        },
      },
    });
  }
}
