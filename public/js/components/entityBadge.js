import { escapeHtml, formatCompact, formatPrice, formatInt } from '../utils/format.js';

const DEFAULT_AVATAR = 'assets/guide.webp';

export function renderEntityInline(entity, showTypeBadge = true) {
  if (!entity) return '<span class="text-muted">Unknown</span>';
  const name = escapeHtml(entity.name || 'Unknown');
  const type = String(entity.type || 'user').toLowerCase();
  const profileUrl = escapeHtml(
    entity.profile_url || `https://app.warera.io/${type}/${entity.id || ''}`
  );
  const avatarUrl = entity.avatar_url ? escapeHtml(entity.avatar_url) : DEFAULT_AVATAR;
  const isFlag = type === 'country';

  const badgeHtml = showTypeBadge
    ? `<span class="entity-type-tag type-${escapeHtml(type)}">${escapeHtml(type.toUpperCase())}</span>`
    : '';

  return `
    <span class="entity-inline">
      <img
        src="${avatarUrl}"
        alt=""
        class="entity-avatar ${isFlag ? 'flag' : ''}"
        loading="lazy"
        onerror="this.onerror=null;this.src='${DEFAULT_AVATAR}';"
      />
      <a
        href="${profileUrl}"
        target="_blank"
        rel="noopener noreferrer"
        class="entity-name-link"
        onclick="event.stopPropagation();"
      >${name}</a>
      ${badgeHtml}
    </span>
  `;
}

export function renderTierPills(orders, maxTiers = 6) {
  if (!Array.isArray(orders) || orders.length === 0) return '';

  if (orders.length <= maxTiers) {
    return orders
      .map(
        (o) =>
          `<span class="order-lot-pill">${formatCompact(o.quantity ?? o.q)} @ ${formatPrice(o.price ?? o.p)} ₿</span>`
      )
      .join('');
  }

  // More than maxTiers: pick the top tiers by volume
  const sorted = [...orders].sort(
    (a, b) => Number(b.quantity ?? b.q ?? 0) - Number(a.quantity ?? a.q ?? 0)
  );
  const top = sorted.slice(0, maxTiers);
  const rest = sorted.slice(maxTiers);

  // Sort top tiers by price ascending for consistent financial display
  top.sort((a, b) => Number(a.price ?? a.p ?? 0) - Number(b.price ?? b.p ?? 0));

  let restUnits = 0;
  let restMoney = 0;
  for (const o of rest) {
    const q = Number(o.quantity ?? o.q ?? 0);
    const p = Number(o.price ?? o.p ?? 0);
    restUnits += q;
    restMoney += p * q;
  }
  const restAvgPrice = restUnits > 0 ? restMoney / restUnits : 0;

  const topPills = top
    .map(
      (o) =>
        `<span class="order-lot-pill">${formatCompact(o.quantity ?? o.q)} @ ${formatPrice(o.price ?? o.p)} ₿</span>`
    )
    .join('');

  const otherPill = `<span class="order-lot-pill order-lot-pill-other" title="${rest.length} other price tiers: ${formatInt(restUnits)} pcs (total: ${formatCompact(restMoney)} ₿)">Other (${rest.length}): ${formatCompact(restUnits)} @ ~${formatPrice(restAvgPrice)} ₿</span>`;

  return `${topPills}${otherPill}`;
}
