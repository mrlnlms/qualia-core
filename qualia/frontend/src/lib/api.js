const BASE = '';

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const message = err.detail || err.message || res.statusText;
    throw { message: typeof message === 'string' ? message : JSON.stringify(message) };
  }
  return res.json();
}

export function fetchHealth() {
  return request('/health');
}

export function fetchPlugins(type = null) {
  const url = type ? `/plugins?plugin_type=${type}` : '/plugins';
  return request(url);
}

export function fetchPlugin(id) {
  return request(`/plugins/${id}`);
}

export function fetchPluginSchema(id) {
  return request(`/plugins/${id}/schema`);
}

export function fetchConsolidated() {
  return request('/config/consolidated');
}

export function resolveConfig(pluginId, textSize) {
  return request('/config/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plugin_id: pluginId, text_size: textSize }),
  });
}

export function analyze(pluginId, text, config = {}, context = {}) {
  return request(`/analyze/${pluginId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, config, context }),
  });
}

export async function analyzeFile(pluginId, file, config = {}) {
  const form = new FormData();
  form.append('file', file);
  form.append('config', JSON.stringify(config));
  return request(`/analyze/${pluginId}/file`, { method: 'POST', body: form });
}

export async function transcribe(pluginId, file, config = {}, callbacks = {}) {
  const form = new FormData();
  form.append('file', file);
  form.append('config', JSON.stringify(config));
  const response = await executeWithJobSupport(`/transcribe/${pluginId}`, { method: 'POST', body: form }, callbacks);
  // Sync returns an envelope; jobs return the plugin result directly.
  return response?.status === 'success' && response.result
    ? response
    : { status: 'success', plugin_id: pluginId, filename: file.name, result: response };
}

export async function executePipeline(steps, { text, file } = {}) {
  const form = new FormData();
  form.append('steps', JSON.stringify(steps));
  if (file) form.append('file', file);
  if (text) form.append('text', text);
  return request('/pipeline', { method: 'POST', body: form });
}

export function visualize(pluginId, data, config = {}, outputFormat = 'html') {
  return request(`/visualize/${pluginId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data, config, output_format: outputFormat }),
  });
}

export function createMonitorStream(onMessage, onError) {
  const source = new EventSource(`${BASE}/monitor/stream`);
  source.onmessage = (e) => onMessage(JSON.parse(e.data));
  source.onerror = onError;
  return source;
}

// --- Async Job Support ---

export function fetchJob(jobId) {
  return request(`/jobs/${jobId}`);
}

export function fetchJobs(params = {}) {
  const query = new URLSearchParams(params).toString();
  return request(`/jobs${query ? '?' + query : ''}`);
}

export function cancelJob(jobId) {
  return request(`/jobs/${jobId}`, { method: 'DELETE' });
}

/**
 * Executes a request that may return sync (200) or async (202).
 * For 202, opens SSE stream and waits for completion.
 * Uses fetch() directly to preserve HTTP status code.
 *
 * @param {string} url - API endpoint
 * @param {object} options - fetch options (method, headers, body)
 * @param {object} callbacks - { onProgress }
 * @returns {Promise} resolves with result data
 */
export async function executeWithJobSupport(url, options = {}, { onProgress } = {}) {
  const res = await fetch(`${BASE}${url}`, options);
  const data = await res.json();

  if (!res.ok) {
    throw { message: data.detail || data.message || `Request failed: ${res.status}` };
  }

  // Sync — return directly
  if (res.status === 200) {
    return data;
  }

  // Async — open SSE and wait for completion
  if (res.status === 202) {
    const { job_id, stream_url } = data;
    return watchJob(job_id, stream_url, { onProgress });
  }

  return data;
}

/** Reopen an existing transcription without submitting another upload. */
export async function loadTranscriptionJob(pluginId, jobId, callbacks = {}) {
  const id = encodeURIComponent(jobId);
  const job = await fetchJob(id);
  if (job.plugin_id !== pluginId) throw new Error('This job belongs to a different transcriber.');
  const result = await watchJob(id, `/jobs/${id}/stream`, callbacks);
  return { status: 'success', plugin_id: pluginId, result };
}

function watchJob(job_id, stream_url, { onProgress } = {}) {
  return new Promise((resolve, reject) => {
      const eventSource = new EventSource(`${BASE}${stream_url}`);
      let fallbackTimer = null;
      let settled = false;

      const finish = (event) => {
        if (settled) return true;
        if (onProgress) onProgress(event);
        if (!['completed', 'failed', 'cancelled'].includes(event.status)) return false;
        settled = true;
        eventSource.close();
        clearInterval(fallbackTimer);
        if (event.status === 'completed') resolve(event.result);
        else reject(new Error(event.error || `Job ${event.status}`));
        return true;
      };

      const startPollingFallback = () => {
        if (settled || fallbackTimer) return;
        eventSource.close();
        fallbackTimer = setInterval(async () => {
          if (settled) return;
          try {
            const resp = await request(`/jobs/${job_id}`);
            finish(resp);
          } catch (e) {
            if (settled) return;
            settled = true;
            clearInterval(fallbackTimer);
            reject(e);
          }
        }, 3000);
      };

      eventSource.addEventListener('status', (e) => {
        const ev = JSON.parse(e.data);
        finish(ev);
      });

      eventSource.addEventListener('step', (e) => {
        const ev = JSON.parse(e.data);
        finish(ev);
      });

      eventSource.addEventListener('completed', (e) => {
        const ev = JSON.parse(e.data);
        finish(ev);
      });

      eventSource.onerror = () => {
        startPollingFallback();
      };

      // A fast/cached job can finish before SSE subscribes. Read current state
      // after attaching listeners so that the terminal event cannot be missed.
      const refresh = () => request(`/jobs/${job_id}`).then(finish).catch(startPollingFallback);
      eventSource.onopen = refresh;
      refresh();
  });
}
