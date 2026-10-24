import { Fragment, type ReactNode } from "react";

function inline(text: string) {
  return text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={index}>{part.slice(2, -2)}</strong> :
      part.startsWith("`") && part.endsWith("`") ? <code key={index}>{part.slice(1, -1)}</code> : <Fragment key={index}>{part}</Fragment>);
}

export function ChatText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let code: string[] | null = null, paragraph: string[] = [], items: string[] = [];
  function flush() {
    if (paragraph.length) { blocks.push(<p key={blocks.length}>{inline(paragraph.join("\n"))}</p>); paragraph = []; }
    if (items.length) { blocks.push(<ul key={blocks.length}>{items.map((item, index) => <li key={index}>{inline(item)}</li>)}</ul>); items = []; }
  }
  for (const line of text.split("\n")) {
    if (line.trimStart().startsWith("```")) {
      flush();
      if (code) { blocks.push(<pre key={blocks.length}><code>{code.join("\n")}</code></pre>); code = null; }
      else code = [];
    } else if (code) code.push(line);
    else if (!line.trim()) flush();
    else if (/^#{1,3}\s/.test(line)) { flush(); blocks.push(<h3 key={blocks.length}>{inline(line.replace(/^#{1,3}\s+/, ""))}</h3>); }
    else if (/^\s*(?:[-*]|\d+\.)\s+/.test(line)) { if (paragraph.length) flush(); items.push(line.replace(/^\s*(?:[-*]|\d+\.)\s+/, "")); }
    else { if (items.length) flush(); paragraph.push(line); }
  }
  flush();
  if (code) blocks.push(<pre key={blocks.length}><code>{code.join("\n")}</code></pre>);
  // Text nodes only: no HTML injection, embedded media or automatic external links.
  return <div className="formatted-answer">{blocks}</div>;
}
