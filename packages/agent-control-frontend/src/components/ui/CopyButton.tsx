import { useState } from "react";
import { Icon } from "./Icon";
export function CopyButton({
  text,
  label = "Copy",
}: {
  text: string;
  label?: string;
}) {
  const [result, setResult] = useState("");
  return (
    <span className="row">
      <button
        type="button"
        className="ghost"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text);
            setResult("Copied");
          } catch {
            setResult("Select the text to copy");
          }
        }}
      >
        <Icon name="copy" />
        {label}
      </button>
      <span className="copy-status" role="status">
        {result}
      </span>
    </span>
  );
}
