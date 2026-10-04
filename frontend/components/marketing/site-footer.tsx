import Link from "next/link";

import { Logo } from "@/components/logo";
import { GATEWAY_URL } from "@/lib/api";

export function SiteFooter() {
  return (
    <footer className="border-t">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 text-muted-foreground sm:flex-row sm:items-center sm:justify-between md:px-6">
        <div className="flex items-center gap-3">
          <Logo />
          <span className="text-xs">OpenAI-compatible LLM gateway</span>
        </div>
        <nav className="flex gap-4 text-xs" aria-label="Footer">
          <a href={`${GATEWAY_URL}/docs`} className="hover:text-foreground">
            API reference
          </a>
          <Link href="/dashboard" className="hover:text-foreground">
            Dashboard
          </Link>
        </nav>
      </div>
    </footer>
  );
}
