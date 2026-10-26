/**
 * Declarative Configuration & Extensible Section Registry for Wealthrate v2.0.
 * To add a new top-level section in the future (e.g. Companies after game patch),
 * simply register it in NAV_SECTIONS.
 */
export const NAV_SECTIONS = [
  {
    id: 'profitability',
    label: 'Profitability',
    dataSlice: 'profitability.json',
    historySlice: 'profitability_history.json',
  },
  {
    id: 'market',
    label: 'Market',
    subtabs: ['orderbook', 'trades', 'leaderboards'],
  },
];

/**
 * Temporary red notice banner shown at the top of the FAQ modal.
 * Remove or set to '' when no longer needed.
 */
const TEMP_NOTICE_BANNER = `
  <div style="padding:10px 12px;border-radius:6px;background:rgba(244,63,94,0.12);border:1px solid rgba(244,63,94,0.45);color:#fb7185;font-size:0.82rem;line-height:1.45;font-weight:600">
    ⚠️ Since the game update heavily affected 3 out of 4 old tabs, everything was rebuilt from scratch for the current mechanics. I plan to bring back the Companies tab later. Some bugs may occur in the meantime.
  </div>
`;

export const GUIDE_CONTENT = {
  profitability: `
    ${TEMP_NOTICE_BANNER}
    <div style="display:flex;flex-direction:column;gap:8px;font-size:0.83rem">
      <div><strong class="text-pp">Min ₿/PP (Fast Trade)</strong> — Net profit per 1 PP when buying raw materials from Top-3 Sell orders (Ask) and selling product into Top-3 Buy orders (Bid).</div>
      <div><strong class="text-buy">Max ₿/PP (Own Orders)</strong> — Net profit per 1 PP when buying raw materials via Top-3 Buy orders (Bid) and selling product via Top-3 Sell orders (Ask).</div>
    </div>
  `,
  orderbook: `
    ${TEMP_NOTICE_BANNER}
    <div style="display:flex;flex-direction:column;gap:8px;font-size:0.83rem">
      <div><strong class="text-buy">🟢 Buy Depth (Bids)</strong> — Active buy orders sorted by total ₿ locked on the market. Click any price row to simulate selling into buy orders down to that price.</div>
      <div><strong class="text-sell">🔴 Sell Depth (Asks)</strong> — Active sell orders sorted by total PP listed on the market. Click any price row to simulate buying out the market up to that price.</div>
      <div class="text-muted" style="font-size:0.78rem">Extreme orders (≥2x Ask or ≤0.5x Bid) are grouped at the bottom of the ladder.</div>
    </div>
  `,
  trades: `
    ${TEMP_NOTICE_BANNER}
    <div style="display:flex;flex-direction:column;gap:8px;font-size:0.83rem">
      <div><strong>VWAP (₿)</strong> — Volume-Weighted Average Price (<code>Total ₿ Turnover ÷ Total Units</code>).</div>
      <div><strong class="text-btc">★ POC</strong> — Point of Control: the price tier with the largest traded volume.</div>
    </div>
  `,
  leaderboards: `
    ${TEMP_NOTICE_BANNER}
    <div style="display:flex;flex-direction:column;gap:8px;font-size:0.83rem">
      <div><strong class="text-pp">Live Sell / Live Buy</strong> — Top-25 holders of active market orders right now.</div>
      <div><strong class="text-btc">Top Buyers / Top Sellers (₿)</strong> — Top-25 traders by completed trade volume (₿) for the selected time window.</div>
    </div>
  `,
};
