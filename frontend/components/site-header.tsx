"use client";

import { usePathname } from "next/navigation";

import { UserButton } from "@clerk/nextjs";

import { CommandMenu } from "@/components/command-menu";
import { ThemeToggle } from "@/components/theme-toggle";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { findNavItem } from "@/lib/nav";

export function SiteHeader() {
  const item = findNavItem(usePathname());

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
      <SidebarTrigger className="-ml-1 text-muted-foreground" />
      <Separator orientation="vertical" className="mr-1 data-vertical:h-4 data-vertical:self-center" />
      <span className="font-medium">{item?.label ?? "Tollgate"}</span>
      <div className="ml-auto flex items-center gap-1">
        <CommandMenu />
        <ThemeToggle />
        <div className="ml-1 flex size-7 items-center justify-center">
          <UserButton />
        </div>
      </div>
    </header>
  );
}
