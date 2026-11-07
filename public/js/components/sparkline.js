/**
 * Renders a crisp SVG 7-Day Mini-Sparkline inside expanded item drawers.
 * Supports 1 or 2 series (e.g. Min ₿/PP & Max ₿/PP, or Buy Depth & Sell Depth).
 */
export function renderSparklineSvg({
  seriesA = [],
  seriesB = null,
  colorA = '#10b981',
  colorB = '#38bdf8',
  width = 160,
  height = 40,
}) {
  const cleanA = (seriesA || []).filter((v) => v !== null && v !== undefined && Number.isFinite(Number(v))).map(Number);
  const cleanB = (seriesB || []).filter((v) => v !== null && v !== undefined && Number.isFinite(Number(v))).map(Number);

  const allVals = [...cleanA, ...cleanB];
  if (allVals.length < 2) {
    return `<div class="text-muted mono" style="font-size:0.7rem">Collecting 7d trend...</div>`;
  }

  let minVal = Math.min(...allVals);
  let maxVal = Math.max(...allVals);
  if (minVal === maxVal) {
    minVal *= 0.98;
    maxVal *= 1.02 || 1;
  }
  const range = maxVal - minVal || 1;
  const padY = 4;
  const usableH = height - padY * 2;

  function toPoints(arr) {
    if (arr.length < 2) return '';
    return arr
      .map((val, idx) => {
        const x = (idx / (arr.length - 1)) * width;
        const y = padY + usableH - ((val - minVal) / range) * usableH;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }

  const ptsA = toPoints(cleanA);
  const ptsB = cleanB.length >= 2 ? toPoints(cleanB) : '';

  const areaPointsA = ptsA ? `0,${height} ${ptsA} ${width},${height}` : '';
  const gradId = `spark-grad-${Math.random().toString(36).slice(2, 8)}`;

  return `
    <svg class="sparkline-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${colorA}" stop-opacity="0.28"/>
          <stop offset="100%" stop-color="${colorA}" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      ${areaPointsA ? `<polygon points="${areaPointsA}" fill="url(#${gradId})" />` : ''}
      ${ptsB ? `<polyline fill="none" stroke="${colorB}" stroke-width="1.5" stroke-dasharray="2,2" points="${ptsB}" />` : ''}
      ${ptsA ? `<polyline fill="none" stroke="${colorA}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" points="${ptsA}" />` : ''}
    </svg>
  `;
}

