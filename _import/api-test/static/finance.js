const FinanceUI = (() => {
    const number = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 });

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function formatNumber(value, compact = false) {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return "-";
        if (compact) {
            return new Intl.NumberFormat("ko-KR", {
                notation: "compact",
                maximumFractionDigits: 1,
            }).format(numeric);
        }
        return number.format(numeric);
    }

    async function request(url) {
        const response = await fetch(url);
        let payload;
        try {
            payload = await response.json();
        } catch {
            payload = {};
        }
        if (!response.ok) {
            throw new Error(payload.detail || `요청 실패 (${response.status})`);
        }
        return payload;
    }

    function setStatus(element, message, type = "") {
        element.textContent = message;
        element.className = `status ${type}`.trim();
    }

    function renderBars(element, rows, {
        name = "name",
        value = "value",
        format,
        tooltip,
    } = {}) {
        if (!rows?.length) {
            element.innerHTML = '<div class="empty">표시할 데이터가 없습니다.</div>';
            return;
        }
        const max = Math.max(...rows.map((row) => Math.abs(Number(row[value]) || 0)), 1);
        element.innerHTML = `<div class="bar-list">${rows.map((row) => `
            <div class="bar-row">
                <span class="bar-name-wrap">
                    <span class="bar-name" ${tooltip ? 'tabindex="0"' : ""} title="${escapeHtml(row[name])}">${escapeHtml(row[name])}</span>
                    ${tooltip ? `<span class="stock-tooltip" role="tooltip">${tooltip(row)}</span>` : ""}
                </span>
                <span class="bar-track"><span class="bar-fill" style="width:${Math.max(2, Math.abs(Number(row[value]) || 0) / max * 100)}%"></span></span>
                <span class="bar-value">${escapeHtml(format ? format(row[value], row) : formatNumber(row[value], true))}</span>
            </div>`).join("")}</div>`;
    }

    function renderLine(element, points, { value = "value", time = "time", unit = "" } = {}) {
        if (!points?.length) {
            element.innerHTML = '<div class="empty">표시할 시계열 데이터가 없습니다.</div>';
            return;
        }
        const data = points.map((point) => ({ x: point[time], y: Number(point[value]) }))
            .filter((point) => Number.isFinite(point.y));
        if (!data.length) {
            element.innerHTML = '<div class="empty">숫자 형식의 데이터가 없습니다.</div>';
            return;
        }
        const width = 900;
        const height = 260;
        const pad = { left: 55, right: 18, top: 18, bottom: 34 };
        const min = Math.min(...data.map((point) => point.y));
        const max = Math.max(...data.map((point) => point.y));
        const spread = max - min || Math.max(Math.abs(max) * .1, 1);
        const low = min - spread * .08;
        const high = max + spread * .08;
        const x = (index) => pad.left + index * (width - pad.left - pad.right) / Math.max(data.length - 1, 1);
        const y = (value) => pad.top + (high - value) * (height - pad.top - pad.bottom) / (high - low);
        const line = data.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.y).toFixed(1)}`).join(" ");
        const area = `${line} L${x(data.length - 1)},${height - pad.bottom} L${x(0)},${height - pad.bottom} Z`;
        const tickIndexes = [...new Set([0, Math.floor((data.length - 1) / 2), data.length - 1])];
        const yTicks = [high, (high + low) / 2, low];
        element.innerHTML = `
            <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="시계열 차트">
                <defs><linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color="#37d4ca"/><stop offset="100%" stop-color="#37d4ca" stop-opacity="0"/>
                </linearGradient></defs>
                ${yTicks.map((tick) => `<line class="chart-grid" x1="${pad.left}" x2="${width-pad.right}" y1="${y(tick)}" y2="${y(tick)}"/>`).join("")}
                ${yTicks.map((tick) => `<text class="chart-label" x="0" y="${y(tick)+4}">${escapeHtml(formatNumber(tick))}</text>`).join("")}
                <path class="chart-area" d="${area}"/><path class="chart-line" d="${line}"/>
                <g class="chart-hover" visibility="hidden" aria-hidden="true">
                    <line class="chart-crosshair" y1="${pad.top}" y2="${height-pad.bottom}"/>
                    <circle class="chart-hover-dot" r="5"/>
                    <g class="chart-hover-card">
                        <rect class="chart-hover-box" width="146" height="45" rx="9"/>
                        <text class="chart-hover-time" x="11" y="16"></text>
                        <text class="chart-hover-value" x="11" y="34"></text>
                    </g>
                </g>
                <rect class="chart-hit-area" x="${pad.left}" y="${pad.top}" width="${width-pad.left-pad.right}" height="${height-pad.top-pad.bottom}" fill="transparent"/>
                ${tickIndexes.map((index) => `<text class="chart-label" text-anchor="${index === 0 ? "start" : index === data.length - 1 ? "end" : "middle"}" x="${x(index)}" y="${height-8}">${escapeHtml(data[index].x)}</text>`).join("")}
            </svg>
            <div class="panel-note">최근값 ${escapeHtml(formatNumber(data.at(-1).y))}${escapeHtml(unit ? ` ${unit}` : "")} · 범위 ${escapeHtml(formatNumber(min))}–${escapeHtml(formatNumber(max))}</div>`;

        const svg = element.querySelector("svg");
        const hitArea = svg.querySelector(".chart-hit-area");
        const hover = svg.querySelector(".chart-hover");
        const crosshair = svg.querySelector(".chart-crosshair");
        const dot = svg.querySelector(".chart-hover-dot");
        const card = svg.querySelector(".chart-hover-card");
        const timeLabel = svg.querySelector(".chart-hover-time");
        const valueLabel = svg.querySelector(".chart-hover-value");
        const plotWidth = width - pad.left - pad.right;

        hitArea.style.cursor = "crosshair";
        hitArea.addEventListener("pointermove", (event) => {
            const screenMatrix = svg.getScreenCTM();
            if (!screenMatrix) return;
            const cursor = svg.createSVGPoint();
            cursor.x = event.clientX;
            cursor.y = event.clientY;
            const localCursor = cursor.matrixTransform(screenMatrix.inverse());
            const pointerX = Math.max(
                pad.left,
                Math.min(width - pad.right, localCursor.x),
            );
            const ratio = Math.max(0, Math.min(1, (pointerX - pad.left) / plotWidth));
            const index = Math.round(ratio * Math.max(data.length - 1, 0));
            const point = data[index];
            const pointX = x(index);
            const pointY = y(point.y);
            const cardX = Math.max(
                pad.left,
                Math.min(width - pad.right - 146, pointerX - 73),
            );
            const cardY = pointY > pad.top + 62
                ? pointY - 55
                : Math.min(height - pad.bottom - 49, pointY + 10);

            crosshair.setAttribute("x1", pointerX);
            crosshair.setAttribute("x2", pointerX);
            dot.setAttribute("cx", pointX);
            dot.setAttribute("cy", pointY);
            card.setAttribute("transform", `translate(${cardX} ${cardY})`);
            timeLabel.textContent = point.x;
            valueLabel.textContent = `${formatNumber(point.y)}${unit ? ` ${unit}` : ""}`;
            hover.setAttribute("visibility", "visible");
        });
        hitArea.addEventListener("pointerleave", () => {
            hover.setAttribute("visibility", "hidden");
        });
    }

    return { escapeHtml, formatNumber, request, setStatus, renderBars, renderLine };
})();
