import { FlaskConicalIcon, KeyRoundIcon, LayoutGridIcon, ScrollTextIcon, type LucideIcon } from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon; description: string };

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/", label: "Overview", icon: LayoutGridIcon, description: "Traffic, tokens, cache hit rate and latency." },
  { href: "/keys", label: "Keys", icon: KeyRoundIcon, description: "Create, inspect and revoke gateway API keys." },
  { href: "/logs", label: "Logs", icon: ScrollTextIcon, description: "Every request with model, tokens and status." },
  {
    href: "/playground",
    label: "Playground",
    icon: FlaskConicalIcon,
    description: "Chat with any alias and inspect gateway headers.",
  },
];

export function findNavItem(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => (item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)));
}
