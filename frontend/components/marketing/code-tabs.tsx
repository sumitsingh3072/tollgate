"use client";

import { CopyButton } from "@/components/copy-button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function snippets(gatewayUrl: string): { id: string; label: string; code: string }[] {
  return [
    {
      id: "python",
      label: "Python",
      code: `from openai import OpenAI

client = OpenAI(
    base_url="${gatewayUrl}/v1",  # the only change
    api_key="tg_live_...",
)

stream = client.chat.completions.create(
    model="smart",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")`,
    },
    {
      id: "node",
      label: "Node.js",
      code: `import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "${gatewayUrl}/v1", // the only change
  apiKey: "tg_live_...",
});

const reply = await client.chat.completions.create({
  model: "fast",
  messages: [{ role: "user", content: "Hello!" }],
});
console.log(reply.choices[0].message.content);`,
    },
    {
      id: "curl",
      label: "cURL",
      code: `curl ${gatewayUrl}/v1/chat/completions \\
  -H "Authorization: Bearer tg_live_..." \\
  -H "Content-Type: application/json" \\
  -d '{"model": "smart-terse", "messages": [{"role": "user", "content": "Hello!"}]}' \\
  -i   # see x-tollgate-model, x-tollgate-cache, x-tollgate-fallback`,
    },
  ];
}

export function CodeTabs({ gatewayUrl }: { gatewayUrl: string }) {
  const items = snippets(gatewayUrl);
  return (
    <Tabs defaultValue="python" className="gap-0 overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <TabsList>
          {items.map((s) => (
            <TabsTrigger key={s.id} value={s.id}>
              {s.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
      {items.map((s) => (
        <TabsContent key={s.id} value={s.id} className="relative">
          <div className="absolute top-3 right-3">
            <CopyButton value={s.code} />
          </div>
          <pre className="overflow-x-auto p-4 pr-28 font-mono text-[12.5px] leading-relaxed">
            <code>{s.code}</code>
          </pre>
        </TabsContent>
      ))}
    </Tabs>
  );
}
