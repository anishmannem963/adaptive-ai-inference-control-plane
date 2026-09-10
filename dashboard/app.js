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
  profiles: [],
  status: null,
};

const elements = Object.fromEntries(
  [
    "api-url", "connect-button", "refresh-button", "connection-dot", "connection-label",
    "last-refresh", "completed-requests", "average-latency", "cache-efficiency",
    "cache-detail", "fallback-count", "latency-chart", "provider-list", "event-table",
    "request-form", "send-button", "request-result", "metrics-link", "docs-link",
    "provider-options", "outage-provider", "prompt", "prompt-count", "load-example",
    "cache-card", "provider-count", "hero-status", "weight-summary",
  ].map((id) => [id.replaceAll("-", "_"), document.querySelector(`#${id}`)]),
);

const weightNames = ["cost", "latency", "utilization", "quality"];

elements.api_url.value = state.apiBase;
updateGatewayLinks();
updatePromptCount();
renderWeightSummary();

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

function formatMoney(value) {
  const number = Number(value || 0);
  if (number === 0) return "$0.000000";
  return `$${number.toFixed(6)}`;
}

function setConnection(mode, label) {
  elements.connection_dot.className = `status-dot ${mode}`;
  elements.connection_label.textContent = label;
  elements.hero_status.className = mode === "online" ? "online" : "";
  elements.hero_status.textContent = mode === "online" ? "ONLINE" : mode === "error" ? "RETRYING" : "WAKING";
}

function updateGatewayLinks() {
  elements.metrics_link.href = `${state.apiBase}/metrics`;
  elements.docs_link.href = `${state.apiBase}/docs`;
}

async function getJson(path) {
  const response = await fetch(`${state.apiBase}${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
  return response.json();
}

async function refresh() {
  if (!state.apiBase || state.refreshing) return;
  state.refreshing = true;
  try {
    const [summary, health, cache, profiles, status] = await Promise.all([
      getJson("/v1/telemetry/summary"),
      getJson("/v1/providers/health"),
      getJson("/v1/cache/status"),
      getJson("/v1/providers"),
      getJson("/v1/system/status"),
    ]);
    Object.assign(state, { summary, health, cache, profiles, status, connected: true });
    setConnection("online", "Gateway connected");
    elements.last_refresh.textContent = `Updated ${new Date().toLocaleTimeString()} · ${cache.backend} cache`;
    renderProviderControls();
    render();
  } catch (error) {
    state.connected = false;
    setConnection("error", "Gateway waking");
    const detail = error instanceof Error ? error.message : "Unable to reach the gateway";
    elements.last_refresh.textContent = `Free gateway waking or updating · retrying · ${detail}`;
  } finally {
    state.refreshing = false;
  }
}

function render() {
  if (!state.summary) return;
  const completed = Number(state.summary.completed_requests || 0);
  const hits = Number(state.summary.cache_hits || 0);
  const replays = Number(state.summary.cache_replays || 0);
  const efficiency = completed ? ((hits + replays) / completed) * 100 : 0;
  elements.completed_requests.textContent = completed.toLocaleString();
  elements.average_latency.textContent = Number(state.summary.average_latency_ms || 0).toFixed(1);
  elements.cache_efficiency.textContent = efficiency.toFixed(1);
  elements.cache_detail.textContent = `${hits} hits · ${replays} replays`;
  elements.fallback_count.textContent = Number(state.summary.fallback_count || 0).toLocaleString();
  elements.provider_count.textContent = String(state.profiles.length);
  renderLatency(state.summary.recent_events || []);
  renderProviders(state.summary.providers || {}, state.health, state.profiles);
  renderEvents(state.summary.recent_events || []);
  renderCache(state.cache);
}

function renderProviderControls() {
  const signature = state.profiles.map((profile) => profile.name).join("|");
  if (elements.provider_options.dataset.signature === signature) return;
  elements.provider_options.dataset.signature = signature;
  elements.provider_options.innerHTML = state.profiles
    .map((profile) => `<label class="provider-check"><input type="checkbox" name="allowed-provider" value="${escapeHtml(profile.name)}" checked /><span>${escapeHtml(profile.name)}</span></label>`)
    .join("");
  elements.outage_provider.innerHTML = `<option value="">None</option>${state.profiles
    .filter((profile) => profile.simulated)
    .map((profile) => `<option value="${escapeHtml(profile.name)}">${escapeHtml(profile.name)}</option>`)
    .join("")}`;
}

function renderProviders(providerMetrics, healthItems, profiles) {
  const healthByProvider = new Map(healthItems.map((item) => [item.provider, item]));
  elements.provider_list.className = "provider-list";
  elements.provider_list.innerHTML = profiles.map((profile) => {
    const metrics = providerMetrics[profile.name] || { calls: 0, successes: 0, failures: 0, average_latency_ms: 0 };
    const health = healthByProvider.get(profile.name);
    const available = health?.available !== false;
    return `<article class="provider-card">
      <div class="provider-top"><strong>${escapeHtml(profile.name)}</strong><span>${available ? "● eligible" : "● isolated"}</span></div>
      <small>${escapeHtml(profile.deployment)} · ${profile.simulated ? "controlled simulation" : "real adapter"}</small>
      <div class="provider-metrics">
        <div><strong>${profile.nominal_latency_ms} ms</strong><span>Nominal latency</span></div>
        <div><strong>${Math.round(Number(profile.utilization_score) * 100)}%</strong><span>Load signal</span></div>
        <div><strong>${Math.round(Number(profile.quality_score) * 100)}%</strong><span>Quality</span></div>
      </div>
      <div class="provider-line"><span>In $${escapeHtml(profile.input_cost_per_million_tokens_usd)} · Out $${escapeHtml(profile.output_cost_per_million_tokens_usd)} / 1M</span><span class="${profile.trusted_for_sensitive ? "trusted" : ""}">${profile.trusted_for_sensitive ? "Trusted policy" : "Standard"}</span></div>
      <div class="provider-line"><span>${Number(metrics.calls || 0)} calls · ${Number(metrics.failures || 0)} failed</span><span>${Number(metrics.average_latency_ms || 0).toFixed(1)} ms avg</span></div>
    </article>`;
  }).join("");
}

function renderLatency(events) {
  const samples = [...events].reverse().slice(-30);
  if (!samples.length) {
    elements.latency_chart.className = "chart empty-chart";
    elements.latency_chart.textContent = "No request samples yet.";
    return;
  }
  const width = 640, height = 210, padding = 16;
  const values = samples.map((event) => Number(event.latency_ms || 0));
  const maximum = Math.max(...values, 1);
  const step = samples.length > 1 ? (width - padding * 2) / (samples.length - 1) : 0;
  const points = values.map((value, index) => `${(padding + index * step).toFixed(1)},${(height - padding - (value / maximum) * (height - padding * 2)).toFixed(1)}`);
  const area = `${padding},${height - padding} ${points.join(" ")} ${width - padding},${height - padding}`;
  elements.latency_chart.className = "chart";
  elements.latency_chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Recent inference latency"><defs><linearGradient id="latency-gradient" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#6ff0af" stop-opacity=".24"></stop><stop offset="100%" stop-color="#6ff0af" stop-opacity="0"></stop></linearGradient></defs><line class="chart-grid" x1="16" y1="52" x2="624" y2="52"></line><line class="chart-grid" x1="16" y1="105" x2="624" y2="105"></line><line class="chart-grid" x1="16" y1="158" x2="624" y2="158"></line><polygon class="chart-area" points="${area}"></polygon><polyline class="chart-line" points="${points.join(" ")}"></polyline><text x="16" y="16" fill="#96aaa2" font-size="11">max ${maximum.toFixed(1)} ms</text></svg>`;
}

function renderEvents(events) {
  if (!events.length) {
    elements.event_table.innerHTML = '<tr><td colspan="8" class="empty-row">No telemetry events yet.</td></tr>';
    return;
  }
  elements.event_table.innerHTML = events.slice(0, 20).map((event) => {
    const cacheClass = event.cache_status === "MISS" ? "cache-pill miss" : "cache-pill";
    return `<tr><td>${escapeHtml(new Date(Number(event.timestamp) * 1000).toLocaleTimeString())}</td><td><code>${escapeHtml(String(event.request_id).slice(0, 12))}</code></td><td>${escapeHtml(event.provider)}</td><td>${escapeHtml(event.policy)}</td><td><span class="${cacheClass}">${escapeHtml(event.cache_status)}</span></td><td>${Number(event.latency_ms).toFixed(1)} ms</td><td>${Number(event.fallback_count)}</td><td><code title="${escapeHtml(event.trace_id)}">${escapeHtml(String(event.trace_id).slice(0, 10))}…</code></td></tr>`;
  }).join("");
}

function renderCache(cache) {
  elements.cache_card.innerHTML = `<strong>${escapeHtml(cache.backend)} cache · ${cache.enabled ? "enabled" : "disabled"}</strong><p>TTL ${cache.ttl_seconds}s · inference continues if the cache is unavailable.</p><div class="cache-stats"><div><strong>${cache.hits}</strong><span>Hits</span></div><div><strong>${cache.misses}</strong><span>Misses</span></div><div><strong>${cache.backend_errors}</strong><span>Backend errors</span></div></div>`;
}

function renderRequestResult(response, body) {
  const routing = body.routing;
  const answer = body.choices?.[0]?.message?.content || "No generated content.";
  const trace = response.headers.get("X-Trace-ID") || "not exported";
  elements.request_result.className = "result";
  elements.request_result.innerHTML = `<div class="result-head"><strong>${escapeHtml(routing.provider)} selected</strong><span>${routing.simulated ? "CONTROLLED SIMULATION" : "REAL PROVIDER"}</span></div>
    <div class="result-grid">
      <div class="result-metric"><span>Cache</span><strong>${escapeHtml(response.headers.get("X-Cache") || "UNKNOWN")}</strong></div>
      <div class="result-metric"><span>Actual cost</span><strong>${formatMoney(routing.estimated_cost_usd)}</strong></div>
      <div class="result-metric"><span>Preflight ceiling</span><strong>${formatMoney(routing.maximum_estimated_cost_usd)}</strong></div>
      <div class="result-metric"><span>Round trip</span><strong>${Number(routing.latency_ms).toFixed(1)} ms</strong></div>
      <div class="result-metric"><span>Prompt tokens</span><strong>${Number(body.usage?.prompt_tokens || 0)}</strong></div>
      <div class="result-metric"><span>Output tokens</span><strong>${Number(body.usage?.completion_tokens || 0)}</strong></div>
      <div class="result-metric"><span>Fallbacks</span><strong>${Number(routing.fallback_count)}</strong></div>
      <div class="result-metric"><span>Trace</span><strong title="${escapeHtml(trace)}">${escapeHtml(trace.slice(0, 12))}…</strong></div>
    </div>
    <div class="result-detail"><div><span>Attempt path</span><strong>${escapeHtml(routing.attempted_providers.join(" → "))}</strong></div><div><span>Eligible pool</span><strong>${escapeHtml(routing.eligible_providers.join(", "))}</strong></div><div><span>Decision</span><strong>${escapeHtml(routing.decision_reason)}</strong></div></div>
    <div class="result-answer"><span>Provider response</span>${escapeHtml(answer)}</div>`;
}

function selectedProviders() {
  return [...document.querySelectorAll('input[name="allowed-provider"]:checked')].map((item) => item.value);
}

function routingWeights() {
  return Object.fromEntries(weightNames.map((name) => [name, Number(document.querySelector(`#${name}-weight`).value) / 100]));
}

function renderWeightSummary() {
  elements.weight_summary.innerHTML = weightNames.map((name) => {
    const value = Number(document.querySelector(`#${name}-weight`).value);
    document.querySelector(`#${name}-weight-output`).textContent = `${value}%`;
    return `<div class="weight-row"><span>${name[0].toUpperCase()}${name.slice(1)}</span><div class="mini-bar"><span style="width:${value}%"></span></div><strong>${value}%</strong></div>`;
  }).join("");
}

function updatePromptCount() {
  elements.prompt_count.textContent = `${elements.prompt.value.length} / 4000`;
}

async function submitRequest(event) {
  event.preventDefault();
  if (!state.apiBase) return;
  const allowed = selectedProviders();
  if (!allowed.length) {
    elements.request_result.className = "result error-message";
    elements.request_result.textContent = "Select at least one eligible provider.";
    return;
  }
  elements.send_button.disabled = true;
  elements.send_button.textContent = "Routing request…";
  elements.request_result.className = "result empty";
  elements.request_result.textContent = "Applying policy gates and ranking eligible providers.";
  const outage = elements.outage_provider.value;
  const costBudget = document.querySelector("#cost-budget").value;
  const routing = {
    policy: document.querySelector("#policy").value,
    min_quality: Number(document.querySelector("#quality").value),
    max_latency_ms: Number(document.querySelector("#latency-budget").value),
    allowed_providers: allowed,
    excluded_providers: [],
    simulated_failure_provider: outage || null,
    require_trusted: document.querySelector("#sensitive-request").checked,
    cache_mode: document.querySelector("#cache-mode").value,
    weights: routingWeights(),
  };
  if (costBudget !== "") routing.max_estimated_cost_usd = costBudget;
  const body = { model: "auto", messages: [{ role: "user", content: elements.prompt.value }], temperature: 0, max_tokens: Number(document.querySelector("#max-tokens").value), routing };
  try {
    const response = await fetch(`${state.apiBase}/v1/chat/completions`, { method: "POST", headers: { "Content-Type": "application/json", "X-Request-ID": crypto.randomUUID() }, body: JSON.stringify(body) });
    const responseBody = await response.json();
    if (!response.ok) throw new Error(typeof responseBody.detail === "string" ? responseBody.detail : JSON.stringify(responseBody.detail));
    renderRequestResult(response, responseBody);
    await refresh();
  } catch (error) {
    elements.request_result.className = "result error-message";
    elements.request_result.textContent = error instanceof Error ? error.message : "The request failed.";
  } finally {
    elements.send_button.disabled = false;
    elements.send_button.textContent = "Run inference →";
  }
}

async function connect() {
  state.apiBase = normalizeBaseUrl(elements.api_url.value);
  localStorage.setItem("control-plane-api", state.apiBase);
  updateGatewayLinks();
  elements.connect_button.disabled = true;
  await refresh();
  elements.connect_button.disabled = false;
}

elements.connect_button.addEventListener("click", connect);
elements.refresh_button.addEventListener("click", refresh);
elements.request_form.addEventListener("submit", submitRequest);
elements.prompt.addEventListener("input", updatePromptCount);
elements.load_example.addEventListener("click", () => { elements.prompt.value = "Explain why a cost-aware router may choose a slightly slower provider for this request."; updatePromptCount(); });
elements.api_url.addEventListener("keydown", (event) => { if (event.key === "Enter") connect(); });
for (const name of weightNames) document.querySelector(`#${name}-weight`).addEventListener("input", renderWeightSummary);

connect();
setInterval(refresh, 5000);
