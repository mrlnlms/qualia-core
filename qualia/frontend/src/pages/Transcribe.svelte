<script>
  import { onMount, onDestroy } from 'svelte';
  import { plugins, pluginsByType, navigate } from '../lib/stores.js';
  import { fetchPluginSchema, transcribe, loadTranscriptionJob } from '../lib/api.js';
  import { downloadTranscript, auditDownload } from '../lib/transcript-download.js';
  import ParamForm from '../components/ParamForm.svelte';
  import FileUpload from '../components/FileUpload.svelte';
  import { typeConfig } from '../lib/constants.js';

  const AUDIO_ACCEPT = '.mp3,.mp4,.mpeg,.mpga,.m4a,.wav,.webm,.ogg,.opus,.flac';

  let { pluginId = null } = $props();

  const plugin = $derived($plugins.find(p => p.id === pluginId) || null);

  let schema = $state(null);
  let configValues = $state({});
  let file = $state(null);
  let loading = $state(false);
  let loadingStatus = $state('');
  let loadingElapsed = $state(0);
  let loadingTimer = null;
  let result = $state(null);
  let error = $state('');
  let copied = $state(false);

  const tconf = $derived(plugin ? (typeConfig[plugin.type] || typeConfig.document) : typeConfig.document);

  onMount(async () => {
    if (!pluginId) return;
    try {
      const s = await fetchPluginSchema(pluginId);
      schema = s.parameters || s;
      const jobId = new URLSearchParams(window.location.search).get('job');
      if (jobId) {
        loading = true;
        startTimer('Opening transcription...');
        result = await loadTranscriptionJob(pluginId, jobId, { onProgress: showProgress });
        const settings = result.result?.provenance?.configuration;
        if (settings && schema.recover_speakers) {
          configValues = { ...configValues, language: settings.language, device: settings.device,
            speech_boundaries: !!settings.speech_boundary_policy,
            recover_speakers: !!settings.speaker_recovery_policy };
        }
      }
    } catch (e) {
      error = e.message || 'Failed to load plugin schema';
    } finally {
      stopTimer();
      loading = false;
    }
  });

  onDestroy(() => { if (loadingTimer) clearInterval(loadingTimer); });

  function startTimer(status) {
    loadingStatus = status;
    loadingElapsed = 0;
    loadingTimer = setInterval(() => loadingElapsed++, 1000);
  }
  function stopTimer() {
    clearInterval(loadingTimer);
    loadingTimer = null;
    loadingElapsed = 0;
    loadingStatus = '';
  }

  function showProgress(job) {
    loadingStatus = job.status === 'pending' ? 'Queued — waiting to transcribe...' : 'Processing audio...';
    if (job.id) {
      const url = new URL(window.location.href);
      url.searchParams.set('job', job.id);
      window.history.replaceState(null, '', url);
    }
  }

  async function runTranscription() {
    if (!pluginId || !file) return;
    loading = true;
    error = '';
    result = null;
    startTimer('Uploading and transcribing...');
    try {
      result = await transcribe(pluginId, file, configValues, { onProgress: showProgress });
    } catch (e) {
      error = typeof e.message === 'string' ? e.message : JSON.stringify(e.message);
    } finally {
      stopTimer();
      loading = false;
    }
  }

  async function copyText() {
    if (result?.result?.transcription) {
      await navigator.clipboard.writeText(result.result.transcription);
      copied = true;
      setTimeout(() => copied = false, 2000);
    }
  }
</script>

<div class="page">
  {#if !pluginId}
    <!-- Plugin picker -->
    <div class="picker">
      <div class="picker-hero">
        <svg class="picker-illus" width="220" height="100" viewBox="0 0 220 100" fill="none">
          <rect x="10" y="16" width="72" height="58" rx="4" stroke="var(--accent)" stroke-width="1.5" fill="var(--accent-dim)"/>
          <rect x="22" y="36" width="3" height="20" rx="1.5" fill="var(--accent)" opacity="0.4"/>
          <rect x="28" y="28" width="3" height="36" rx="1.5" fill="var(--accent)" opacity="0.6"/>
          <rect x="34" y="32" width="3" height="28" rx="1.5" fill="var(--accent)" opacity="0.5"/>
          <rect x="40" y="24" width="3" height="44" rx="1.5" fill="var(--accent)" opacity="0.7"/>
          <rect x="46" y="30" width="3" height="32" rx="1.5" fill="var(--accent)" opacity="0.55"/>
          <rect x="52" y="26" width="3" height="40" rx="1.5" fill="var(--accent)" opacity="0.65"/>
          <rect x="58" y="34" width="3" height="24" rx="1.5" fill="var(--accent)" opacity="0.45"/>
          <rect x="64" y="38" width="3" height="16" rx="1.5" fill="var(--accent)" opacity="0.35"/>
          <rect x="70" y="32" width="3" height="28" rx="1.5" fill="var(--accent)" opacity="0.5"/>
          <path d="M90 45 L112 45" stroke="var(--border)" stroke-width="1.5"/>
          <polygon points="110,40 120,45 110,50" fill="var(--border)"/>
          <rect x="128" y="16" width="72" height="58" rx="4" stroke="var(--accent)" stroke-width="1.5" fill="var(--bg-card)"/>
          <line x1="140" y1="32" x2="188" y2="32" stroke="var(--accent)" stroke-width="1" opacity="0.25"/>
          <line x1="140" y1="40" x2="182" y2="40" stroke="var(--accent)" stroke-width="1" opacity="0.25"/>
          <line x1="140" y1="48" x2="186" y2="48" stroke="var(--accent)" stroke-width="1" opacity="0.25"/>
          <line x1="140" y1="56" x2="172" y2="56" stroke="var(--accent)" stroke-width="1" opacity="0.25"/>
          <rect x="140" y="62" width="8" height="2" rx="1" fill="var(--accent)" opacity="0.5"/>
        </svg>
        <h1 class="picker-title">Transcribe</h1>
        <p class="picker-desc">
          Convert audio and video into text. Supports multiple languages and formats.
        </p>
        <div class="picker-features">
          <span class="picker-feat">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 2v6M4.5 6l2.5 2 2.5-2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 10h8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
            Drag &amp; drop files
          </span>
          <span class="picker-feat">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 4h10M2 7h7M2 10h9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
            MP3, MP4, WAV, OGG, FLAC
          </span>
        </div>
      </div>
      <div class="picker-grid">
        {#each $pluginsByType.document.filter(p => p.provides.includes('transcription')) as p, i}
          <button class="picker-card" style="animation-delay: {i * 50}ms" onclick={() => navigate('transcribe', p.id)}>
            <span class="pc-name">{p.name}</span>
            <span class="pc-desc">{p.description}</span>
            <div class="pc-tags">
              {#each p.provides.slice(0, 4) as tag}
                <span class="pc-tag">{tag}</span>
              {/each}
            </div>
          </button>
        {/each}
      </div>
    </div>
  {:else if plugin}
    <!-- Plugin page -->
    <div class="workspace" class:has-result={!!result?.result}>
      <div class="col-input">
        <div class="plugin-hero" class:compact={!!result}>
          <button class="back-link" onclick={() => navigate('transcribe')}>
            &larr; all transcribers
          </button>
          <div class="plugin-header">
            <span class="type-badge" style:--tc={tconf.color} style:--tbg={tconf.bg}>{tconf.label}</span>
            <span class="plugin-version">{plugin.version}</span>
          </div>
          <h1 class="plugin-name">{plugin.name}</h1>
          {#if !result}
            <p class="plugin-desc">{plugin.description}</p>
            <div class="plugin-provides">
              {#each plugin.provides as tag}
                <span class="provide-tag">{tag}</span>
              {/each}
            </div>
          {/if}
        </div>

        {#if schema}
          <div class="field">
            <label class="field-label" for="transcribe-file">file</label>
            <FileUpload id="transcribe-file" bind:file accept={AUDIO_ACCEPT} maxSize={(pluginId === 'transcription' ? 25 : 500) * 1024 * 1024} />
          </div>

          <div class="field">
            <ParamForm parameters={schema} bind:values={configValues} />
          </div>

          <button class="run-btn" onclick={runTranscription} disabled={loading || !file}>
            {#if loading}
              <span class="spinner"></span> transcribing
            {:else}
              transcribe
            {/if}
          </button>
        {/if}

        {#if loadingStatus}
          <div class="progress">
            <div class="progress-track"><div class="progress-fill"></div></div>
            <div class="progress-info">
              <span class="progress-status">{loadingStatus}</span>
              <span class="progress-t">{loadingElapsed}s</span>
            </div>
          </div>
        {/if}

        {#if error}
          <div class="err">{error}</div>
        {/if}
      </div>

      {#if result?.result}
        <div class="col-result">
          <div class="result-panel">
            <div class="result-bar">
              <span class="result-label">Transcription</span>
              <button class="copy-btn" class:copied onclick={copyText}>
                {copied ? 'copied' : 'copy'}
              </button>
            </div>
            {#if result.result.detected_language || result.result.language || result.result.duration}
              <div class="result-meta">
                {#if result.result.detected_language || result.result.language}<span class="meta-item">{result.result.detected_language || result.result.language}</span>{/if}
                {#if result.result.duration}<span class="meta-item">{result.result.duration.toFixed(1)}s</span>{/if}
                {#if result.filename}<span class="meta-item">{result.filename}</span>{/if}
              </div>
            {/if}
            {#if result.result.exports}
              <div class="download-bar">
                {#each Object.entries(result.result.exports) as [format, artifact]}
                  <button class="copy-btn" onclick={() => downloadTranscript(artifact)}>Download {format.toUpperCase()}</button>
                {/each}
                <button class="copy-btn" onclick={() => downloadTranscript(auditDownload(result.result))}>Download audit JSON</button>
              </div>
              <p class="review-note">
                Speakers are automatic labels, not verified identities.
                {result.result.review?.length || 0} words flagged for review.
                {#if result.result.words?.some(w => w.flags?.includes('speaker_inferred'))}
                  {result.result.words.filter(w => w.flags?.includes('speaker_inferred')).length} speaker labels inferred or reconciled; check the audit JSON.
                {/if}
                {#if result.result.quality_audit?.internal_repetitions?.length || result.result.quality_audit?.repeated_segment_runs?.length}
                  Repetition detected: check these passages against the audio.
                {/if}
                Download the files before leaving this page.
              </p>
            {/if}
            <textarea class="transcription-text" readonly value={result.result.transcription}></textarea>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .page { max-width: 100%; }

  /* Picker */
  .picker {
    max-width: 700px;
    margin: 0 auto;
    padding-top: 40px;
  }

  .picker-title {
    font-family: var(--font-serif);
    font-size: 1.6em;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 6px;
  }

  .picker-hero {
    text-align: center;
    margin-bottom: 32px;
    animation: fadeUp 0.35s ease backwards;
  }

  .picker-illus {
    margin-bottom: 20px;
    opacity: 0.8;
  }

  .picker-desc {
    font-size: 0.9em;
    color: var(--text-secondary);
    line-height: 1.6;
    margin-bottom: 14px;
    max-width: 400px;
    margin-left: auto;
    margin-right: auto;
  }

  .picker-features {
    display: flex;
    gap: 20px;
    justify-content: center;
    flex-wrap: wrap;
    margin-bottom: 8px;
  }

  .picker-feat {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.78em;
    color: var(--text-muted);
  }

  .picker-feat svg {
    color: var(--accent);
    flex-shrink: 0;
  }

  .picker-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
  }

  .picker-card {
    text-align: left;
    padding: 18px 20px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    cursor: pointer;
    transition: all var(--transition);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .picker-card { animation: fadeUp 0.3s ease backwards; }

  .picker-card:hover {
    border-color: var(--accent);
    transform: translateY(-1px);
    box-shadow: var(--shadow-sm);
  }

  .pc-name { font-size: 0.95em; font-weight: 600; color: var(--text-primary); }
  .pc-desc { font-size: 0.82em; color: var(--text-secondary); line-height: 1.5; }
  .pc-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
  .pc-tag { font-size: 0.66em; font-family: var(--font-mono); padding: 2px 7px; background: var(--bg-input); border-radius: var(--radius); color: var(--text-muted); }

  /* Plugin page */
  .back-link {
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 0.78em;
    font-family: var(--font-mono);
    padding: 0;
    margin-bottom: 16px;
    cursor: pointer;
    transition: color var(--transition);
  }

  .back-link:hover { color: var(--accent); }

  .plugin-hero { margin-bottom: 24px; }
  .plugin-hero.compact { margin-bottom: 20px; }

  .plugin-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }

  .type-badge {
    font-size: 0.66em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--tc);
    padding: 2px 8px;
    background: var(--tbg);
    border-radius: var(--radius);
  }

  .plugin-version { font-size: 0.7em; color: var(--text-muted); font-family: var(--font-mono); }

  .plugin-name {
    font-family: var(--font-serif);
    font-size: 1.5em;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 8px;
  }

  .plugin-hero.compact .plugin-name { font-size: 1.2em; margin-bottom: 4px; }

  .plugin-desc {
    font-size: 0.88em;
    color: var(--text-secondary);
    line-height: 1.6;
    margin-bottom: 14px;
    max-width: 440px;
  }

  .plugin-provides { display: flex; flex-wrap: wrap; gap: 6px; }

  .provide-tag {
    font-size: 0.7em;
    font-family: var(--font-mono);
    padding: 3px 10px;
    background: var(--accent-dim);
    color: var(--accent);
    border-radius: var(--radius);
  }

  /* Workspace two-col */
  .workspace { display: flex; gap: 32px; align-items: flex-start; }

  .col-input { flex: 0 0 auto; width: 420px; min-width: 300px; max-width: 420px; }
  .workspace:not(.has-result) .col-input { max-width: 520px; width: auto; flex: 1; }
  .col-result { flex: 1; min-width: 0; position: sticky; top: 0; }

  .field { margin-bottom: 18px; }
  .field-label { display: block; font-size: 0.7em; font-family: var(--font-mono); color: var(--text-muted); letter-spacing: 0.5px; margin-bottom: 6px; }

  .run-btn {
    padding: 7px 18px;
    background: transparent;
    color: var(--accent);
    border: 1px solid var(--accent);
    border-radius: var(--radius);
    font-size: 0.8em;
    font-family: var(--font-mono);
    transition: all var(--transition);
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }

  .run-btn:hover:not(:disabled) { background: var(--accent); color: #fff; }
  .run-btn:disabled { opacity: 0.35; cursor: not-allowed; }

  .spinner { width: 12px; height: 12px; border: 1.5px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.6s linear infinite; }

  .progress { margin-top: 8px; padding: 10px 14px; border: 1px solid var(--border); border-radius: var(--radius); }
  .progress-track { height: 2px; background: var(--bg-input); overflow: hidden; margin-bottom: 8px; }
  .progress-fill { height: 100%; width: 40%; background: var(--accent); animation: progressSlide 1.5s ease-in-out infinite; }

  .progress-info { display: flex; justify-content: space-between; }
  .progress-status { font-size: 0.76em; font-family: var(--font-mono); color: var(--text-muted); }
  .progress-t { font-size: 0.7em; color: var(--text-muted); font-family: var(--font-mono); }

  .err { margin-top: 14px; padding: 10px 14px; background: var(--error-bg); border-left: 2px solid var(--error); color: var(--text-primary); font-size: 0.82em; }

  /* Result */
  .result-panel { border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
  .result-bar { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; background: var(--bg-secondary); border-bottom: 1px solid var(--border-subtle); }
  .result-label { font-size: 0.82em; font-weight: 500; color: var(--text-primary); }

  .copy-btn {
    padding: 3px 10px;
    background: transparent;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-muted);
    font-size: 0.72em;
    font-family: var(--font-mono);
    transition: all var(--transition);
  }

  .copy-btn:hover { border-color: var(--accent); color: var(--accent); }
  .copy-btn.copied { border-color: var(--accent-green); color: var(--accent-green); }

  .result-meta { display: flex; gap: 12px; padding: 8px 16px; border-bottom: 1px solid var(--border-subtle); }
  .download-bar { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 16px; }
  .review-note { padding: 0 16px 12px; font-size: 0.78em; line-height: 1.6; color: var(--text-secondary); }
  .meta-item { font-size: 0.72em; font-family: var(--font-mono); color: var(--text-muted); }

  .transcription-text {
    width: 100%;
    min-height: 280px;
    padding: 16px;
    background: transparent;
    border: none;
    color: var(--text-primary);
    font-size: 0.88em;
    line-height: 1.8;
    resize: vertical;
    outline: none;
    font-family: var(--font-sans);
  }

  @media (max-width: 900px) {
    .workspace { flex-direction: column; }
    .col-input, .col-result { max-width: 100%; width: 100%; }
    .col-result { position: static; }
  }
</style>
