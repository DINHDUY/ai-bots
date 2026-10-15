import type { Credential } from "../../api/client";
import type { AgentOverrides, PreviewFile, RuntimeChoice, SourceFile } from "../../api/imports.generated";
import { RuntimeFields } from "./RuntimeFields";

export function AgentFileCard({ file, preview, error, defaults, credentials, onChange, onRemove, onReplace }: {
  file: SourceFile; preview?: PreviewFile; error?: string; defaults: RuntimeChoice;
  credentials: Credential[]; onChange: (overrides: AgentOverrides) => void;
  onRemove: () => void; onReplace: (file: File) => void;
}) {
  const overrides = file.overrides ?? {};
  return <section className="import-file" aria-label={file.filename}>
    <div className="import-file-heading"><h3>{file.filename}</h3><button type="button" onClick={onRemove}>Remove</button></div>
    <label className="import-replace">Replace file<input type="file" accept=".md" onChange={event => {
      const next = event.target.files?.[0]; if (next) onReplace(next); event.target.value = "";
    }} /></label>
    {error ? <p role="alert" className="error">{error}</p> : null}
    <div className="import-grid">
      <label>Bot name<input value={overrides.name ?? preview?.name ?? file.filename.replace(/(?:\.agent)?\.md$/i, "")}
        maxLength={80} onChange={event => onChange({ ...overrides, name: event.target.value })} /></label>
      <label>Public purpose<textarea value={overrides.purpose ?? preview?.purpose ?? ""} rows={2} maxLength={400}
        onChange={event => onChange({ ...overrides, purpose: event.target.value })} /></label>
    </div>
    <p className="muted">Name and public purpose are visible in the workspace bot directory.</p>
    <label className="import-check"><input type="checkbox" checked={!!overrides.runtime} onChange={event => onChange({ ...overrides, runtime: event.target.checked ? { ...defaults } : null })} />Use different runtime settings for this bot</label>
    {overrides.runtime ? <RuntimeFields value={overrides.runtime} credentials={credentials} onChange={runtime => onChange({ ...overrides, runtime })} /> : null}
    {preview?.errors?.map((item, index) => <p key={index} role="alert" className="error">{item.field}: {item.message}</p>)}
    {preview?.warnings?.map((warning, index) => <p key={index}>{warning}</p>)}
    {preview ? <details><summary>Instructions · {[...preview.instructions].length} characters</summary><pre className="import-body">{preview.instructions}</pre></details> : null}
  </section>;
}
