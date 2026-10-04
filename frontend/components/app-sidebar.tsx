"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpenIcon } from "lucide-react";

import { GatewayStatus } from "@/components/gateway-status";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { GATEWAY_URL } from "@/lib/api";
import { findNavItem, NAV_ITEMS } from "@/lib/nav";

const DOCS_URL = `${GATEWAY_URL}/docs`;

export function AppSidebar() {
  const active = findNavItem(usePathname());

  return (
    <Sidebar variant="inset" collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<Link href="/" />} tooltip="Tollgate">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-[13px] font-semibold text-primary-foreground">
                T
              </span>
              <span className="flex flex-col leading-tight">
                <span className="font-semibold text-sidebar-accent-foreground">Tollgate</span>
                <span className="text-xs text-muted-foreground">LLM gateway</span>
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
                <SidebarMenuItem key={href}>
                  <SidebarMenuButton render={<Link href={href} />} isActive={active?.href === href} tooltip={label}>
                    <Icon />
                    <span>{label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              render={<a href={DOCS_URL} target="_blank" rel="noreferrer" />}
              tooltip="API reference"
            >
              <BookOpenIcon />
              <span>API reference</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <GatewayStatus />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
