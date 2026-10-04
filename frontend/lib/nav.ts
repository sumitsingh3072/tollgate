import {
  DatabaseZapIcon,
  FlaskConicalIcon,
  KeyRoundIcon,
  LayoutGridIcon,
  ScaleIcon,
  ScrollTextIcon,
  type LucideIcon,
} from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon; description: string };

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Overview", icon: LayoutGridIcon, description: "Traffic, tokens, cache hit rate and latency." },
  { href: "/dashboard/keys", label: "Keys", icon: KeyRoundIcon, description: "Create, inspect and revoke gateway API keys." },
  { href: "/dashboard/logs", label: "Logs", icon: ScrollTextIcon, description: "Every request with model, tokens and status." },
  {
    href: "/dashboard/cache",
    label: "Cache",
    icon: DatabaseZapIcon,
    description: "Hit rate, memory, evictions and what the admission filter kept out.",
  },
  {
    href: "/dashboard/fairness",
    label: "Fairness",
    icon: ScaleIcon,
    description: "How model capacity is shared between keys, live.",
  },
  {
    href: "/dashboard/playground",
    label: "Playground",
    icon: FlaskConicalIcon,
    description: "Chat with any alias and inspect gateway headers.",
  },
];

export function findNavItem(pathname: string): NavItem | undefined {
  // Longest match wins, so /dashboard/keys is "Keys", not "Overview".
  return [...NAV_ITEMS]
    .sort((a, b) => b.href.length - a.href.length)
    .find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`));
}
