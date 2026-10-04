import { auth } from "@clerk/nextjs/server";
import Link from "next/link";

import { Logo } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { CLERK_ENABLED } from "@/lib/auth-config";

const LINKS = [
  { href: "#unique", label: "Why Tollgate" },
  { href: "#features", label: "Features" },
  { href: "#how-it-works", label: "How it works" },
  { href: "#quickstart", label: "Quickstart" },
];

export async function SiteNav() {
  // Local mode has no accounts: the dashboard is always one click away.
  const signedIn = CLERK_ENABLED ? Boolean((await auth()).userId) : true;
  return (
    <header className="sticky top-0 z-40 border-b border-transparent bg-background/80 backdrop-blur supports-backdrop-filter:bg-background/60">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4 md:px-6">
        <Logo />
        <nav className="hidden items-center gap-1 md:flex" aria-label="Main">
          {LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              {link.label}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          {signedIn ? (
            <Button size="sm" render={<Link href="/dashboard" />}>
              Open dashboard
            </Button>
          ) : (
            <>
              <Button size="sm" variant="ghost" render={<Link href="/sign-in" />}>
                Sign in
              </Button>
              <Button size="sm" render={<Link href="/sign-up" />}>
                Get started
              </Button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
