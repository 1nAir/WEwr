import { escapeHtml } from '../utils/format.js';

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

