const won = new Intl.NumberFormat('ko-KR', {
  style: 'currency', currency: 'KRW', maximumFractionDigits: 0,
});
const integer = new Intl.NumberFormat('ko-KR');

const state = {
  user: null,
  authMode: 'login',
  ticker: '005930',
  side: 'buy',
  data: null,
  countdownEnd: 0,
  refreshing: false,
  chartPointLimit: 20,
  marketRandomizeUnlocked: false,
  randomNewsInitialized: false,
  lastRandomNewsId: 0,
  positionSort: { key: null, direction: 'asc' },
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

function signedPercent(value) {
  const number = Number(value || 0);
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`;
}

function formatVolume(value) {
  const number = Number(value || 0);
  if (number >= 100_000_000) return `${(number / 100_000_000).toFixed(1)}억`;
  if (number >= 10_000) return `${(number / 10_000).toFixed(1)}만`;
  return integer.format(number);
}

function withVirtualVolume(point) {
  if (Number(point.volume) > 0) return point;
  const price = Math.max(1, Number(point.price || 1));
  const change = Number(point.change_pct || 0);
  const activity = point.event_type === 'news'
    ? 5
    : .8 + Math.min(1, Math.abs(change) / 7) * 1.2;
  const volume = Math.max(100, Math.round(4_000_000_000 / price * activity));
  let imbalance = Math.min(.9, Math.abs(change) / 7 * .68);
  if (change < 0) imbalance *= -1;
  const buyVolume = Math.round(volume * (1 + imbalance) / 2);
  return {
    ...point,
    buy_volume: buyVolume,
    sell_volume: volume - buyVolume,
    volume,
  };
}

function directionClass(value) {
  return Number(value) > 0 ? 'is-up' : Number(value) < 0 ? 'is-down' : 'is-flat';
}

function formatTime(value, seconds = true) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('ko-KR', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    second: seconds ? '2-digit' : undefined, hour12: false,
  });
}

function currentStock() {
  return state.data?.stocks.find((stock) => stock.ticker === state.ticker);
}

function syncMarketActionLock() {
  const button = $('#randomize-market');
  button.disabled = !state.marketRandomizeUnlocked;
  button.title = state.marketRandomizeUnlocked
    ? '전 종목 가격을 새 기준가로 재설정'
    : '전 종목 매도 후 사용할 수 있습니다';
}

function apiErrorMessage(data, fallback) {
  if (typeof data?.detail === 'string') return data.detail;
  if (Array.isArray(data?.detail)) return data.detail.map((item) => item.msg).join(', ');
  return fallback;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(apiErrorMessage(data, `요청 실패 (${response.status})`));
    error.status = response.status;
    throw error;
  }
  return data;
}

function toast(message, type = 'success') {
  const element = $('#toast');
  element.textContent = message;
  element.className = `toast ${type}`;
  element.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { element.hidden = true; }, 4300);
}

function setAuthMode(mode) {
  const registering = mode === 'register';
  state.authMode = registering ? 'register' : 'login';
  $('#auth-title').textContent = registering ? '회원가입' : '로그인';
  $('#auth-description').textContent = registering
    ? '아이디별로 계좌와 거래 내역이 저장됩니다.'
    : '내 계좌와 거래 내역을 불러옵니다.';
  $('#auth-submit').textContent = registering ? '회원가입' : '로그인';
  $('#auth-switch-copy').textContent = registering ? '이미 계정이 있으신가요?' : '계정이 없으신가요?';
  $('#auth-switch').textContent = registering ? '로그인' : '회원가입';
  $('#auth-confirm-field').hidden = !registering;
  $('#auth-password-confirm').required = registering;
  $('#auth-password').autocomplete = registering ? 'new-password' : 'current-password';
  $('#auth-error').hidden = true;
}

function showAuthModal(mode = 'login') {
  const modal = $('#auth-modal');
  const backdrop = $('#auth-backdrop');
  clearTimeout(hideAuthModal.timer);
  setAuthMode(mode);
  $('#auth-password').value = '';
  $('#auth-password-confirm').value = '';
  backdrop.hidden = false;
  modal.hidden = false;
  requestAnimationFrame(() => {
    backdrop.classList.add('visible');
    modal.classList.add('visible');
    $('#auth-username').focus();
  });
}

function hideAuthModal() {
  const modal = $('#auth-modal');
  const backdrop = $('#auth-backdrop');
  modal.classList.remove('visible');
  backdrop.classList.remove('visible');
  clearTimeout(hideAuthModal.timer);
  hideAuthModal.timer = setTimeout(() => {
    modal.hidden = true;
    backdrop.hidden = true;
  }, 200);
}

function renderAuth() {
  const authenticated = Boolean(state.user);
  $('#auth-actions').hidden = authenticated;
  $('#member-actions').hidden = !authenticated;
  if (authenticated) {
    $('#header-user').textContent = state.user.username;
    $('#header-avatar').textContent = state.user.username.slice(0, 1).toUpperCase();
  }
  setSide(state.side);
}

async function initializeAuth() {
  try {
    const result = await api('/api/auth/me');
    state.user = result.user;
  } catch (error) {
    state.user = null;
  }
  renderAuth();
  await refresh();
}

function hideNewsPopup() {
  const popup = $('#random-news-popup');
  const backdrop = $('#random-news-backdrop');
  popup.classList.remove('visible');
  backdrop.classList.remove('visible');
  clearTimeout(hideNewsPopup.timer);
  hideNewsPopup.timer = setTimeout(() => {
    popup.hidden = true;
    backdrop.hidden = true;
  }, 220);
}

function showNewsPopup(item) {
  const popup = $('#random-news-popup');
  const backdrop = $('#random-news-backdrop');
  clearTimeout(hideNewsPopup.timer);
  $('#random-news-stock').textContent = item.applied_at
    ? (item.stock_name || '전체 시장')
    : `영향 종목 ${item.affected_tickers?.length || '전체'}개 · 반영 후 공개`;
  $('#random-news-time').textContent = formatTime(item.published_at);
  const status = $('#random-news-status');
  status.textContent = item.applied_at ? '가격 반영 완료' : '가격 반영 예정';
  status.className = item.applied_at ? 'applied' : 'pending';
  $('#random-news-title').textContent = item.title;
  $('#random-news-content').textContent = item.content || '등록된 뉴스 내용이 없습니다.';
  const impact = $('#random-news-impact');
  impact.textContent = item.applied_at ? signedPercent(item.impact_pct) : '반영 후 공개';
  impact.className = item.applied_at ? directionClass(item.impact_pct) : 'pending';
  backdrop.hidden = false;
  popup.hidden = false;
  requestAnimationFrame(() => {
    backdrop.classList.add('visible');
    popup.classList.add('visible');
    $('#random-news-close').focus();
  });
}

function detectRandomNews(news) {
  const latest = news.find((item) => item.source === 'random');
  if (!state.randomNewsInitialized) {
    const stored = localStorage.getItem('market_lab_last_random_news_id');
    state.lastRandomNewsId = stored === null ? (latest?.id || 0) : Number(stored || 0);
    state.randomNewsInitialized = true;
    if (stored === null) {
      localStorage.setItem('market_lab_last_random_news_id', String(state.lastRandomNewsId));
      return;
    }
  }
  if (!latest || latest.id <= state.lastRandomNewsId) return;
  state.lastRandomNewsId = latest.id;
  localStorage.setItem('market_lab_last_random_news_id', String(latest.id));
  showNewsPopup(latest);
}

function openSelectedNews(event) {
  const itemElement = event.target.closest('[data-news-id]');
  if (!itemElement || !state.data) return;
  const item = state.data.news.find((newsItem) => newsItem.id === Number(itemElement.dataset.newsId));
  if (item) showNewsPopup(item);
}

function openSelectedNewsWithKeyboard(event) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  openSelectedNews(event);
}

function renderSummary() {
  const portfolio = state.data.portfolio;
  $('#total-assets').textContent = won.format(portfolio.total_assets);
  $('#cash').textContent = won.format(portfolio.cash);
  $('#stock-value').textContent = won.format(portfolio.stock_value);
  $('#position-count').textContent = `보유 종목 ${portfolio.positions.length}개`;
  $('#return-rate').textContent = signedPercent(portfolio.total_profit_pct);
  $('#return-rate').className = directionClass(portfolio.total_profit_pct);
  const profit = $('#total-profit');
  profit.textContent = `평가손익 ${won.format(portfolio.total_profit)}`;
  profit.className = directionClass(portfolio.total_profit);
}

function renderStocks() {
  $('#stock-list').innerHTML = state.data.stocks.map((stock) => `
    <tr data-ticker="${stock.ticker}" class="${stock.ticker === state.ticker ? 'selected' : ''}">
      <td><button type="button" class="stock-button"><strong>${escapeHtml(stock.name)}</strong><small>${stock.ticker} · ${escapeHtml(stock.sector)}</small></button></td>
      <td><strong>${integer.format(stock.price)}원</strong></td>
      <td class="${directionClass(stock.change_pct)}"><strong>${signedPercent(stock.change_pct)}</strong></td>
      <td class="${directionClass(stock.total_change_pct)}"><strong>${signedPercent(stock.total_change_pct)}</strong></td>
    </tr>`).join('');
}

function renderChart() {
  const host = $('#price-chart');
  const stock = currentStock();
  const points = (state.data.history || [])
    .map(withVirtualVolume)
    .slice(-state.chartPointLimit);
  if (!stock || !points.length) {
    host.innerHTML = '<div class="empty-block">가격 데이터가 없습니다.</div>';
    return;
  }

  const width = 820, height = 260;
  const margin = { top: 10, right: 78, bottom: 25, left: 12 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = 176;
  const volumeTop = 202;
  const volumeHeight = 31;
  const volumeBottom = volumeTop + volumeHeight;
  const position = state.data.portfolio.positions
    .find((item) => item.ticker === stock.ticker);
  const maxVolume = Math.max(1, ...points.map((point) => Number(point.volume || 0)));
  const candles = points.map((point, index) => {
    const close = Number(point.price);
    const open = index
      ? Number(points[index - 1].price)
      : close / (1 + Number(point.change_pct || 0) / 100);
    const bodyRange = Math.abs(close - open);
    const volumeRatio = Number(point.volume || 0) / maxVolume;
    const wick = Math.max(bodyRange * .18, open * (.0007 + volumeRatio * .0012));
    return {
      ...point, open, close,
      high: Math.max(open, close) + wick,
      low: Math.max(1000, Math.min(open, close) - wick),
      up: close >= open,
    };
  });
  const scalePrices = candles.flatMap((candle) => [candle.high, candle.low]);
  if (position) scalePrices.push(Number(position.avg_price));
  const rawMin = Math.min(...scalePrices), rawMax = Math.max(...scalePrices);
  const padding = Math.max((rawMax - rawMin) * .08, rawMax * .002, 10);
  const min = rawMin - padding, max = rawMax + padding;
  const slot = plotWidth / Math.max(1, candles.length);
  const x = (index) => margin.left + slot * index + slot / 2;
  const y = (price) => margin.top + (max - price) / (max - min) * plotHeight;
  const maxCandleWidth = candles.length <= 5 ? 52
    : candles.length <= 8 ? 42
      : candles.length <= 12 ? 32
    : candles.length <= 20 ? 22
      : candles.length <= 30 ? 16 : 10;
  const bodyWidth = Math.max(3, Math.min(maxCandleWidth, slot * .72));
  const volumeWidth = Math.max(3, Math.min(maxCandleWidth, slot * .78));

  const horizontalGrid = Array.from({ length: 6 }, (_, index) => {
    const ratio = index / 5;
    const py = margin.top + ratio * plotHeight;
    const value = max - ratio * (max - min);
    return `<line class="grid-line" x1="${margin.left}" y1="${py}" x2="${margin.left + plotWidth}" y2="${py}" />
      <text class="chart-label" x="${margin.left + plotWidth + 8}" y="${py + 3}">${integer.format(Math.round(value))}</text>`;
  }).join('');
  const verticalGrid = Array.from({ length: 12 }, (_, index) => {
    const px = margin.left + index / 11 * plotWidth;
    return `<line class="vertical-grid-line" x1="${px}" y1="${margin.top}" x2="${px}" y2="${volumeBottom}" />`;
  }).join('');
  const newsBands = candles.map((candle, index) => candle.event_type === 'news'
    ? `<rect class="news-band" x="${x(index) - slot / 2}" y="${margin.top}" width="${slot}" height="${volumeBottom - margin.top}" />`
    : '').join('');
  const candleShapes = candles.map((candle, index) => {
    const px = x(index);
    const bodyTop = y(Math.max(candle.open, candle.close));
    const bodyBottom = y(Math.min(candle.open, candle.close));
    const bodyHeight = Math.max(1.5, bodyBottom - bodyTop);
    const klass = candle.up ? 'up' : 'down';
    return `<line class="candle-wick ${klass}" x1="${px}" y1="${y(candle.high)}" x2="${px}" y2="${y(candle.low)}" />
      <rect class="candle-body ${klass}" x="${px - bodyWidth / 2}" y="${bodyTop}" width="${bodyWidth}" height="${bodyHeight}" />`;
  }).join('');
  const volumeBars = candles.map((candle, index) => {
    const barHeight = Number(candle.volume || 0) / maxVolume * volumeHeight;
    return `<rect class="volume-bar ${candle.up ? 'buy' : 'sell'}" x="${x(index) - volumeWidth / 2}" y="${volumeBottom - barHeight}" width="${volumeWidth}" height="${Math.max(1, barHeight)}" />`;
  }).join('');

  const labelIndexes = [...new Set([0, Math.floor((candles.length - 1) / 2), candles.length - 1])];
  const timeLabels = labelIndexes.map((index) => {
    const date = new Date(candles[index].created_at);
    const label = date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    const anchor = index === 0 ? 'start' : index === candles.length - 1 ? 'end' : 'middle';
    return `<text class="chart-label" x="${x(index)}" y="${height - 6}" text-anchor="${anchor}">${label}</text>`;
  }).join('');
  const averagePriceLine = position
    ? `<line class="average-price-line" x1="${margin.left}" y1="${y(Number(position.avg_price))}" x2="${margin.left + plotWidth}" y2="${y(Number(position.avg_price))}" />`
    : '';
  const currentY = y(Number(stock.price));
  const currentColor = Number(stock.change_pct) >= 0 ? '#ef244f' : '#2563eb';
  const currentPrice = `<line class="current-price-line" x1="${margin.left}" y1="${currentY}" x2="${margin.left + plotWidth}" y2="${currentY}" stroke="${currentColor}" />
    <rect class="current-price-tag" x="${margin.left + plotWidth + 4}" y="${currentY - 9}" width="70" height="18" rx="2" fill="${currentColor}" />
    <text class="current-price-text" x="${margin.left + plotWidth + 39}" y="${currentY + 3}" text-anchor="middle">${integer.format(stock.price)}</text>`;
  const hoverLayer = `<g id="chart-hover" class="chart-hover" visibility="hidden">
      <line class="chart-hover-guide" y1="${margin.top}" y2="${volumeBottom}" />
      <circle class="chart-hover-dot" r="4" />
      <g id="chart-tooltip" class="chart-tooltip">
        <rect width="176" height="78" rx="6" />
        <text class="chart-tooltip-time" x="10" y="15"></text>
        <text class="chart-tooltip-price" x="10" y="32"></text>
        <text class="chart-tooltip-ohlc" x="10" y="49"></text>
        <text class="chart-tooltip-volume" x="10" y="66"></text>
      </g>
    </g>
    <rect id="chart-hover-capture" class="chart-hover-capture" x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${volumeBottom - margin.top}" />`;

  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(stock.name)} 캔들 차트">
    ${verticalGrid}${horizontalGrid}${newsBands}${candleShapes}${averagePriceLine}${currentPrice}
    <line class="volume-divider" x1="${margin.left}" y1="${volumeTop - 5}" x2="${margin.left + plotWidth}" y2="${volumeTop - 5}" />
    ${volumeBars}${timeLabels}${hoverLayer}
  </svg>`;

  const svg = host.querySelector('svg');
  const capture = $('#chart-hover-capture');
  const hover = $('#chart-hover');
  const guide = hover.querySelector('.chart-hover-guide');
  const dot = hover.querySelector('.chart-hover-dot');
  const tooltip = $('#chart-tooltip');
  const tooltipTime = hover.querySelector('.chart-tooltip-time');
  const tooltipPrice = hover.querySelector('.chart-tooltip-price');
  const tooltipOhlc = hover.querySelector('.chart-tooltip-ohlc');
  const tooltipVolume = hover.querySelector('.chart-tooltip-volume');

  capture.addEventListener('pointermove', (event) => {
    const bounds = svg.getBoundingClientRect();
    const svgX = (event.clientX - bounds.left) / bounds.width * width;
    const index = Math.max(0, Math.min(candles.length - 1, Math.floor((svgX - margin.left) / slot)));
    const candle = candles[index];
    const pointX = x(index), pointY = y(candle.close);
    const tooltipX = Math.max(margin.left, Math.min(margin.left + plotWidth - 176, pointX - 88));
    const tooltipY = pointY < margin.top + 86 ? pointY + 8 : pointY - 84;
    const pointTime = new Date(candle.created_at).toLocaleTimeString('ko-KR', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    });
    hover.setAttribute('visibility', 'visible');
    guide.setAttribute('x1', pointX);
    guide.setAttribute('x2', pointX);
    dot.setAttribute('cx', pointX);
    dot.setAttribute('cy', pointY);
    tooltip.setAttribute('transform', `translate(${tooltipX} ${tooltipY})`);
    tooltipTime.textContent = pointTime;
    tooltipPrice.textContent = `${integer.format(candle.close)}원 · ${signedPercent(candle.change_pct)}`;
    tooltipOhlc.textContent = `시 ${integer.format(Math.round(candle.open))}  고 ${integer.format(Math.round(candle.high))}  저 ${integer.format(Math.round(candle.low))}`;
    tooltipVolume.textContent = `거래량 ${formatVolume(candle.volume)}주`;
  });
  capture.addEventListener('pointerleave', () => hover.setAttribute('visibility', 'hidden'));

  $('#chart-title').textContent = `${stock.name} (${stock.ticker})`;
  $('#live-price').textContent = `${integer.format(stock.price)}원`;
  $('#live-change').textContent = signedPercent(stock.change_pct);
  $('#live-change').className = directionClass(stock.change_pct);
}

function renderOrder() {
  const stock = currentStock();
  $('#order-name').textContent = stock.name;
  $('#order-code').textContent = `${stock.ticker} · ${stock.sector}`;
  $('#order-price').textContent = `${integer.format(stock.price)}원`;
  updateEstimate();
}

function renderNews() {
  const news = state.data.news;
  $('#news-list').innerHTML = news.length ? news.map((item) => {
    const concealed = item.source === 'random' && !item.applied_at;
    return `
    <article class="news-item ${concealed ? 'neutral' : item.sentiment}" data-news-id="${item.id}" role="button" tabindex="0" aria-haspopup="dialog">
      <div class="news-icon">${concealed ? '◇' : item.sentiment === 'positive' ? '↗' : '↘'}</div>
      <div>
        <div class="news-meta">
          ${item.applied_at ? `<span>${escapeHtml(item.stock_name)}</span>` : ''}<time>${formatTime(item.published_at)}</time>
          <b class="news-status ${item.applied_at ? 'applied' : 'pending'}">${item.applied_at ? '가격 반영 완료' : `가격 반영 예정 · ${formatTime(item.effective_at)}`}</b>
        </div>
        <h3>${escapeHtml(item.title)}</h3>
        ${item.content ? `<p>${escapeHtml(item.content)}</p>` : ''}
      </div>
      ${!item.applied_at
        ? '<span class="news-undisclosed">변동률 반영 후 공개</span>'
        : `<strong class="news-impact ${directionClass(item.impact_pct)}">${signedPercent(item.impact_pct)}</strong>`}
    </article>`;
  }).join('') : '<div class="empty-block">아직 발행된 뉴스가 없습니다.</div>';
  detectRandomNews(news);
}

function renderRecentNews() {
  const recent = state.data.news.slice(0, 3);
  $('#recent-news-list').innerHTML = recent.length ? recent.map((item) => {
    return `
    <article class="recent-news-item" data-news-id="${item.id}" role="button" tabindex="0" aria-haspopup="dialog">
      <div class="recent-news-meta">
        ${item.applied_at ? `<span>${escapeHtml(item.stock_name)}</span>` : ''}
        <time>${formatTime(item.published_at)}</time>
      </div>
      <h3>${escapeHtml(item.title)}</h3>
      <b class="${item.applied_at ? 'applied' : 'pending'}">${item.applied_at ? '반영 완료' : '반영 예정'}</b>
    </article>`;
  }).join('') : '<div class="recent-news-empty">아직 발행된 뉴스가 없습니다.</div>';
}

function renderTables() {
  const positions = state.data.portfolio.positions;
  const totalCost = positions.reduce((sum, position) => sum + Number(position.avg_price) * Number(position.quantity), 0);
  const totalProfit = positions.reduce((sum, position) => sum + Number(position.profit), 0);
  const totalReturn = totalCost ? totalProfit / totalCost * 100 : 0;
  document.getElementById("positions-total-value").textContent = won.format(state.data.portfolio.stock_value);
  document.getElementById("positions-total-return").textContent = signedPercent(totalReturn);
  document.getElementById("positions-total-return").className = directionClass(totalReturn);
  document.getElementById("positions-total-profit").textContent = "평가손익 " + won.format(totalProfit);
  document.getElementById("positions-total-profit").className = directionClass(totalProfit);
  const { key: sortKey, direction: sortDirection } = state.positionSort;
  const sortedPositions = [...positions].sort((left, right) => {
    if (!sortKey) return 0;
    const comparison = sortKey === 'name'
      ? String(left[sortKey]).localeCompare(String(right[sortKey]), 'ko-KR')
      : Number(left[sortKey]) - Number(right[sortKey]);
    return sortDirection === 'asc' ? comparison : -comparison;
  });
  document.querySelectorAll('#positions-table .sort-button').forEach((button) => {
    const active = button.dataset.sortKey === sortKey;
    button.classList.toggle('active', active);
    button.querySelector('span').textContent = active
      ? (sortDirection === 'asc' ? '↑' : '↓')
      : '↕';
    button.closest('th').setAttribute(
      'aria-sort',
      active ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none',
    );
  });
  $('#positions').innerHTML = sortedPositions.length ? sortedPositions.map((position) => `
    <tr data-ticker="${position.ticker}" class="${position.ticker === state.ticker ? 'selected' : ''}" role="button" tabindex="0" aria-label="${escapeHtml(position.name)} 종목 선택"><td><strong>${escapeHtml(position.name)}</strong><small>${position.ticker}</small></td>
      <td>${integer.format(position.quantity)}주</td><td>${integer.format(Math.round(position.avg_price))}원</td>
      <td>${integer.format(position.price)}원</td><td>${won.format(position.market_value)}</td><td><strong class="${directionClass(position.profit_pct)}">${signedPercent(position.profit_pct)}</strong><small>${won.format(position.profit)}</small></td></tr>`).join('')
    : '<tr><td colspan="6" class="empty">보유 종목이 없습니다.</td></tr>';

  const trades = state.data.trades;
  $('#trades').innerHTML = trades.length ? trades.map((trade) => `
    <tr><td>${formatTime(trade.executed_at, false)}</td><td><strong>${escapeHtml(trade.name)}</strong><small>${trade.ticker}</small></td>
      <td><span class="side-label ${trade.side}">${trade.side === 'buy' ? '매수' : '매도'}</span></td>
      <td>${integer.format(trade.quantity)}주</td><td>${integer.format(trade.price)}원</td></tr>`).join('')
    : '<tr><td colspan="5" class="empty">거래 내역이 없습니다.</td></tr>';
}


function renderTradeHistory() {
  const trades = state.data.trades || [];
  const buys = trades.filter((trade) => trade.side === 'buy');
  const sells = trades.filter((trade) => trade.side === 'sell');
  const buyTotal = buys.reduce((sum, trade) => sum + Number(trade.total), 0);
  const sellTotal = sells.reduce((sum, trade) => sum + Number(trade.total), 0);
  $('#history-trade-count').textContent = `${integer.format(trades.length)}건`;
  $('#history-buy-total').textContent = won.format(buyTotal);
  $('#history-sell-total').textContent = won.format(sellTotal);
  $('#history-buy-count').textContent = `매수 ${integer.format(buys.length)}건`;
  $('#history-sell-count').textContent = `매도 ${integer.format(sells.length)}건`;
  $('#history-table-count').textContent = `총 ${integer.format(trades.length)}건`;
  $('#trade-history').innerHTML = trades.length ? trades.map((trade) => `
    <tr>
      <td><time>${formatTime(trade.executed_at)}</time></td>
      <td><span class="side-label ${trade.side}">${trade.side === 'buy' ? '매수' : '매도'}</span></td>
      <td><strong>${escapeHtml(trade.name)}</strong></td>
      <td><span class="ticker-code">${trade.ticker}</span></td>
      <td>${integer.format(trade.quantity)}주</td>
      <td>${integer.format(trade.price)}원</td>
      <td><strong class="trade-total">${won.format(trade.total)}</strong></td>
    </tr>`).join('')
    : '<tr><td colspan="7" class="empty">거래 내역이 없습니다.</td></tr>';
}

function renderStockOptions() {
  const select = $('#news-ticker');
  const previous = select.value;
  select.innerHTML = '<option value="">전체 시장</option>' + state.data.stocks.map((stock) =>
    `<option value="${stock.ticker}">${escapeHtml(stock.name)} (${stock.ticker})</option>`).join('');
  select.value = previous;
}

function render() {
  renderSummary();
  renderStocks();
  renderChart();
  renderOrder();
  renderNews();
  renderRecentNews();
  renderTables();
  renderTradeHistory();
  renderStockOptions();
}

async function refresh({ silent = false } = {}) {
  if (state.refreshing) return;
  const requestedTicker = state.ticker;
  state.refreshing = true;
  $('#refresh').classList.add('spinning');
  try {
    const query = new URLSearchParams({ ticker: state.ticker });
    const data = await api(`/api/market/snapshot?${query}`);
    if (state.ticker === requestedTicker) {
      state.data = data;
      state.ticker = data.selected_ticker;
      state.countdownEnd = Date.now() + data.next_tick_in_seconds * 1000;
      render();
    }
  } catch (error) {
    state.countdownEnd = Date.now() + 5000;
    if (!silent) toast(error.message, 'error');
  } finally {
    state.refreshing = false;
    $('#refresh').classList.remove('spinning');
    if (state.ticker !== requestedTicker) refresh({ silent: true });
  }
}

function selectTicker(ticker) {
  if (!ticker || ticker === state.ticker) return;
  state.ticker = ticker;
  if (state.data) {
    renderStocks();
    renderTables();
  }
  refresh();
}

function selectTickerFromRow(event) {
  const row = event.target.closest('tr[data-ticker]');
  if (row) selectTicker(row.dataset.ticker);
}

function selectTickerFromRowWithKeyboard(event) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  selectTickerFromRow(event);
}

function updateEstimate() {
  const stock = currentStock();
  const quantity = Math.max(0, Number($('#quantity').value || 0));
  $('#estimate').textContent = stock ? won.format(stock.price * quantity) : '-';
}

function setSide(side) {
  state.side = side;
  document.querySelectorAll('.side-toggle button').forEach((button) => {
    button.classList.toggle('active', button.dataset.side === side);
  });
  const submit = $('#order-submit');
  submit.textContent = state.user ? (side === 'buy' ? '매수 주문' : '매도 주문') : '로그인 후 주문';
  submit.className = `primary-action ${side}`;
  $('#quick-order-label').textContent = side === 'buy'
    ? '주문 가능 현금 기준 빠른 주문'
    : '선택 종목 보유 수량 기준 빠른 주문';
}

function setMenuOpen(open) {
  $('#app-menu').classList.toggle('open', open);
  $('#menu-backdrop').classList.toggle('open', open);
  $('#app-menu').setAttribute('aria-hidden', String(!open));
  $('#menu-backdrop').setAttribute('aria-hidden', String(!open));
  $('#menu-toggle').setAttribute('aria-expanded', String(open));
}

function setView(view, { updateHash = true } = {}) {
  const activeView = ['trading', 'news', 'trades'].includes(view) ? view : 'trading';
  document.querySelectorAll('.app-view').forEach((element) => {
    element.hidden = element.dataset.view !== activeView;
  });
  document.querySelectorAll('[data-view-target]').forEach((button) => {
    button.classList.toggle('active', button.dataset.viewTarget === activeView);
  });
  setMenuOpen(false);
  if (updateHash && location.hash !== `#${activeView}`) location.hash = activeView;
}

$('#chart-point-limit').addEventListener('change', (event) => {
  const limit = Number(event.target.value);
  state.chartPointLimit = [10, 20, 30, 60].includes(limit) ? limit : 20;
  if (state.data) renderChart();
});

$("#stock-list").addEventListener("click", selectTickerFromRow);
$("#positions").addEventListener("click", selectTickerFromRow);
$("#positions").addEventListener("keydown", selectTickerFromRowWithKeyboard);
$('#positions-table thead').addEventListener('click', (event) => {
  const button = event.target.closest('.sort-button');
  if (!button) return;
  const key = button.dataset.sortKey;
  state.positionSort = {
    key,
    direction: state.positionSort.key === key && state.positionSort.direction === 'asc'
      ? 'desc'
      : 'asc',
  };
  renderTables();
});

$('#refresh').addEventListener('click', () => refresh());
$('#quantity').addEventListener('input', updateEstimate);
document.querySelectorAll('.side-toggle button').forEach((button) => {
  button.addEventListener('click', () => setSide(button.dataset.side));
});

document.querySelectorAll('.quick-quantity button').forEach((button) => {
  button.addEventListener('click', () => {
    const stock = currentStock();
    if (!stock) return;
    let quantity = Number(button.dataset.quantity || 0);
    if (button.dataset.ratio) {
      const ratio = Number(button.dataset.ratio);
      if (state.side === 'buy') {
        quantity = Math.floor((state.data.portfolio.cash * ratio) / stock.price);
      } else {
        const held = state.data.portfolio.positions
          .find((item) => item.ticker === stock.ticker)?.quantity || 0;
        quantity = Math.floor(held * ratio);
      }
    }
    if (quantity < 1) {
      toast(state.side === 'buy'
        ? '해당 비율로 주문 가능한 현금이 부족합니다.'
        : '해당 비율로 매도할 보유 수량이 없습니다.', 'error');
      return;
    }
    $('#quantity').value = quantity;
    updateEstimate();
  });
});

$('#menu-toggle').addEventListener('click', (event) => {
  event.stopPropagation();
  setMenuOpen(!$('#app-menu').classList.contains('open'));
});

$('#menu-close').addEventListener('click', () => {
  setMenuOpen(false);
  $('#menu-toggle').focus();
});

$('#menu-backdrop').addEventListener('click', () => setMenuOpen(false));
$('#login-open').addEventListener('click', () => showAuthModal('login'));
$('#register-open').addEventListener('click', () => showAuthModal('register'));
$('#auth-close').addEventListener('click', hideAuthModal);
$('#auth-backdrop').addEventListener('click', hideAuthModal);
$('#auth-switch').addEventListener('click', () => {
  setAuthMode(state.authMode === 'login' ? 'register' : 'login');
  $('#auth-password').value = '';
  $('#auth-password-confirm').value = '';
});
$('#random-news-close').addEventListener('click', hideNewsPopup);
$('#random-news-backdrop').addEventListener('click', hideNewsPopup);
$('#recent-news-list').addEventListener('click', openSelectedNews);
$('#recent-news-list').addEventListener('keydown', openSelectedNewsWithKeyboard);
$('#news-list').addEventListener('click', openSelectedNews);
$('#news-list').addEventListener('keydown', openSelectedNewsWithKeyboard);
$('#recent-news-more').addEventListener('click', () => setView('news'));
$('#trade-history-more').addEventListener('click', () => setView('trades'));

document.querySelectorAll('[data-view-target]').forEach((button) => {
  button.addEventListener('click', () => setView(button.dataset.viewTarget));
});

$('.brand').addEventListener('click', (event) => {
  event.preventDefault();
  setView('trading');
});

document.addEventListener('click', (event) => {
  if (event.target.closest('.menu-wrap') || event.target.closest('.app-menu')) return;
  setMenuOpen(false);
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (!$('#auth-modal').hidden) hideAuthModal();
  if (!$('#random-news-popup').hidden) hideNewsPopup();
  setMenuOpen(false);
  $('#menu-toggle').focus();
});

window.addEventListener('hashchange', () => {
  setView(location.hash.slice(1), { updateHash: false });
});

$('#order-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.user) {
    showAuthModal('login');
    return;
  }
  const submit = $('#order-submit');
  submit.disabled = true;
  try {
    const result = await api('/api/market/orders', {
      method: 'POST',
      body: JSON.stringify({
        ticker: state.ticker, side: state.side,
        quantity: Number($('#quantity').value),
      }),
    });
    toast(`${result.message} · ${won.format(result.total)}`);
    await refresh();
  } catch (error) {
    if (error.status === 401) {
      state.user = null;
      renderAuth();
      showAuthModal('login');
    }
    toast(error.message, 'error');
  } finally {
    submit.disabled = false;
  }
});

$('#news-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = $('#news-submit');
  submit.disabled = true;
  const impact = $('#news-impact').value;
  try {
    const result = await api('/api/market/news', {
      method: 'POST',
      body: JSON.stringify({
        title: $('#news-title').value, content: $('#news-content').value,
        sentiment: $('#news-sentiment').value, ticker: $('#news-ticker').value || null,
        impact_pct: impact ? Number(impact) : null, admin_key: $('#admin-key').value,
      }),
    });
    toast(`${result.message} (${signedPercent(result.impact_pct)})`);
    $('#news-title').value = '';
    $('#news-content').value = '';
    $('#news-impact').value = '';
    await refresh();
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    submit.disabled = false;
  }
});

$('#reset-account').addEventListener('click', async () => {
  if (!state.user) {
    showAuthModal('login');
    return;
  }
  if (!confirm('보유 종목과 거래 내역을 지우고 초기자금 1억원으로 되돌릴까요?')) return;
  try {
    const result = await api('/api/market/accounts/reset', { method: 'POST' });
    toast(result.message);
    await refresh();
  } catch (error) {
    toast(error.message, 'error');
  }
});


$('#sell-all').addEventListener('click', async () => {
  if (!state.user) { showAuthModal('login'); return; }
  const positions = state.data?.portfolio?.positions || [];
  if (!positions.length) { toast('매도할 보유 종목이 없습니다.', 'error'); return; }
  if (!confirm(`보유 중인 ${positions.length}개 종목을 현재가로 모두 매도할까요?`)) return;
  const button = $('#sell-all');
  button.disabled = true;
  try {
    let result;
    try {
      result = await api('/api/market/accounts/sell-all', { method: 'POST' });
    } catch (error) {
      if (![404, 405].includes(error.status)) throw error;
      let total = 0;
      for (const position of positions) {
        const sold = await api('/api/market/orders', {
          method: 'POST',
          body: JSON.stringify({
            ticker: position.ticker,
            side: 'sell',
            quantity: position.quantity,
          }),
        });
        total += Number(sold.total || 0);
      }
      result = {
        message: `보유 종목 ${positions.length}개를 모두 매도했습니다.`,
        total,
      };
    }
    state.marketRandomizeUnlocked = true;
    syncMarketActionLock();
    toast(`${result.message} · ${won.format(result.total)}`);
    await refresh();
  } catch (error) {
    await refresh();
    toast(error.message, 'error');
  } finally { button.disabled = false; }
});

$('#randomize-market').addEventListener('click', async () => {
  if (!state.user) { showAuthModal('login'); return; }
  if (!confirm('전 종목 가격을 기준가 ±15% 범위에서 새로 설정할까요?\n보유 수량과 거래 내역은 유지됩니다.')) return;
  const button = $('#randomize-market');
  button.disabled = true;
  try {
    const result = await api('/api/market/randomize', { method: 'POST' });
    state.marketRandomizeUnlocked = false;
    syncMarketActionLock();
    toast(result.message);
    await refresh();
  } catch (error) { toast(error.message, 'error'); }
  finally { syncMarketActionLock(); }
});

$('#auth-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = $('#auth-submit');
  const errorElement = $('#auth-error');
  const password = $('#auth-password').value;
  if (state.authMode === 'register' && password !== $('#auth-password-confirm').value) {
    errorElement.textContent = '비밀번호 확인이 일치하지 않습니다.';
    errorElement.hidden = false;
    return;
  }
  submit.disabled = true;
  errorElement.hidden = true;
  try {
    const result = await api(`/api/auth/${state.authMode}`, {
      method: 'POST',
      body: JSON.stringify({ username: $('#auth-username').value, password }),
    });
    state.user = result.user;
    state.marketRandomizeUnlocked = false;
    syncMarketActionLock();
    renderAuth();
    hideAuthModal();
    $('#auth-form').reset();
    toast(result.message);
    await refresh();
  } catch (error) {
    errorElement.textContent = error.message;
    errorElement.hidden = false;
  } finally {
    submit.disabled = false;
  }
});

$('#logout').addEventListener('click', async () => {
  try {
    const result = await api('/api/auth/logout', { method: 'POST' });
    state.user = null;
    state.marketRandomizeUnlocked = false;
    syncMarketActionLock();
    renderAuth();
    toast(result.message);
    await refresh();
  } catch (error) {
    toast(error.message, 'error');
  }
});

setInterval(() => {
  const now = new Date();
  $('#topbar-time').textContent = now.toLocaleTimeString('ko-KR', { hour12: false });
  if (!state.countdownEnd) return;
  const remaining = Math.max(0, (state.countdownEnd - Date.now()) / 1000);
  if (remaining <= 0 && !state.refreshing) {
    state.countdownEnd = Date.now() + 15_000;
    refresh({ silent: true });
  }
}, 250);

setView(location.hash.slice(1), { updateHash: false });
syncMarketActionLock();
initializeAuth();
