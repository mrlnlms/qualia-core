/** Stateless UTF-8 downloads. Revoke object URLs after the click is consumed. */
export function downloadTranscript(artifact) {
  const blob = new Blob([artifact.content], { type: artifact.media_type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = artifact.filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function auditDownload(result) {
  return {
    filename: 'transcript.audit.json', media_type: 'application/json;charset=utf-8',
    content: JSON.stringify(result, null, 2) + '\n',
  };
}
