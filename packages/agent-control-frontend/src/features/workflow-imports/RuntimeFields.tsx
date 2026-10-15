import { Link } from "react-router-dom";
import { providersFor, suggestedModel, type Credential } from "../../api/client";
import type { ImportTool, RuntimeChoice } from "../../api/imports.generated";
import { ToolLibraryPicker } from "../bots/ToolLibraryPicker";
import { messagingTool } from "../workspace/channel";

export function RuntimeFields({ value, onChange, credentials }: {
  value: RuntimeChoice; onChange: (next: RuntimeChoice) => void; credentials: Credential[];
}) {
  const framework = value.framework ?? "microsoft";
  const keys = credentials.filter(key => providersFor(framework)?.includes(key.provider));
  return <div className="import-runtime">
    <div className="import-grid">
      <label>Framework<select value={framework} onChange={event => {
        const next = event.target.value;
        const key = credentials.find(item => providersFor(next)?.includes(item.provider));
        onChange({ framework: next, credential_id: key?.id ?? "", model: key ? suggestedModel(key.provider) : "", tool_selection: null });
      }}><option value="microsoft">Microsoft</option><option value="anthropic">Anthropic</option></select></label>
      <label>API key<select value={value.credential_id ?? ""} onChange={event => {
        const key = keys.find(item => item.id === event.target.value);
        onChange({ ...value, credential_id: key?.id ?? "", model: key ? suggestedModel(key.provider) : "" });
      }}><option value="">Choose an API key</option>{keys.map(key => <option key={key.id} value={key.id}>{key.label}</option>)}</select></label>
      <label>Model<input value={value.model ?? ""} maxLength={128} onChange={event => onChange({ ...value, model: event.target.value })} /></label>
    </div>
    {!keys.length ? <p>No compatible API key. <Link to="/keys" target="_blank" rel="noopener">Add an API key in a new tab</Link>, then return here.</p> : null}
    <details><summary>Computer tools</summary>
      <label className="import-check"><input type="checkbox" checked={value.tool_selection == null} onChange={event => onChange({ ...value, tool_selection: event.target.checked ? null : [] })} />Use standard computer tools</label>
      {value.tool_selection != null ? <ToolLibraryPicker framework={framework}
        value={[...value.tool_selection.filter(tool => tool.library_id !== messagingTool.library_id).map(tool => ({ ...tool, configuration: tool.configuration ?? {} })), messagingTool]}
        onChange={selection => onChange({ ...value, tool_selection: selection.filter(tool => tool.library_id !== messagingTool.library_id).map((tool): ImportTool => ({ ...tool, configuration: tool.configuration.resource_id ? { resource_id: tool.configuration.resource_id } : {} })) })} /> : null}
      <p>Bot channel messaging stays enabled for every imported bot. Connections and taught tasks can be configured after import.</p>
    </details>
  </div>;
}
