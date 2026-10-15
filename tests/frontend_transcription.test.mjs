import test from 'node:test';
import assert from 'node:assert/strict';
import { transcribe, executeWithJobSupport, loadTranscriptionJob } from '../qualia/frontend/src/lib/api.js';
import { auditDownload } from '../qualia/frontend/src/lib/transcript-download.js';

const response = (status, data) => ({ status, ok: status < 400, json: async () => data });

class FakeStream {
  static latest;
  constructor() { FakeStream.latest = this; this.handlers = {}; this.closed = false; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  close() { this.closed = true; }
  emit(name, data) { this.handlers[name]({ data: JSON.stringify(data) }); }
}

test('transcribe normalizes a sync response and preserves filename', async () => {
  const file = new File(['audio'], 'sample.wav');
  const envelope = { status: 'success', filename: file.name, result: { transcription: 'Olá' } };
  globalThis.fetch = async () => response(200, envelope);
  assert.deepEqual(await transcribe('transcription', file), envelope);
});

test('already completed job resolves without waiting for a lost SSE event', async () => {
  globalThis.EventSource = FakeStream;
  const result = { transcription: 'Participant 3\nOlá', exports: { txt: { content: 'Olá' } } };
  globalThis.fetch = async (url) => url.startsWith('/jobs/')
    ? response(200, { status: 'completed', result })
    : response(202, { job_id: '123', stream_url: '/jobs/123/stream' });
  const output = await transcribe('transcription_structured', new File(['audio'], 'sample.wav'));
  assert.deepEqual(output.result, result);
  assert.equal(output.filename, 'sample.wav');
  assert.equal(FakeStream.latest.closed, true);
});

test('running job reports progress then resolves via SSE', async () => {
  globalThis.EventSource = FakeStream;
  const progress = [];
  globalThis.fetch = async (url) => url.startsWith('/jobs/')
    ? response(200, { status: 'running' })
    : response(202, { job_id: '123', stream_url: '/jobs/123/stream' });
  const output = executeWithJobSupport('/transcribe/x', {}, { onProgress: (e) => progress.push(e.status) });
  await new Promise(resolve => setImmediate(resolve));
  FakeStream.latest.emit('completed', { status: 'completed', result: { transcription: 'Done' } });
  assert.deepEqual(await output, { transcription: 'Done' });
  assert.deepEqual(progress, ['running', 'completed']);
});

test('cancelled or failed jobs reject rather than leave the page waiting', async () => {
  globalThis.EventSource = FakeStream;
  for (const status of ['cancelled', 'failed']) {
    globalThis.fetch = async (url) => url.startsWith('/jobs/')
      ? response(200, { status })
      : response(202, { job_id: '123', stream_url: '/jobs/123/stream' });
    await assert.rejects(executeWithJobSupport('/transcribe/x'), new RegExp(status));
    assert.equal(FakeStream.latest.closed, true);
  }
});

test('job completing between initial snapshot and SSE subscription still resolves', async () => {
  globalThis.EventSource = FakeStream;
  let snapshots = 0;
  globalThis.fetch = async (url) => url.startsWith('/jobs/')
    ? response(200, ++snapshots === 1 ? { status: 'running' } : { status: 'completed', result: { ok: true } })
    : response(202, { job_id: '123', stream_url: '/jobs/123/stream' });
  const output = executeWithJobSupport('/transcribe/x');
  await new Promise(resolve => setImmediate(resolve));
  FakeStream.latest.onopen();
  assert.deepEqual(await output, { ok: true });
});

test('SSE failure falls back to polling and rejects cancelled jobs', async () => {
  globalThis.EventSource = FakeStream;
  const originalInterval = globalThis.setInterval;
  const originalClear = globalThis.clearInterval;
  let poll;
  let cleared = false;
  globalThis.setInterval = callback => { poll = callback; return 99; };
  globalThis.clearInterval = () => { cleared = true; };
  let snapshots = 0;
  globalThis.fetch = async (url) => url.startsWith('/jobs/')
    ? response(200, { status: ++snapshots === 1 ? 'running' : 'cancelled' })
    : response(202, { job_id: '123', stream_url: '/jobs/123/stream' });
  try {
    const output = executeWithJobSupport('/transcribe/x');
    await new Promise(resolve => setImmediate(resolve));
    FakeStream.latest.onerror();
    const rejected = assert.rejects(output, /cancelled/);
    await poll();
    await rejected;
    assert.equal(cleared, true);
  } finally {
    globalThis.setInterval = originalInterval;
    globalThis.clearInterval = originalClear;
  }
});

test('audit JSON preserves uncertain words and provenance', () => {
  const result = { words: [{ word: 'Olá', start: null, speaker: '' }], provenance: { source_sha256: 'hash' } };
  assert.deepEqual(JSON.parse(auditDownload(result).content), result);
});

test('reopen existing transcription only reads the job and never uploads audio', async () => {
  globalThis.EventSource = FakeStream;
  const result = { transcription: 'Participant 2\nOlá', exports: { txt: { content: 'Olá' } } };
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push([url, options.method || 'GET']);
    return response(200, { status: 'completed', plugin_id: 'transcription_structured', result });
  };
  assert.deepEqual((await loadTranscriptionJob('transcription_structured', 'existing-job')).result, result);
  assert.ok(calls.every(([url, method]) => url === '/jobs/existing-job' && method === 'GET'));
});

test('existing job from another plugin is rejected before opening a stream', async () => {
  globalThis.fetch = async () => response(200, { plugin_id: 'another-plugin' });
  await assert.rejects(loadTranscriptionJob('transcription_structured', 'wrong-job'), /different transcriber/);
});
