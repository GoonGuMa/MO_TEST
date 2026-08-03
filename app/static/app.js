const won = new Intl.NumberFormat('ko-KR', {
  style: 'currency', currency: 'KRW', maximumFractionDigits: 0,
});
const integer = new Intl.NumberFormat('ko-KR');

const state = {
  userId: getUserId(),
  ticker: '005930',
  side: 'buy',
  data: null,
  countdownEnd: 0,
  refreshing: false,
};

const $ = (selector) => document.querySelector(selector);

function getUserId() {
  let userId = localStorage.getItem('market_lab_user_id');
  if (!userId) {
    const suffix = crypto.randomUUID?.().replaceAll('-', '').slice(0, 10)
      || Math.random().toString(36).slice(2, 12);
    userId = `student_${suffix}`;
    localStorage.setItem('market_lab_user_id', userId);
  }
  return userId;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

function signedPercent(value) {
  const number = Number(value || 0);
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`;
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

function apiErrorMessage(data, fallback) {
  if (typeof data?.detail === 'string') return data.detail;
  if (Array.isArray(data?.detail)) return data.detail.map((item) => item.msg).join(', ');
  return fallback;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(apiErrorMessage(data, `요청 실패 (${response.status})`));
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
  const points = state.data.history || [];
  if (!stock || !points.length) {
    host.innerHTML = '<div class="empty-block">가격 데이터가 없습니다.</div>';
    return;
  }

  const width = 820, height = 260;
  const margin = { top: 16, right: 76, bottom: 30, left: 12 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const prices = points.map((point) => Number(point.price));
  const rawMin = Math.min(...prices), rawMax = Math.max(...prices);
  const padding = Math.max((rawMax - rawMin) * .12, rawMax * .005, 10);
  const min = rawMin - padding, max = rawMax + padding;
  const x = (index) => margin.left + (points.length === 1 ? plotWidth / 2 : index / (points.length - 1) * plotWidth);
  const y = (price) => margin.top + (max - price) / (max - min) * plotHeight;
  const coordinates = points.map((point, index) => [x(index), y(point.price)]);
  const line = coordinates.map(([px, py], index) => `${index ? 'L' : 'M'}${px.toFixed(1)},${py.toFixed(1)}`).join(' ');
  const area = `${line} L${coordinates.at(-1)[0].toFixed(1)},${margin.top + plotHeight} L${coordinates[0][0].toFixed(1)},${margin.top + plotHeight} Z`;
  const up = stock.total_change_pct >= 0;
  const color = up ? '#e23d48' : '#1e63d5';
  const gradientId = `area-${stock.ticker}`;

  const grid = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    const py = margin.top + ratio * plotHeight;
    const value = max - ratio * (max - min);
    return `<line class="grid-line" x1="${margin.left}" y1="${py}" x2="${margin.left + plotWidth}" y2="${py}" />
      <text class="chart-label" x="${margin.left + plotWidth + 8}" y="${py + 3}">${integer.format(Math.round(value))}</text>`;
  }).join('');

  const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  const timeLabels = labelIndexes.map((index) => {
    const date = new Date(points[index].created_at);
    const label = date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    const anchor = index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'middle';
    return `<text class="chart-label" x="${x(index)}" y="${height - 7}" text-anchor="${anchor}">${label}</text>`;
  }).join('');

  const newsMarkers = points.map((point, index) => point.event_type === 'news' ? `
    <circle class="news-marker" cx="${x(index)}" cy="${y(point.price)}" r="5" />
    <text class="news-label" x="${x(index)}" y="${Math.max(10, y(point.price) - 9)}" text-anchor="middle">NEWS</text>` : '').join('');

  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(stock.name)} 가격 흐름">
    <defs><linearGradient id="${gradientId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".8"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    ${grid}<path class="chart-area" d="${area}" fill="url(#${gradientId})"/><path class="chart-line-path" d="${line}" stroke="${color}"/>
    ${newsMarkers}${timeLabels}
  </svg>`;

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
  $('#news-list').innerHTML = news.length ? news.map((item) => `
    <article class="news-item ${item.sentiment}">
      <div class="news-icon">${item.sentiment === 'positive' ? '↗' : '↘'}</div>
      <div>
        <div class="news-meta"><span>${escapeHtml(item.stock_name)}</span><time>${formatTime(item.published_at)}</time></div>
        <h3>${escapeHtml(item.title)}</h3>
        ${item.content ? `<p>${escapeHtml(item.content)}</p>` : ''}
      </div>
      <strong class="news-impact ${directionClass(item.impact_pct)}">${signedPercent(item.impact_pct)}</strong>
    </article>`).join('') : '<div class="empty-block">아직 발행된 뉴스가 없습니다.</div>';
}

function renderTables() {
  const positions = state.data.portfolio.positions;
  $('#positions').innerHTML = positions.length ? positions.map((position) => `
    <tr><td><strong>${escapeHtml(position.name)}</strong><small>${position.ticker}</small></td>
      <td>${integer.format(position.quantity)}주</td><td>${integer.format(Math.round(position.avg_price))}원</td>
      <td>${won.format(position.market_value)}</td><td class="${directionClass(position.profit_pct)}"><strong>${signedPercent(position.profit_pct)}</strong><small>${won.format(position.profit)}</small></td></tr>`).join('')
    : '<tr><td colspan="5" class="empty">보유 종목이 없습니다.</td></tr>';

  const trades = state.data.trades;
  $('#trades').innerHTML = trades.length ? trades.map((trade) => `
    <tr><td>${formatTime(trade.executed_at, false)}</td><td><strong>${escapeHtml(trade.name)}</strong><small>${trade.ticker}</small></td>
      <td><span class="side-label ${trade.side}">${trade.side === 'buy' ? '매수' : '매도'}</span></td>
      <td>${integer.format(trade.quantity)}주</td><td>${integer.format(trade.price)}원</td></tr>`).join('')
    : '<tr><td colspan="5" class="empty">거래 내역이 없습니다.</td></tr>';
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
  renderTables();
  renderStockOptions();
}

async function refresh({ silent = false } = {}) {
  if (state.refreshing) return;
  state.refreshing = true;
  $('#refresh').classList.add('spinning');
  try {
    const query = new URLSearchParams({ user_id: state.userId, ticker: state.ticker });
    state.data = await api(`/api/market/snapshot?${query}`);
    state.ticker = state.data.selected_ticker;
    state.countdownEnd = Date.now() + state.data.next_tick_in_seconds * 1000;
    render();
  } catch (error) {
    state.countdownEnd = Date.now() + 5000;
    if (!silent) toast(error.message, 'error');
  } finally {
    state.refreshing = false;
    $('#refresh').classList.remove('spinning');
  }
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
  submit.textContent = side === 'buy' ? '매수 주문' : '매도 주문';
  submit.className = `primary-action ${side}`;
}

$('#stock-list').addEventListener('click', (event) => {
  const row = event.target.closest('tr[data-ticker]');
  if (!row || row.dataset.ticker === state.ticker) return;
  state.ticker = row.dataset.ticker;
  refresh();
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
    let quantity = Number(button.dataset.quantity);
    if (button.dataset.quantity === 'max') {
      if (state.side === 'buy') quantity = Math.floor(state.data.portfolio.cash / stock.price);
      else quantity = state.data.portfolio.positions.find((item) => item.ticker === stock.ticker)?.quantity || 0;
    }
    $('#quantity').value = Math.max(1, quantity);
    updateEstimate();
  });
});

$('#order-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = $('#order-submit');
  submit.disabled = true;
  try {
    const result = await api('/api/market/orders', {
      method: 'POST',
      body: JSON.stringify({
        user_id: state.userId, ticker: state.ticker,
        side: state.side, quantity: Number($('#quantity').value),
      }),
    });
    toast(`${result.message} · ${won.format(result.total)}`);
    await refresh();
  } catch (error) {
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
  if (!confirm('보유 종목과 거래 내역을 지우고 초기자금 1억원으로 되돌릴까요?')) return;
  try {
    const result = await api('/api/market/accounts/reset', {
      method: 'POST', body: JSON.stringify({ user_id: state.userId }),
    });
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
  $('#countdown').textContent = `${Math.ceil(remaining)}초`;
  if (remaining <= 0 && !state.refreshing) {
    state.countdownEnd = Date.now() + 15_000;
    refresh({ silent: true });
  }
}, 250);

$('#header-user').textContent = state.userId.toUpperCase();
refresh();
