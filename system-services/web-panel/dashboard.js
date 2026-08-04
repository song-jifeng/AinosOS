/**
 * AinosOS Web Dashboard - Main Application Script
 * Version: 1.0.0
 *
 * Features:
 * - Real-time updates via Server-Sent Events (EventSource)
 * - WebSocket for streaming inference
 * - SVG chart rendering (CPU, Memory, Temperature time series)
 * - Model management (list, load, unload)
 * - Inference playground with streaming response
 * - Context management (list, view, delete)
 * - Log viewer with auto-refresh and filtering
 * - Plugin management (list, enable, disable)
 * - Settings management with localStorage persistence
 * - Dark theme with smooth transitions
 * - Responsive handlers
 */

/* ============================================================
   Configuration
   ============================================================ */
const CONFIG = {
  apiBase: localStorage.getItem('ainos_api_url') || 'http://localhost:8080',
  apiToken: localStorage.getItem('ainos_api_token') || '',
  refreshInterval: parseInt(localStorage.getItem('ainos_refresh_interval')) || 5,
  maxLogEntries: parseInt(localStorage.getItem('ainos_max_logs')) || 500,
  defaultMaxTokens: parseInt(localStorage.getItem('ainos_default_max_tokens')) || 1024,
  defaultTemperature: parseFloat(localStorage.getItem('ainos_default_temp')) || 0.7,
  streamingEnabled: localStorage.getItem('ainos_streaming') !== 'false',
  logLevel: localStorage.getItem('ainos_log_level') || 'info',
  cpuThreshold: parseInt(localStorage.getItem('ainos_cpu_threshold')) || 90,
  tempThreshold: parseInt(localStorage.getItem('ainos_temp_threshold')) || 80,
  autoRefresh: localStorage.getItem('ainos_auto_refresh') !== 'false',
};

/* ============================================================
   State
   ============================================================ */
const STATE = {
  currentPage: 'dashboard',
  models: [],
  contexts: [],
  logs: [],
  plugins: [],
  inferenceWs: null,
  inferenceAbortController: null,
  isStreaming: false,
  chartData: {
    cpu: [],
    mem: [],
    temp: [],
    timestamps: [],
  },
  maxChartPoints: 60,
  refreshTimer: null,
  logTimer: null,
  sseConnection: null,
  modalCallback: null,
};

/* ============================================================
   Utility Functions
   ============================================================ */

function $(id) { return document.getElementById(id); }

function show(element) {
  if (typeof element === 'string') element = $(element);
  if (element) element.classList.remove('hidden');
}

function hide(element) {
  if (typeof element === 'string') element = $(element);
  if (element) element.classList.add('hidden');
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i];
}

function formatDuration(seconds) {
  if (!seconds || seconds < 0) return '0s';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const parts = [];
  if (d > 0) parts.push(d + 'd');
  if (h > 0) parts.push(h + 'h');
  if (m > 0) parts.push(m + 'm');
  if (s > 0 || parts.length === 0) parts.push(s + 's');
  return parts.join(' ');
}

function formatTimestamp(ts) {
  if (!ts) return '-';
  const d = new Date(ts);
  return d.toLocaleTimeString('en-US', { hour12: false }) + '.' +
    String(d.getMilliseconds()).padStart(3, '0');
}

function formatDate(ts) {
  if (!ts) return '-';
  const d = new Date(ts);
  return d.toLocaleString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });
}

function sanitize(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function escapeHtml(str) {
  return sanitize(str);
}

function debounce(fn, ms) {
  let timer;
  return function(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), ms);
  };
}

function getApiHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  if (CONFIG.apiToken) {
    headers['Authorization'] = 'Bearer ' + CONFIG.apiToken;
  }
  return headers;
}

/* ============================================================
   Toast Notifications
   ============================================================ */

function showToast(message, type, duration) {
  type = type || 'info';
  duration = duration || 4000;
  const container = $('toastContainer');
  const toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  const icons = { success: '&#10003;', error: '&#10007;', warning: '&#9888;', info: '&#8505;' };
  toast.innerHTML = '<span>' + (icons[type] || icons.info) + '</span><span>' + sanitize(message) + '</span>';
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

/* ============================================================
   Modal
   ============================================================ */

function openModal(title, bodyHtml, confirmText, callback) {
  $('modalTitle').textContent = title;
  $('modalBody').innerHTML = bodyHtml;
  $('modalConfirmBtn').textContent = confirmText || 'Confirm';
  STATE.modalCallback = callback || null;
  $('modalOverlay').classList.add('active');
}

function closeModal() {
  $('modalOverlay').classList.remove('active');
  STATE.modalCallback = null;
}

function modalConfirm() {
  if (typeof STATE.modalCallback === 'function') {
    STATE.modalCallback();
  }
  closeModal();
}

$('modalOverlay').addEventListener('click', function(e) {
  if (e.target === this) closeModal();
});

/* ============================================================
   Navigation
   ============================================================ */

function navigateTo(page) {
  STATE.currentPage = page;

  // Update sidebar
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  document.querySelector('.nav-item[data-page="' + page + '"]')?.classList.add('active');

  // Update pages
  document.querySelectorAll('.page').forEach(el => el.classList.add('hidden'));
  const pageEl = $('page-' + page);
  if (pageEl) {
    pageEl.classList.remove('hidden');
    pageEl.querySelectorAll('.fade-in-up').forEach((el, i) => {
      el.style.animation = 'none';
      el.offsetHeight;
      el.style.animation = '';
    });
  }

  // Auto-load data per page
  switch (page) {
    case 'models': refreshModels(); break;
    case 'context': refreshContext(); break;
    case 'logs': refreshLogs(); break;
    case 'plugins': refreshPlugins(); break;
    case 'inference': loadModelsForInference(); break;
  }

  // Close sidebar on mobile
  closeSidebar();
}

function toggleSidebar() {
  const sidebar = $('sidebar');
  const overlay = $('sidebarOverlay');
  sidebar.classList.toggle('open');
  overlay.classList.toggle('active');
}

function closeSidebar() {
  const sidebar = $('sidebar');
  const overlay = $('sidebarOverlay');
  sidebar.classList.remove('open');
  overlay.classList.remove('active');
}

/* ============================================================
   API Client
   ============================================================ */

async function apiRequest(method, path, body) {
  const url = CONFIG.apiBase.replace(/\/+$/, '') + path;
  const options = {
    method: method,
    headers: getApiHeaders(),
  };
  if (body && method !== 'GET') {
    options.body = JSON.stringify(body);
  }
  try {
    const response = await fetch(url, options);
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.error || errData.detail || 'HTTP ' + response.status);
    }
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return await response.json();
    }
    return await response.text();
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new Error('API request failed: ' + err.message);
  }
}

/* ============================================================
   SSE Connection
   ============================================================ */

function connectSSE() {
  if (STATE.sseConnection) {
    STATE.sseConnection.close();
  }
  const url = CONFIG.apiBase.replace(/\/+$/, '') + '/api/events';
  try {
    const es = new EventSource(url);
    STATE.sseConnection = es;

    es.onopen = function() {
      // Connection established
    };

    es.addEventListener('status', function(e) {
      try {
        const data = JSON.parse(e.data);
        updateDashboardStatus(data);
      } catch (err) { /* ignore parse errors */ }
    });

    es.addEventListener('log', function(e) {
      try {
        const data = JSON.parse(e.data);
        if (STATE.currentPage === 'logs') {
          addLogEntry(data);
        }
        STATE.logs.push(data);
        if (STATE.logs.length > CONFIG.maxLogEntries) {
          STATE.logs = STATE.logs.slice(-CONFIG.maxLogEntries);
        }
      } catch (err) { /* ignore */ }
    });

    es.addEventListener('model', function(e) {
      try {
        const data = JSON.parse(e.data);
        if (data.event === 'loaded' || data.event === 'unloaded') {
          refreshModels();
          updateDashboard();
        }
      } catch (err) { /* ignore */ }
    });

    es.onerror = function() {
      // Will auto-reconnect
    };
  } catch (err) {
    console.warn('SSE connection failed:', err.message);
  }
}

/* ============================================================
   Dashboard Status Updates
   ============================================================ */

function updateDashboardStatus(data) {
  if (!data) return;

  const cpu = data.cpu != null ? data.cpu : 0;
  const mem = data.memory != null ? data.memory : 0;
  const temp = data.temperature != null ? data.temperature : 0;
  const uptime = data.uptime != null ? data.uptime : 0;
  const status = data.status || 'online';

  // Status bar
  const dot = $('statusDot');
  dot.className = 'status-dot ' + (status === 'online' ? 'green' : status === 'degraded' ? 'yellow' : 'red');
  $('systemStatus').textContent = status.charAt(0).toUpperCase() + status.slice(1);
  $('cpuStatus').textContent = Math.round(cpu) + '%';
  $('memStatus').textContent = Math.round(mem) + '%';
  $('tempStatus').textContent = Math.round(temp) + '°C';
  $('uptimeStatus').textContent = formatDuration(uptime);

  // Stat cards
  $('statCpu').textContent = Math.round(cpu) + '%';
  $('statMem').textContent = formatBytes(data.memory_used != null ? data.memory_used : 0);
  $('statTemp').textContent = Math.round(temp) + '°C';
  $('statUptime').textContent = formatDuration(uptime);

  // Update chart data
  const now = Date.now();
  STATE.chartData.cpu.push(cpu);
  STATE.chartData.mem.push(mem);
  STATE.chartData.temp.push(temp);
  STATE.chartData.timestamps.push(now);

  if (STATE.chartData.cpu.length > STATE.maxChartPoints) {
    STATE.chartData.cpu.shift();
    STATE.chartData.mem.shift();
    STATE.chartData.temp.shift();
    STATE.chartData.timestamps.shift();
  }

  renderCharts();

  // System info
  if (data.system) {
    const sys = data.system;
    $('sysHostname').textContent = sys.hostname || '-';
    $('sysOS').textContent = sys.os || '-';
    $('sysKernel').textContent = sys.kernel || '-';
    $('sysCores').textContent = sys.cpu_cores || '-';
    $('sysTotalMem').textContent = formatBytes(sys.total_memory);
    $('sysDisk').textContent = sys.disk_usage != null ? sys.disk_usage + '%' : '-';
    $('sysPython').textContent = sys.python_version || '-';
    $('sysVersion').textContent = sys.ainos_version || '-';
  }

  // Active models
  if (data.active_models) {
    const tbody = $('activeModelsBody');
    if (data.active_models.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No models loaded</td></tr>';
    } else {
      tbody.innerHTML = data.active_models.map(function(m) {
        return '<tr>' +
          '<td><span class="text-mono text-sm">' + sanitize(m.id || m.model_id || '-') + '</span></td>' +
          '<td>' + sanitize(m.name || '-') + '</td>' +
          '<td><span class="badge badge-success">Loaded</span></td>' +
          '<td>' + (m.vram != null ? formatBytes(m.vram) : '-') + '</td>' +
          '<td>' + (m.uptime != null ? formatDuration(m.uptime) : '-') + '</td>' +
          '<td>' + (m.requests != null ? m.requests : 0) + '</td>' +
          '</tr>';
      }).join('');
    }
  }
}

/* ============================================================
   SVG Chart Rendering
   ============================================================ */

function renderCharts() {
  renderSingleChart('cpuChart', STATE.chartData.cpu, '#2979ff', '#0f3460', 'CPU %');
  renderSingleChart('memChart', STATE.chartData.mem, '#00c853', '#0f3460', 'Memory %');
  renderSingleChart('tempChart', STATE.chartData.temp, '#e94560', '#0f3460', 'Temperature °C');
}

function renderSingleChart(chartId, data, lineColor, fillColor, label) {
  const svg = $(chartId);
  if (!svg || data.length < 2) return;

  const width = 600;
  const height = 250;
  const padding = { top: 20, right: 20, bottom: 30, left: 40 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;

  const minVal = Math.min(...data);
  const maxVal = Math.max(...data);
  const valRange = maxVal - minVal || 1;
  const padding_pct = valRange * 0.1;

  const yMin = Math.max(0, minVal - padding_pct);
  const yMax = maxVal + padding_pct;

  function xPos(i) {
    if (data.length <= 1) return padding.left;
    return padding.left + (i / (data.length - 1)) * plotW;
  }

  function yPos(val) {
    return padding.top + plotH - ((val - yMin) / (yMax - yMin)) * plotH;
  }

  // Build path
  let pathD = data.map(function(val, i) {
    return (i === 0 ? 'M' : 'L') + xPos(i).toFixed(1) + ',' + yPos(val).toFixed(1);
  }).join(' ');

  // Area fill
  let areaD = pathD +
    ' L' + xPos(data.length - 1).toFixed(1) + ',' + (padding.top + plotH) +
    ' L' + xPos(0).toFixed(1) + ',' + (padding.top + plotH) + ' Z';

  // Grid lines
  let gridLines = '';
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (plotH / 4) * i;
    const val = yMax - ((yMax - yMin) / 4) * i;
    gridLines += '<line x1="' + padding.left + '" y1="' + y + '" x2="' + (padding.left + plotW) + '" y2="' + y + '" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>';
    gridLines += '<text x="' + (padding.left - 8) + '" y="' + (y + 4) + '" fill="#616161" font-size="10" text-anchor="end">' + Math.round(val) + '</text>';
  }

  // Y-axis label
  const yLabel = '<text x="8" y="' + (padding.top + plotH / 2) + '" fill="#616161" font-size="10" transform="rotate(-90,8,' + (padding.top + plotH / 2) + ')" text-anchor="middle">' + sanitize(label) + '</text>';

  // X-axis labels (time)
  let xLabels = '';
  if (STATE.chartData.timestamps.length === data.length) {
    const step = Math.max(1, Math.floor(data.length / 6));
    for (let i = 0; i < data.length; i += step) {
      const x = xPos(i);
      const time = new Date(STATE.chartData.timestamps[i]);
      const timeStr = time.getHours().toString().padStart(2, '0') + ':' + time.getMinutes().toString().padStart(2, '0') + ':' + time.getSeconds().toString().padStart(2, '0');
      xLabels += '<text x="' + x + '" y="' + (height - 6) + '" fill="#616161" font-size="9" text-anchor="middle">' + timeStr + '</text>';
    }
  }

  // Current value label
  const lastVal = data[data.length - 1];
  const lastX = xPos(data.length - 1);
  const lastY = yPos(lastVal);
  const valueLabel = '<text x="' + (lastX + 5) + '" y="' + (lastY - 5) + '" fill="' + lineColor + '" font-size="11" font-weight="600">' + Math.round(lastVal) + '</text>';

  svg.innerHTML =
    '<defs>' +
    '  <linearGradient id="grad-' + chartId + '" x1="0" y1="0" x2="0" y2="1">' +
    '    <stop offset="0%" stop-color="' + fillColor + '" stop-opacity="0.3"/>' +
    '    <stop offset="100%" stop-color="' + fillColor + '" stop-opacity="0.02"/>' +
    '  </linearGradient>' +
    '</defs>' +
    gridLines +
    yLabel +
    xLabels +
    '<path d="' + areaD + '" fill="url(#grad-' + chartId + ')" opacity="0.8"/>' +
    '<path d="' + pathD + '" fill="none" stroke="' + lineColor + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<circle cx="' + lastX.toFixed(1) + '" cy="' + lastY.toFixed(1) + '" r="3" fill="' + lineColor + '" stroke="#1a1a2e" stroke-width="1.5"/>' +
    valueLabel;
}

/* ============================================================
   Dashboard Page
   ============================================================ */

async function updateDashboard() {
  try {
    const data = await apiRequest('GET', '/api/status');
    updateDashboardStatus(data);
  } catch (err) {
    console.warn('Dashboard update failed:', err.message);
  }
}

/* ============================================================
   Models Page
   ============================================================ */

async function refreshModels() {
  const tbody = $('modelsTableBody');
  tbody.innerHTML = '<tr><td colspan="8" class="text-center"><div class="spinner" style="margin:12px auto;"></div></td></tr>';
  try {
    const data = await apiRequest('GET', '/api/models');
    STATE.models = data.models || data || [];
    renderModels();
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger">Error loading models: ' + sanitize(err.message) + '</td></tr>';
  }
}

function renderModels() {
  const tbody = $('modelsTableBody');
  const search = ($('modelSearch')?.value || '').toLowerCase();
  const statusFilter = $('modelStatusFilter')?.value || 'all';

  const filtered = STATE.models.filter(function(m) {
    const id = (m.id || m.model_id || '').toLowerCase();
    const name = (m.name || '').toLowerCase();
    const matchesSearch = !search || id.includes(search) || name.includes(search);
    const matchesStatus = statusFilter === 'all' || (m.status || 'unloaded') === statusFilter;
    return matchesSearch && matchesStatus;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">No models found</td></tr>';
    return;
  }

  tbody.innerHTML = filtered.map(function(m) {
    const modelId = m.id || m.model_id || '-';
    const status = m.status || 'unloaded';
    const statusBadge = status === 'loaded' ? 'badge-success' :
      status === 'error' ? 'badge-danger' : 'badge-neutral';
    const isLoaded = status === 'loaded';
    return '<tr>' +
      '<td><span class="text-mono text-sm">' + sanitize(modelId) + '</span></td>' +
      '<td>' + sanitize(m.name || modelId) + '</td>' +
      '<td>' + sanitize(m.provider || '-') + '</td>' +
      '<td><span class="badge ' + statusBadge + '">' + sanitize(status) + '</span></td>' +
      '<td>' + (m.vram != null ? formatBytes(m.vram) : '-') + '</td>' +
      '<td>' + (m.context_length || '-') + '</td>' +
      '<td>' + (m.requests || 0) + '</td>' +
      '<td>' +
        (isLoaded
          ? '<button class="btn btn-sm btn-danger" onclick="unloadModel(\'' + sanitize(modelId) + '\')">Unload</button>'
          : '<button class="btn btn-sm btn-success" onclick="loadModel(\'' + sanitize(modelId) + '\')">Load</button>'
        ) +
      '</td>' +
      '</tr>';
  }).join('');
}

function filterModels() {
  renderModels();
}

async function loadModel(modelId) {
  try {
    await apiRequest('POST', '/api/models/load', { model_id: modelId });
    showToast('Model ' + modelId + ' loaded successfully', 'success');
    refreshModels();
  } catch (err) {
    showToast('Failed to load model: ' + err.message, 'error');
  }
}

async function unloadModel(modelId) {
  openModal('Unload Model', '<p>Are you sure you want to unload <strong>' + sanitize(modelId) + '</strong>?</p>', 'Unload', async function() {
    try {
      await apiRequest('POST', '/api/models/unload', { model_id: modelId });
      showToast('Model ' + modelId + ' unloaded', 'success');
      refreshModels();
    } catch (err) {
      showToast('Failed to unload model: ' + err.message, 'error');
    }
  });
}

function showLoadModelModal() {
  openModal('Load Model',
    '<div class="form-group">' +
    '  <label class="form-label">Model ID / Name</label>' +
    '  <input type="text" class="form-input" id="loadModelInput" placeholder="e.g. gpt-3.5-turbo">' +
    '</div>',
    'Load',
    async function() {
      const modelId = $('loadModelInput').value.trim();
      if (modelId) {
        await loadModel(modelId);
      }
    }
  );
  setTimeout(function() { $('loadModelInput')?.focus(); }, 100);
}

/* ============================================================
   Inference Page
   ============================================================ */

async function loadModelsForInference() {
  const select = $('inferenceModel');
  try {
    const data = await apiRequest('GET', '/api/models');
    const models = data.models || data || [];
    select.innerHTML = '<option value="">-- Select a model --</option>' +
      models
        .filter(function(m) { return (m.status || 'unloaded') === 'loaded'; })
        .map(function(m) {
          const id = m.id || m.model_id || '';
          return '<option value="' + sanitize(id) + '">' + sanitize(m.name || id) + '</option>';
        }).join('');
    if (models.length === 0) {
      select.innerHTML += '<option value="" disabled>No loaded models available</option>';
    }
  } catch (err) {
    select.innerHTML = '<option value="">Error loading models</option>';
  }
}

async function runInference() {
  const model = $('inferenceModel').value;
  const prompt = $('promptInput').value.trim();
  const maxTokens = parseInt($('inferenceMaxTokens').value) || CONFIG.defaultMaxTokens;
  const temperature = parseFloat($('inferenceTemperature').value) || CONFIG.defaultTemperature;
  const stream = $('inferenceStream').checked;

  if (!model) {
    showToast('Please select a model', 'warning');
    return;
  }
  if (!prompt) {
    showToast('Please enter a prompt', 'warning');
    return;
  }

  // UI state
  $('inferenceBtn').classList.add('hidden');
  $('stopInferenceBtn').classList.remove('hidden');
  const responseArea = $('responseArea');
  responseArea.textContent = '';
  responseArea.classList.add('streaming');
  STATE.isStreaming = true;
  $('tokenCount').textContent = 'Tokens: 0';

  if (stream) {
    await runInferenceStreaming(model, prompt, maxTokens, temperature);
  } else {
    await runInferenceDirect(model, prompt, maxTokens, temperature);
  }
}

async function runInferenceDirect(model, prompt, maxTokens, temperature) {
  try {
    STATE.inferenceAbortController = new AbortController();
    const response = await apiRequest('POST', '/api/inference', {
      model: model,
      prompt: prompt,
      max_tokens: maxTokens,
      temperature: temperature,
      stream: false,
    });
    const text = typeof response === 'string' ? response :
      response.text || response.response || response.content || JSON.stringify(response);
    $('responseArea').textContent = text;
    $('tokenCount').textContent = 'Tokens: ~' + (text.split(/\s+/).length || 0);
  } catch (err) {
    if (err.name !== 'AbortError') {
      $('responseArea').textContent = 'Error: ' + err.message;
      showToast('Inference failed: ' + err.message, 'error');
    }
  } finally {
    STATE.inferenceAbortController = null;
    resetInferenceUI();
  }
}

async function runInferenceStreaming(model, prompt, maxTokens, temperature) {
  // Try WebSocket first, fall back to SSE via fetch
  const wsUrl = CONFIG.apiBase.replace(/^http/, 'ws').replace(/\/+$/, '') + '/ws/inference';

  if (window.WebSocket) {
    try {
      await new Promise(function(resolve, reject) {
        const ws = new WebSocket(wsUrl);
        STATE.inferenceWs = ws;
        let tokenCount = 0;
        let timeout = setTimeout(function() {
          reject(new Error('WebSocket connection timeout'));
        }, 10000);

        ws.onopen = function() {
          clearTimeout(timeout);
          ws.send(JSON.stringify({
            model: model,
            prompt: prompt,
            max_tokens: maxTokens,
            temperature: temperature,
          }));
        };

        ws.onmessage = function(event) {
          try {
            const data = JSON.parse(event.data);
            if (data.error) {
              reject(new Error(data.error));
              return;
            }
            if (data.token) {
              $('responseArea').textContent += data.token;
              tokenCount++;
              $('tokenCount').textContent = 'Tokens: ' + tokenCount;
            }
            if (data.done || data.finished) {
              resolve();
            }
          } catch (e) {
            // Plain text
            $('responseArea').textContent += event.data;
            tokenCount++;
            $('tokenCount').textContent = 'Tokens: ' + tokenCount;
          }
        };

        ws.onerror = function() {
          clearTimeout(timeout);
          reject(new Error('WebSocket connection failed'));
        };

        ws.onclose = function() {
          clearTimeout(timeout);
          resolve();
        };
      });
      return;
    } catch (wsErr) {
      // WebSocket failed, fall through to SSE
      STATE.inferenceWs = null;
      console.warn('WebSocket failed, falling back to SSE:', wsErr.message);
    }
  }

  // Fallback: fetch with streaming
  try {
    STATE.inferenceAbortController = new AbortController();
    const url = CONFIG.apiBase.replace(/\/+$/, '') + '/api/inference';
    const response = await fetch(url, {
      method: 'POST',
      headers: getApiHeaders(),
      body: JSON.stringify({
        model: model,
        prompt: prompt,
        max_tokens: maxTokens,
        temperature: temperature,
        stream: true,
      }),
      signal: STATE.inferenceAbortController.signal,
    });

    if (!response.ok) {
      throw new Error('HTTP ' + response.status);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let tokenCount = 0;
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6).trim();
          if (data === '[DONE]') continue;
          try {
            const parsed = JSON.parse(data);
            const text = parsed.token || parsed.text || parsed.content || '';
            if (text) {
              $('responseArea').textContent += text;
              tokenCount++;
              $('tokenCount').textContent = 'Tokens: ' + tokenCount;
            }
          } catch (e) {
            // Plain text data
            if (data && data !== '[DONE]') {
              $('responseArea').textContent += data;
              tokenCount++;
              $('tokenCount').textContent = 'Tokens: ' + tokenCount;
            }
          }
        }
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      $('responseArea').textContent += '\n\nError: ' + err.message;
      showToast('Streaming inference error: ' + err.message, 'error');
    }
  } finally {
    STATE.inferenceAbortController = null;
    resetInferenceUI();
  }
}

function stopInference() {
  if (STATE.inferenceWs) {
    STATE.inferenceWs.close();
    STATE.inferenceWs = null;
  }
  if (STATE.inferenceAbortController) {
    STATE.inferenceAbortController.abort();
    STATE.inferenceAbortController = null;
  }
  STATE.isStreaming = false;
  resetInferenceUI();
  $('responseArea').classList.remove('streaming');
}

function resetInferenceUI() {
  $('inferenceBtn').classList.remove('hidden');
  $('stopInferenceBtn').classList.add('hidden');
  $('responseArea').classList.remove('streaming');
  STATE.isStreaming = false;
}

function clearPrompt() {
  $('promptInput').value = '';
  $('promptInput').focus();
}

function clearResponse() {
  $('responseArea').textContent = 'Response will appear here...';
  $('tokenCount').textContent = 'Tokens: 0';
}

function copyResponse() {
  const text = $('responseArea').textContent;
  if (text && text !== 'Response will appear here...') {
    navigator.clipboard.writeText(text).then(function() {
      showToast('Response copied to clipboard', 'success');
    }).catch(function() {
      showToast('Failed to copy', 'error');
    });
  }
}

/* ============================================================
   Context Page
   ============================================================ */

async function refreshContext() {
  $('contextList').innerHTML = '<div class="text-center" style="grid-column:1/-1;padding:48px;"><div class="spinner"></div></div>';
  try {
    const data = await apiRequest('GET', '/api/context');
    STATE.contexts = data.contexts || data || [];
    renderContexts();
  } catch (err) {
    $('contextList').innerHTML = '<div class="text-center text-danger" style="grid-column:1/-1;padding:48px;">Error: ' + sanitize(err.message) + '</div>';
  }
}

function renderContexts() {
  const container = $('contextList');
  const search = ($('contextSearch')?.value || '').toLowerCase();

  const filtered = STATE.contexts.filter(function(c) {
    const id = (c.id || '').toLowerCase();
    const preview = (c.preview || c.content || '').toLowerCase().substring(0, 100);
    return !search || id.includes(search) || preview.includes(search);
  });

  if (filtered.length === 0) {
    container.innerHTML =
      '<div class="empty-state" style="grid-column:1/-1;">' +
      '  <div class="empty-state-icon">&#9776;</div>' +
      '  <div class="empty-state-title">No Context Entries</div>' +
      '  <div class="empty-state-text">No conversation context found. Run inference to create context entries.</div>' +
      '</div>';
    $('contextBadge').textContent = '0';
    return;
  }

  $('contextBadge').textContent = filtered.length;
  container.innerHTML = filtered.map(function(c) {
    const id = c.id || c.context_id || 'unknown';
    const tokens = c.tokens || c.token_count || 0;
    const preview = c.preview || c.content || '';
    const truncated = preview.length > 200 ? preview.substring(0, 200) + '...' : preview;
    return '<div class="context-item" onclick="viewContext(\'' + sanitize(id) + '\')">' +
      '<div class="context-item-header">' +
      '  <span class="context-item-id">' + sanitize(id) + '</span>' +
      '  <span class="context-item-tokens">' + tokens + ' tokens</span>' +
      '</div>' +
      '<div class="context-item-preview">' + sanitize(truncated) + '</div>' +
      '</div>';
  }).join('');
}

function filterContext() {
  renderContexts();
}

function viewContext(contextId) {
  const ctx = STATE.contexts.find(function(c) {
    return (c.id || c.context_id) === contextId;
  });
  if (!ctx) {
    showToast('Context not found', 'error');
    return;
  }
  const content = ctx.content || ctx.preview || 'No content';
  openModal('Context: ' + sanitize(contextId),
    '<div class="form-group">' +
    '  <label class="form-label">Content</label>' +
    '  <div class="code-block" style="max-height:400px;overflow-y:auto;">' + sanitize(content) + '</div>' +
    '</div>' +
    '<div class="form-group">' +
    '  <label class="form-label">Tokens: ' + (ctx.tokens || ctx.token_count || 0) + '</label>' +
    '</div>',
    'Delete',
    function() { deleteContext(contextId); }
  );
}

async function deleteContext(contextId) {
  try {
    await apiRequest('DELETE', '/api/context/' + encodeURIComponent(contextId));
    showToast('Context deleted', 'success');
    refreshContext();
  } catch (err) {
    showToast('Failed to delete context: ' + err.message, 'error');
  }
}

async function clearAllContext() {
  openModal('Clear All Context',
    '<p>Are you sure you want to delete all context entries? This action cannot be undone.</p>',
    'Clear All',
    async function() {
      try {
        await apiRequest('DELETE', '/api/context');
        showToast('All context cleared', 'success');
        refreshContext();
      } catch (err) {
        showToast('Failed to clear context: ' + err.message, 'error');
      }
    }
  );
}

/* ============================================================
   Logs Page
   ============================================================ */

async function refreshLogs() {
  const viewer = $('logViewer');
  try {
    const data = await apiRequest('GET', '/api/logs?limit=' + CONFIG.maxLogEntries);
    STATE.logs = data.logs || data || [];
    renderLogs();
  } catch (err) {
    viewer.innerHTML = '<div class="text-center text-danger" style="padding:24px;">Error: ' + sanitize(err.message) + '</div>';
  }
}

function renderLogs() {
  const viewer = $('logViewer');
  const levelFilter = $('logLevel')?.value || 'all';
  const search = ($('logSearch')?.value || '').toLowerCase();

  // Apply minimum level filter from settings
  const levelOrder = { debug: 0, info: 1, warn: 2, error: 3 };
  const minLevel = levelOrder[CONFIG.logLevel] || 1;

  const filtered = STATE.logs.filter(function(log) {
    const level = (log.level || 'info').toLowerCase();
    const msg = (log.message || '').toLowerCase();
    const matchesLevel = levelFilter === 'all' || level === levelFilter;
    const matchesMinLevel = (levelOrder[level] || 1) >= minLevel;
    const matchesSearch = !search || msg.includes(search);
    return matchesLevel && matchesMinLevel && matchesSearch;
  });

  if (filtered.length === 0) {
    viewer.innerHTML = '<div class="text-center text-muted" style="padding:24px;">No log entries found</div>';
    return;
  }

  // Show last N entries
  const display = filtered.slice(-CONFIG.maxLogEntries);
  viewer.innerHTML = display.map(function(log) {
    const level = (log.level || 'info').toLowerCase();
    const timestamp = log.timestamp ? formatTimestamp(log.timestamp) : '-';
    const message = log.message || '';
    return '<div class="log-entry">' +
      '<span class="log-timestamp">' + sanitize(timestamp) + '</span>' +
      '<span class="log-level ' + level + '">' + sanitize(level) + '</span>' +
      '<span class="log-message">' + sanitize(message) + '</span>' +
      '</div>';
  }).join('');

  viewer.scrollTop = viewer.scrollHeight;
}

function filterLogs() {
  renderLogs();
}

function clearLogs() {
  STATE.logs = [];
  renderLogs();
}

function addLogEntry(log) {
  STATE.logs.push(log);
  if (STATE.logs.length > CONFIG.maxLogEntries * 2) {
    STATE.logs = STATE.logs.slice(-CONFIG.maxLogEntries);
  }
  if (STATE.currentPage === 'logs') {
    renderLogs();
  }
}

function toggleLogAutoRefresh() {
  if ($('autoRefreshLogs').checked) {
    startLogAutoRefresh();
  } else {
    stopLogAutoRefresh();
  }
}

function startLogAutoRefresh() {
  stopLogAutoRefresh();
  STATE.logTimer = setInterval(function() {
    refreshLogs();
  }, 3000);
}

function stopLogAutoRefresh() {
  if (STATE.logTimer) {
    clearInterval(STATE.logTimer);
    STATE.logTimer = null;
  }
}

/* ============================================================
   Plugins Page
   ============================================================ */

async function refreshPlugins() {
  $('pluginList').innerHTML = '<div class="text-center" style="grid-column:1/-1;padding:48px;"><div class="spinner"></div></div>';
  try {
    const data = await apiRequest('GET', '/api/plugins');
    STATE.plugins = data.plugins || data || [];
    renderPlugins();
  } catch (err) {
    $('pluginList').innerHTML = '<div class="text-center text-danger" style="grid-column:1/-1;padding:48px;">Error: ' + sanitize(err.message) + '</div>';
  }
}

function renderPlugins() {
  const container = $('pluginList');
  const search = ($('pluginSearch')?.value || '').toLowerCase();
  const statusFilter = $('pluginStatusFilter')?.value || 'all';

  const filtered = STATE.plugins.filter(function(p) {
    const name = (p.name || '').toLowerCase();
    const desc = (p.description || '').toLowerCase();
    const matchesSearch = !search || name.includes(search) || desc.includes(search);
    const isEnabled = p.enabled !== false;
    const matchesStatus = statusFilter === 'all' ||
      (statusFilter === 'enabled' && isEnabled) ||
      (statusFilter === 'disabled' && !isEnabled);
    return matchesSearch && matchesStatus;
  });

  if (filtered.length === 0) {
    container.innerHTML =
      '<div class="empty-state" style="grid-column:1/-1;">' +
      '  <div class="empty-state-icon">&#9881;</div>' +
      '  <div class="empty-state-title">No Plugins</div>' +
      '  <div class="empty-state-text">No plugins found matching your filters.</div>' +
      '</div>';
    return;
  }

  container.innerHTML = filtered.map(function(p) {
    const isEnabled = p.enabled !== false;
    const pluginId = p.id || p.name || 'unknown';
    return '<div class="plugin-card">' +
      '<div class="plugin-card-header">' +
      '  <div>' +
      '    <div class="plugin-card-name">' + sanitize(p.name || pluginId) + '</div>' +
      '    <div class="plugin-card-version">v' + sanitize(p.version || '0.0.0') + '</div>' +
      '  </div>' +
      '  <span class="badge ' + (isEnabled ? 'badge-success' : 'badge-neutral') + '">' +
          (isEnabled ? 'Enabled' : 'Disabled') +
      '  </span>' +
      '</div>' +
      '<div class="plugin-card-description">' + sanitize(p.description || 'No description') + '</div>' +
      '<div class="plugin-card-footer">' +
      '  <span class="text-sm text-muted">' + sanitize(p.author || '') + '</span>' +
      '  <label class="toggle">' +
      '    <input type="checkbox" ' + (isEnabled ? 'checked' : '') + ' onchange="togglePlugin(\'' + sanitize(pluginId) + '\', this.checked)">' +
      '    <span class="toggle-slider"></span>' +
      '  </label>' +
      '</div>' +
      '</div>';
  }).join('');
}

function filterPlugins() {
  renderPlugins();
}

async function togglePlugin(pluginId, enabled) {
  try {
    await apiRequest('POST', '/api/plugins/' + encodeURIComponent(pluginId) + '/toggle', { enabled: enabled });
    showToast('Plugin ' + pluginId + ' ' + (enabled ? 'enabled' : 'disabled'), 'success');
    refreshPlugins();
  } catch (err) {
    showToast('Failed to toggle plugin: ' + err.message, 'error');
    refreshPlugins();
  }
}

/* ============================================================
   Settings Page
   ============================================================ */

function loadSettings() {
  $('settingAutoRefresh').checked = CONFIG.autoRefresh;
  $('settingRefreshInterval').value = CONFIG.refreshInterval;
  $('settingCpuThreshold').value = CONFIG.cpuThreshold;
  $('settingTempThreshold').value = CONFIG.tempThreshold;
  $('settingDefaultMaxTokens').value = CONFIG.defaultMaxTokens;
  $('settingDefaultTemp').value = CONFIG.defaultTemperature;
  $('settingStreaming').checked = CONFIG.streamingEnabled;
  $('settingLogLevel').value = CONFIG.logLevel;
  $('settingMaxLogs').value = CONFIG.maxLogEntries;
  $('settingApiUrl').value = CONFIG.apiBase;
  $('settingApiToken').value = CONFIG.apiToken;
}

function saveSettings() {
  CONFIG.autoRefresh = $('settingAutoRefresh').checked;
  CONFIG.refreshInterval = parseInt($('settingRefreshInterval').value) || 5;
  CONFIG.cpuThreshold = parseInt($('settingCpuThreshold').value) || 90;
  CONFIG.tempThreshold = parseInt($('settingTempThreshold').value) || 80;
  CONFIG.defaultMaxTokens = parseInt($('settingDefaultMaxTokens').value) || 1024;
  CONFIG.defaultTemperature = parseFloat($('settingDefaultTemp').value) || 0.7;
  CONFIG.streamingEnabled = $('settingStreaming').checked;
  CONFIG.logLevel = $('settingLogLevel').value;
  CONFIG.maxLogEntries = parseInt($('settingMaxLogs').value) || 500;
  CONFIG.apiBase = $('settingApiUrl').value.trim();
  CONFIG.apiToken = $('settingApiToken').value.trim();

  // Persist
  localStorage.setItem('ainos_api_url', CONFIG.apiBase);
  localStorage.setItem('ainos_api_token', CONFIG.apiToken);
  localStorage.setItem('ainos_refresh_interval', String(CONFIG.refreshInterval));
  localStorage.setItem('ainos_max_logs', String(CONFIG.maxLogEntries));
  localStorage.setItem('ainos_default_max_tokens', String(CONFIG.defaultMaxTokens));
  localStorage.setItem('ainos_default_temp', String(CONFIG.defaultTemperature));
  localStorage.setItem('ainos_streaming', String(CONFIG.streamingEnabled));
  localStorage.setItem('ainos_log_level', CONFIG.logLevel);
  localStorage.setItem('ainos_cpu_threshold', String(CONFIG.cpuThreshold));
  localStorage.setItem('ainos_temp_threshold', String(CONFIG.tempThreshold));
  localStorage.setItem('ainos_auto_refresh', String(CONFIG.autoRefresh));

  // Restart timers
  setupRefreshTimer();
  showToast('Settings saved', 'success');
}

async function testConnection() {
  const resultEl = $('connectionTestResult');
  resultEl.textContent = 'Testing...';
  resultEl.style.color = 'var(--text-secondary)';
  try {
    const data = await apiRequest('GET', '/api/status');
    resultEl.textContent = 'Connected (status: ' + (data.status || 'ok') + ')';
    resultEl.style.color = 'var(--success)';
  } catch (err) {
    resultEl.textContent = 'Failed: ' + err.message;
    resultEl.style.color = 'var(--danger)';
  }
}

/* ============================================================
   Refresh Timer
   ============================================================ */

function setupRefreshTimer() {
  if (STATE.refreshTimer) {
    clearInterval(STATE.refreshTimer);
    STATE.refreshTimer = null;
  }
  if (CONFIG.autoRefresh) {
    STATE.refreshTimer = setInterval(function() {
      if (STATE.currentPage === 'dashboard') {
        updateDashboard();
      }
    }, CONFIG.refreshInterval * 1000);
  }
}

/* ============================================================
   Theme Toggle
   ============================================================ */

function toggleTheme() {
  const currentBg = getComputedStyle(document.documentElement).getPropertyValue('--bg-primary').trim();
  if (currentBg === '#0a0a1a' || currentBg === '#1a1a2e') {
    // Switch to light theme
    document.documentElement.style.setProperty('--bg-primary', '#f5f5f5');
    document.documentElement.style.setProperty('--bg-secondary', '#ffffff');
    document.documentElement.style.setProperty('--bg-card', '#ffffff');
    document.documentElement.style.setProperty('--bg-card-hover', '#f0f0f0');
    document.documentElement.style.setProperty('--bg-input', '#ffffff');
    document.documentElement.style.setProperty('--bg-sidebar', '#ffffff');
    document.documentElement.style.setProperty('--bg-header', '#ffffff');
    document.documentElement.style.setProperty('--text-primary', '#1a1a2e');
    document.documentElement.style.setProperty('--text-secondary', '#616161');
    document.documentElement.style.setProperty('--text-muted', '#9e9e9e');
    document.documentElement.style.setProperty('--border', '#e0e0e0');
    document.documentElement.style.setProperty('--border-light', '#bdbdbd');
    document.documentElement.style.setProperty('--shadow', '0 4px 6px rgba(0,0,0,0.1)');
    document.documentElement.style.setProperty('--shadow-lg', '0 8px 24px rgba(0,0,0,0.15)');
    localStorage.setItem('ainos_theme', 'light');
  } else {
    // Switch to dark theme
    document.documentElement.style.setProperty('--bg-primary', '#0a0a1a');
    document.documentElement.style.setProperty('--bg-secondary', '#1a1a2e');
    document.documentElement.style.setProperty('--bg-card', '#16213e');
    document.documentElement.style.setProperty('--bg-card-hover', '#1c2a52');
    document.documentElement.style.setProperty('--bg-input', '#0f1a30');
    document.documentElement.style.setProperty('--bg-sidebar', '#0d1117');
    document.documentElement.style.setProperty('--bg-header', '#0d1117');
    document.documentElement.style.setProperty('--text-primary', '#e0e0e0');
    document.documentElement.style.setProperty('--text-secondary', '#9e9e9e');
    document.documentElement.style.setProperty('--text-muted', '#616161');
    document.documentElement.style.setProperty('--border', '#2a2a4a');
    document.documentElement.style.setProperty('--border-light', '#3a3a5a');
    document.documentElement.style.setProperty('--shadow', '0 4px 6px rgba(0,0,0,0.3)');
    document.documentElement.style.setProperty('--shadow-lg', '0 8px 24px rgba(0,0,0,0.4)');
    localStorage.setItem('ainos_theme', 'dark');
  }
}

function loadTheme() {
  const theme = localStorage.getItem('ainos_theme');
  if (theme === 'light') {
    toggleTheme();
  }
}

/* ============================================================
   Refresh All
   ============================================================ */

function refreshAll() {
  updateDashboard();
  if (STATE.currentPage === 'models') refreshModels();
  if (STATE.currentPage === 'context') refreshContext();
  if (STATE.currentPage === 'logs') refreshLogs();
  if (STATE.currentPage === 'plugins') refreshPlugins();
  showToast('Refreshing all data...', 'info', 1500);
}

/* ============================================================
   Keyboard Shortcuts
   ============================================================ */

document.addEventListener('keydown', function(e) {
  // Ctrl+Enter: Run inference from any page
  if (e.ctrlKey && e.key === 'Enter') {
    if (STATE.currentPage === 'inference' && !STATE.isStreaming) {
      runInference();
    }
  }
  // Escape: Close modal
  if (e.key === 'Escape') {
    closeModal();
  }
  // Ctrl+L: Focus log search
  if (e.ctrlKey && e.key === 'l') {
    e.preventDefault();
    if ($('logSearch')) {
      navigateTo('logs');
      setTimeout(function() { $('logSearch').focus(); }, 100);
    }
  }
  // Ctrl+K: Focus model search
  if (e.ctrlKey && e.key === 'k') {
    e.preventDefault();
    if ($('modelSearch')) {
      navigateTo('models');
      setTimeout(function() { $('modelSearch').focus(); }, 100);
    }
  }
});

/* ============================================================
   Window Resize Handler
   ============================================================ */

let resizeTimeout;
window.addEventListener('resize', function() {
  clearTimeout(resizeTimeout);
  resizeTimeout = setTimeout(function() {
    renderCharts();
  }, 200);
});

/* ============================================================
   Initialization
   ============================================================ */

function init() {
  // Load theme
  loadTheme();

  // Load settings into UI
  loadSettings();

  // Connect SSE
  connectSSE();

  // Initial data load
  updateDashboard();

  // Setup refresh timer
  setupRefreshTimer();

  // Start log auto-refresh if on logs page
  if ($('autoRefreshLogs').checked) {
    startLogAutoRefresh();
  }

  // Hide loading screen
  setTimeout(function() {
    const loading = $('loadingScreen');
    if (loading) {
      loading.classList.add('hidden');
      setTimeout(function() { loading.style.display = 'none'; }, 500);
    }
  }, 800);

  // Set build time
  $('aboutBuildTime').textContent = new Date().toISOString();

  console.log('AinosOS Dashboard initialized');
  console.log('API Base:', CONFIG.apiBase);
  console.log('Auto-refresh:', CONFIG.autoRefresh ? 'enabled (' + CONFIG.refreshInterval + 's)' : 'disabled');
}

// Start when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}