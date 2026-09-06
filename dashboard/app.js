const HOSTED_API_BASE = "https://adaptive-ai-inference-control-plane-api.onrender.com";
const LOCAL_API_BASE = "http://localhost:8080";
const savedApiBase = localStorage.getItem("control-plane-api");
const localDashboard = ["localhost", "127.0.0.1"].includes(window.location.hostname);
const initialApiBase =
  savedApiBase && (localDashboard || savedApiBase !== LOCAL_API_BASE)
    ? savedApiBase
    : localDashboard
      ? LOCAL_API_BASE
      : HOSTED_API_BASE;

const state = {
  apiBase: initialApiBase,
  connected: false,
  refreshing: false,
  summary: null,
  health: [],
  cache: null,
};

const elements = {
  apiUrl: document.querySelector("#api-url"),
  connectButton: document.querySelector("#connect-button"),
  refreshButton: document.querySelector("#refresh-button"),
  connectionDot: document.querySelector("#connection-dot"),
  connectionLabel: document.querySelector("#connection-label"),
  lastRefresh: document.querySelector("#last-refresh"),
  completedRequests: document.querySelector("#completed-requests"),
  averageLatency: document.querySelector("#average-latency"),
  cacheEfficiency: document.querySelector("#cache-efficiency"),
  cacheDetail: document.querySelector("#cache-detail"),
  fallbackCount: document.querySelector("#fallback-count"),
  latencyChart: document.querySelector("#latency-chart"),
  providerList: document.querySelector("#provider-list"),
  eventTable: document.querySelector("#event-table"),
  requestForm: document.querySelector("#request-form"),
  sendButton: document.querySelector("#send-button"),
  requestResult: document.querySelector("#request-result"),
  metricsLink: document.querySelector("#metrics-link"),
};

elements.apiUrl.value = state.apiBase;
elements.metricsLink.href = `${state.apiBase}/metrics`;

function normalizeBaseUrl(value) {
  return value.trim().replace(/\/+$/, "");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setConnection(mode, label) {
  elements.connectionDot.className = `status-dot ${mode}`;
  elements.connectionLabel.textContent = label;
}

async function getJson(path) {
  const response = await fetch(`${state.apiBase}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`${path} returned HTTP ${response.status}`);
  }
  return response.json();
}

async function refresh() {
  if (!state.apiBase || state.refreshing) return;
  state.refreshing = true;

  try {
    const [summary, health, cache] = await Promise.all([
      getJson("/v1/telemetry/summary"),
      getJson("/v1/providers/health"),
      getJson("/v1/cache/status"),
    ]);
    state.summary = summary;
    state.health = health;
    state.cache = cache;
    state.connected = true;
    setConnection("online", "Gateway connected");
    elements.lastRefresh.textContent = `Updated ${new Date().toLocaleTimeString()} · ${cache.backend} cache`;
    render();
  } catch (error) {
    state.connected = false;
    setConnection("error", "Gateway unavailable");
    const detail = error instanceof Error ? error.message : "Unable to reach the gateway.";
    elements.lastRefresh.textContent = `Gateway waking or unavailable · retrying · ${detail}`;
  } finally {
    state.refreshing = false;
  }
}

function render() {
  const summary = state.summary;
  if (!summary) return;

  const completed = Number(summary.completed_requests || 0);
  const hits = Number(summary.cache_hits || 0);
  const replays = Number(summary.cache_replays || 0);
  const efficiency = completed ? ((hits + replays) / completed) * 100 : 0;

  elements.completedRequests.textContent = completed.toLocaleString();
  elements.averageLatency.textContent = Number(summary.average_latency_ms || 0).toFixed(1);
  elements.cacheEfficiency.textContent = efficiency.toFixed(1);
  elements.cacheDetail.textContent = `${hits} hits · ${replays} replays`;
  elements.fallbackCount.textContent = Number(summary.fallback_count || 0).toLocaleString();

  renderLatency(summary.recent_events || []);
  renderProviders(summary.providers || {}, state.health);
  renderEvents(summary.recent_events || []);
}

function renderLatency(events) {
  const samples = [...events].reverse().slice(-30);
  if (!samples.length) {
    elements.latencyChart.className = "chart empty-chart";
    elements.latencyChart.textContent = "No request samples yet.";
    return;
  }

  const width = 640;
  const height = 210;
  const padding = 16;
  const values = samples.map((event) => Number(event.latency_ms || 0));
  const maximum = Math.max(...values, 1);
  const step = samples.length > 1 ? (width - padding * 2) / (samples.length - 1) : 0;
  const points = values.map((value, index) => {
    const x = padding + index * step;
    const y = height - padding - (value / maximum) * (height - padding * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const areaPoints = `${padding},${height - padding} ${points.join(" ")} ${
    width - padding
  },${height - padding}`;

  elements.latencyChart.className = "chart";
  elements.latencyChart.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Recent inference latency">
      <defs>
        <linearGradient id="latency-gradient" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="#72f2b2" stop-opacity="0.24"></stop>
          <stop offset="100%" stop-color="#72f2b2" stop-opacity="0"></stop>
        </linearGradient>
      </defs>
      <line class="chart-grid" x1="16" y1="52" x2="624" y2="52"></line>
      <line class="chart-grid" x1="16" y1="105" x2="624" y2="105"></line>
      <line class="chart-grid" x1="16" y1="158" x2="624" y2="158"></line>
      <polygon class="chart-area" points="${areaPoints}"></polygon>
      <polyline class="chart-line" points="${points.join(" ")}"></polyline>
      <text x="16" y="16" fill="#91a9a0" font-size="10">max ${maximum.toFixed(1)} ms</text>
    </svg>`;
}

function renderProviders(providerMetrics, healthItems) {
  const healthByProvider = new Map(healthItems.map((item) => [item.provider, item]));
  const names = [...new Set([...Object.keys(providerMetrics), ...healthByProvider.keys()])].sort();

  if (!names.length) {
    elements.providerList.className = "provider-list empty-chart";
    elements.providerList.textContent = "No provider data yet.";
    return;
  }

  elements.providerList.className = "provider-list";
  elements.providerList.innerHTML = names
    .map((name) => {
      const metrics = providerMetrics[name] || {
        calls: 0,
        successes: 0,
        failures: 0,
        average_latency_ms: 0,
      };
      const health = healthByProvider.get(name);
      const calls = Number(metrics.calls || 0);
      const successRate = calls ? (Number(metrics.successes || 0) / calls) * 100 : 100;
      const healthLabel = health
        ? `${health.circuit} · ${health.available ? "available" : "isolated"}`
        : "not sampled";
      return `
        <div class="provider">
          <div class="provider-top">
            <strong>${escapeHtml(name)}</strong>
            <span>${escapeHtml(healthLabel)}</span>
          </div>
          <div class="bar"><span style="width: ${Math.max(successRate, 2)}%"></span></div>
          <div class="provider-meta">
            <span>${calls} calls · ${Number(metrics.failures || 0)} failed</span>
            <span>${Number(metrics.average_latency_ms || 0).toFixed(1)} ms avg</span>
          </div>
        </div>`;
    })
    .join("");
}

function renderEvents(events) {
  if (!events.length) {
    elements.eventTable.innerHTML =
      '<tr><td colspan="8" class="empty-row">No telemetry events yet.</td></tr>';
    return;
  }

  elements.eventTable.innerHTML = events
    .slice(0, 20)
    .map((event) => {
      const cacheClass = event.cache_status === "MISS" ? "cache-pill miss" : "cache-pill";
      const time = new Date(Number(event.timestamp) * 1000).toLocaleTimeString();
      return `
        <tr>
          <td>${escapeHtml(time)}</td>
          <td><code>${escapeHtml(String(event.request_id).slice(0, 12))}</code></td>
          <td>${escapeHtml(event.provider)}</td>
          <td>${escapeHtml(event.policy)}</td>
          <td><span class="${cacheClass}">${escapeHtml(event.cache_status)}</span></td>
          <td>${Number(event.latency_ms).toFixed(1)} ms</td>
          <td>${Number(event.fallback_count)}</td>
          <td><code title="${escapeHtml(event.trace_id)}">${escapeHtml(
            String(event.trace_id).slice(0, 10),
          )}…</code></td>
        </tr>`;
    })
    .join("");
}

function renderRequestResult(response, body) {
  const routing = body.routing;
  const answer = body.choices?.[0]?.message?.content || "No generated content.";
  elements.requestResult.className = "result";
  elements.requestResult.innerHTML = `
    <div class="result-grid">
      <div class="result-metric"><span>Provider</span><strong>${escapeHtml(
        routing.provider,
      )}</strong></div>
      <div class="result-metric"><span>Cache</span><strong>${escapeHtml(
        response.headers.get("X-Cache") || "UNKNOWN",
      )}</strong></div>
      <div class="result-metric"><span>Fallbacks</span><strong>${Number(
        routing.fallback_count,
      )}</strong></div>
      <div class="result-metric"><span>Trace</span><strong title="${escapeHtml(
        response.headers.get("X-Trace-ID") || "",
      )}">${escapeHtml((response.headers.get("X-Trace-ID") || "").slice(0, 12))}…</strong></div>
    </div>
    <div class="result-answer"><span>Response</span>${escapeHtml(answer)}</div>`;
}

async function submitRequest(event) {
  event.preventDefault();
  if (!state.apiBase) return;

  elements.sendButton.disabled = true;
  elements.sendButton.textContent = "Routing request…";
  elements.requestResult.className = "result empty";
  elements.requestResult.textContent = "Evaluating constraints and provider health.";

  const policy = document.querySelector("#policy").value;
  const body = {
    model: "auto",
    messages: [{ role: "user", content: document.querySelector("#prompt").value }],
    temperature: 0,
    max_tokens: Number(document.querySelector("#max-tokens").value),
    routing: {
      policy,
      min_quality: Number(document.querySelector("#quality").value),
      max_latency_ms: Number(document.querySelector("#latency-budget").value),
    },
  };

  try {
    const response = await fetch(`${state.apiBase}/v1/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": crypto.randomUUID(),
      },
      body: JSON.stringify(body),
    });
    const responseBody = await response.json();
    if (!response.ok) {
      throw new Error(
        typeof responseBody.detail === "string"
          ? responseBody.detail
          : JSON.stringify(responseBody.detail),
      );
    }
    renderRequestResult(response, responseBody);
    await refresh();
  } catch (error) {
    elements.requestResult.className = "result error-message";
    elements.requestResult.textContent =
      error instanceof Error ? error.message : "The request failed.";
  } finally {
    elements.sendButton.disabled = false;
    elements.sendButton.textContent = "Send through control plane";
  }
}

async function connect() {
  state.apiBase = normalizeBaseUrl(elements.apiUrl.value);
  localStorage.setItem("control-plane-api", state.apiBase);
  elements.metricsLink.href = `${state.apiBase}/metrics`;
  elements.connectButton.disabled = true;
  await refresh();
  elements.connectButton.disabled = false;
}

elements.connectButton.addEventListener("click", connect);
elements.refreshButton.addEventListener("click", refresh);
elements.requestForm.addEventListener("submit", submitRequest);
elements.apiUrl.addEventListener("keydown", (event) => {
  if (event.key === "Enter") connect();
});

connect();
setInterval(refresh, 5000);
