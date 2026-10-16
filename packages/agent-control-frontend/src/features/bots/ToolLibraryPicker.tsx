import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type ToolSelection, type ToolState, type ToolSpec } from "../../api/client";
import styles from "./tools.module.css";

const key = (tool: ToolSelection) => `${tool.library_id}/${tool.tool_id}`;
const selection = (tool: ToolSpec): ToolSelection => ({ library_id: tool.library_id, tool_id: tool.tool_id, version: tool.version, configuration: {} });

export function ToolLibraryPicker({ framework, value, onChange, state, disabled = false }: {
  framework: string; value: ToolSelection[]; onChange: (next: ToolSelection[]) => void; state?: ToolState; disabled?: boolean;
}) {
  const [search, setSearch] = useState("");
  const catalog = useQuery({ queryKey: ["tool-libraries", framework], queryFn: () => api<{ libraries: ToolSpec[] }>(`/api/tool-libraries?framework=${encodeURIComponent(framework)}`) });
  const specs = catalog.data?.libraries ?? [];
  const libraries = [...new Set(specs.map(t => t.library_id))];
  const ready = value.filter(t => {
    const spec = specs.find(s => key(s) === key(t) && s.version === t.version);
    const saved = state?.bindings.find(b => key(b) === key(t) && b.version === t.version && b.configuration.resource_id === t.configuration.resource_id);
    return spec?.compatible && (!spec.resource || !!t.configuration.resource_id) && saved?.ready !== false;
  }).length;
  return <section className={styles.picker} aria-label="Tool libraries">
    <h3>Tools <small>{value.length} selected · {ready} configured</small></h3>
    <p>Choose what this bot can use. Added tools become available on its next task. Removing a tool cancels its pending actions.</p>
    <div className={styles.bar}>
      <input aria-label="Search tools" type="search" placeholder="Search tools" value={search} onChange={e => setSearch(e.target.value)} />
      <button type="button" disabled={disabled || !catalog.data} onClick={() => onChange([...value, ...specs.filter(t => t.compatible && /^(sandbox|windows)\./.test(t.library_id) && !value.some(v => key(v) === key(t))).map(selection)])}>Computer basics</button>
      <button type="button" disabled={disabled || !value.length} onClick={() => onChange([])}>Clear</button>
    </div>
    {!value.length ? <p>{framework === "open_interface" ? "Select macOS desktop control to run a Mac task." : framework === "ufo" ? "Select Windows desktop control to run a Windows task." : "No tools selected. This bot can respond in chat."}</p> : null}
    {catalog.isPending ? <p role="status">Loading tool libraries…</p> : null}
    {catalog.isError ? <p role="alert">Could not load tool libraries. <button type="button" onClick={() => void catalog.refetch()}>Retry</button></p> : null}
    {libraries.map(id => {
      const tools = specs.filter(t => t.library_id === id && `${t.library_name} ${t.name} ${t.description}`.toLowerCase().includes(search.toLowerCase()));
      if (!tools.length) return null;
      const selected = value.filter(t => t.library_id === id).length;
      return <details key={id} open={!!search || undefined}>
        <summary>{tools[0].library_name}{selected ? ` · ${selected} selected` : ""}</summary>
        {tools.map(tool => {
          const entries = value.filter(t => key(t) === key(tool));
          return <div key={tool.tool_id} className={styles.tool}>
            <label className={styles.check}>
              <input type="checkbox" checked={!!entries.length} disabled={disabled || (!tool.compatible && !entries.length)} onChange={e => onChange(e.target.checked ? [...value, selection(tool)] : value.filter(t => key(t) !== key(tool)))} />
              <span>{tool.name}{tool.bundle ? " (bundle)" : ""}</span>
            </label>
            <p>{tool.description}</p>
            {!tool.compatible ? <p>{tool.reason}</p> : null}
            {state?.bindings.filter(b => key(b) === key(tool) && !b.ready && entries.some(e => e.configuration.resource_id === b.configuration.resource_id)).map((b, i) => <p key={i}>{b.reason}</p>)}
            {tool.resource && entries.map((entry, index) => <div key={index}>
              <label> {tool.resource === "connector" ? "Repository connection" : "Taught task version"}
                <select disabled={disabled} value={entry.configuration.resource_id ?? ""} onChange={e => {
                  const next = { ...entry, configuration: e.target.value ? { resource_id: e.target.value } : {} };
                  onChange(value.map(v => v === entry ? next : v));
                }}>
                  <option value="">Needs setup — choose a resource</option>
                  {(state?.resources[tool.resource!] ?? []).filter(r => r.id === entry.configuration.resource_id || !entries.some(v => v.configuration.resource_id === r.id)).map(r => <option key={r.id} value={r.id}>{r.name} · {r.id.slice(-8)}</option>)}
                </select>
              </label>
              <button type="button" disabled={disabled} onClick={() => onChange(value.filter(v => v !== entry))}>Remove binding</button>
            </div>)}
            {tool.resource && entries.length ? <>
              <p>Manage connections and taught tasks in Toolkit after creating the bot.</p>
              <button type="button" disabled={disabled || entries.some(v => !v.configuration.resource_id)} onClick={() => onChange([...value, selection(tool)])}>Add another binding</button>
            </> : null}
          </div>;
        })}
      </details>;
    })}
    {value.filter(v => catalog.data && !specs.some(s => key(s) === key(v) && s.version === v.version)).map((v, index) => <p key={index} role="status">Unavailable: {v.tool_id} {v.version} <button type="button" disabled={disabled} onClick={() => onChange(value.filter(t => t !== v))}>Remove</button></p>)}
    {state?.editable === false ? <p>Only the bot owner can change its tools.</p> : null}
  </section>;
}
