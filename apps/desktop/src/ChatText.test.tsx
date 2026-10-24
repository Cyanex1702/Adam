import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ChatText } from "./ChatText";

it("renders readable emphasis, lists and fenced code", () => {
  const html = renderToStaticMarkup(<ChatText text={"## Answer\n**A clear result**\n\n- First\n- Second\n\n```python\nprint('hello')\n```"} />);
  expect(html).toContain("<h3>Answer</h3>");
  expect(html).toContain("<strong>A clear result</strong>");
  expect(html).toContain("<li>First</li>");
  expect(html).toContain("<pre><code>");
});

it("keeps model HTML, media and links inert", () => {
  const html = renderToStaticMarkup(<ChatText text={'<script>alert(1)</script>\n<img src="https://remote.invalid/private">\n[link](javascript:alert(1))'} />);
  expect(html).not.toContain("<script>");
  expect(html).not.toContain("<img");
  expect(html).not.toContain("<a ");
  expect(html).toContain("&lt;script&gt;");
});

it("displays an unfinished streaming code block without hiding text", () => {
  const html = renderToStaticMarkup(<ChatText text={"```\n**literal code"} />);
  expect(html).toContain("<pre><code>**literal code</code></pre>");
});
