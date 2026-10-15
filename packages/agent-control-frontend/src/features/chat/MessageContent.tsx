import Markdown from "react-markdown";
import { useLayoutEffect } from "react";
import remarkGfm from "remark-gfm";
export default function MessageContent({
  text,
  onRendered,
}: {
  text: string;
  onRendered: () => void;
}) {
  useLayoutEffect(onRendered, [text, onRendered]);
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      skipHtml
      components={{
        a: (props) => (
          <a {...props} target="_blank" rel="noopener noreferrer" />
        ),
        img: () => <span className="muted">[Image omitted]</span>,
      }}
    >
      {text}
    </Markdown>
  );
}
