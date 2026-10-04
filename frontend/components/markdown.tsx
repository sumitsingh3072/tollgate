import "katex/dist/katex.min.css";

import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { cn } from "@/lib/utils";

/** react-markdown passes its AST node as a prop; keep it off the DOM element. */
function withoutNode<T extends { node?: unknown }>(props: T): Omit<T, "node"> {
  const { node, ...rest } = props;
  void node;
  return rest;
}

// Element styles instead of a typography plugin: keeps model output on the dashboard's dense type
// scale and theme tokens. Raw HTML in model output is not rendered (react-markdown default).
const components: Components = {
  a: (props) => (
    <a {...withoutNode(props)} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2" />
  ),
  table: (props) => (
    <div className="my-2 overflow-x-auto">
      <table {...withoutNode(props)} className="w-full border-collapse text-xs" />
    </div>
  ),
  th: (props) => <th {...withoutNode(props)} className="border-b px-2 py-1 text-left font-medium" />,
  td: (props) => <td {...withoutNode(props)} className="border-b border-border/60 px-2 py-1 align-top" />,
  pre: (props) => (
    <pre {...withoutNode(props)} className="my-2 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed" />
  ),
  code: ({ className, ...props }) => (
    <code {...withoutNode(props)} className={cn(className ?? "rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]")} />
  ),
};

/** Model output rendered as GitHub-flavoured markdown with $math$. Safe for partial (streaming) text. */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div
      className={cn(
        "space-y-2 break-words",
        "[&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-[15px] [&_h2]:font-semibold [&_h3]:font-semibold [&_h4]:font-medium",
        "[&_h1]:mt-3 [&_h2]:mt-3 [&_h3]:mt-2 [&>:first-child]:mt-0",
        "[&_ul]:list-disc [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:pl-5 [&_li]:my-0.5 [&_li>p]:my-0",
        "[&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground",
        "[&_hr]:my-3 [&_hr]:border-border [&_strong]:font-semibold",
        "[&_pre_code]:bg-transparent [&_pre_code]:p-0",
        className,
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
