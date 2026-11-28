/**
 * Numeric, Currency, Percentage & Relative Time Formatters.
 */

export function formatPrice(val, decimals = 3) {
  const n = Number(val);
  if (!Number.isFinite(n) || n === 0) return '—';
  return n.toFixed(Math.min(decimals, 3));
}

export function formatPPPrice(val) {
  const n = Number(val);
  if (!Number.isFinite(n)) return '—';
  return n.toFixed(3);
}

export function formatInt(val) {
  const n = Math.round(Number(val) || 0);
  return n.toLocaleString('en-US');
}

export function formatMoney(val, decimals = 2) {
  const n = Number(val) || 0;
  return n.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatCompact(val, decimals = 1) {
  const n = Number(val) || 0;
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(decimals)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(decimals)}M`;
  if (abs >= 1e4) return `${(n / 1e3).toFixed(decimals)}K`;
  if (Number.isInteger(n)) return n.toLocaleString('en-US');
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

export function formatPct(val, decimals = 1) {
  const n = Number(val) || 0;
  return `${n.toFixed(decimals)}%`;
}

export function timeAgo(unixSeconds) {
  if (!unixSeconds) return 'just now';
  const ts = unixSeconds > 1e12 ? Math.floor(unixSeconds / 1000) : unixSeconds;
  const now = Math.floor(Date.now() / 1000);
  // Handle synthetic/future test timestamps gracefully
  const diff = Math.max(0, now - ts);
  if (diff < 60) return 'just now';
  const mins = Math.floor(diff / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  if (hours < 24) return remMins > 0 ? `${hours}h ${remMins}m ago` : `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatIsoShort(isoStr) {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
}

export function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Renders full item name on desktop and short name (from config.py) on mobile (<= 768px).
 */
export function renderItemName(meta) {
  const full = escapeHtml(meta?.name || '');
  const short = escapeHtml(meta?.short || meta?.name || '');
  if (full === short) return `<span>${full}</span>`;
  return `<span class="item-name-full">${full}</span><span class="item-name-short">${short}</span>`;
}

export function formatDateShort(dateStr) {
  if (!dateStr) return '';
  const parts = String(dateStr).split('-');
  if (parts.length < 3) return dateStr;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const m = parseInt(parts[1], 10) - 1;
  const d = parseInt(parts[2], 10);
  return `${months[m] || parts[1]} ${d}`;
}

export function formatDateRange(startStr, endStr) {
  if (!startStr || !endStr) return '';
  if (startStr === endStr) return formatDateShort(startStr);
  const s = formatDateShort(startStr);
  const e = formatDateShort(endStr);
  const sParts = s.split(' ');
  const eParts = e.split(' ');
  if (sParts[0] === eParts[0]) {
    return `${sParts[0]} ${sParts[1]}–${eParts[1]}`;
  }
  return `${s}–${e}`;
}
