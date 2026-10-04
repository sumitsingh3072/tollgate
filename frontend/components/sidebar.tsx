"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/keys", label: "Keys" },
  { href: "/logs", label: "Logs" },
  { href: "/playground", label: "Playground" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-full border-b bg-muted/40 p-4 md:w-56 md:shrink-0 md:border-b-0 md:border-r">
      <div className="mb-4 text-lg font-semibold">Tollgate Lite</div>
      <nav className="flex gap-1 md:flex-col">
        {NAV.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className={`rounded-md px-3 py-2 text-sm hover:bg-muted ${
              pathname === href ? "bg-muted font-medium" : "text-muted-foreground"
            }`}
          >
            {label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
