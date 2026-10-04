"use client";

import { XIcon } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export type LogFilterValues = { key?: string; alias?: string; status?: "errors" | "429" };
type Option = { value: string; label: string };

const ALL = "__all__";
const STATUS_OPTIONS: Option[] = [
  { value: ALL, label: "Any status" },
  { value: "errors", label: "Errors only" },
  { value: "429", label: "Rate limited (429)" },
];

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string | undefined;
  options: Option[];
  onChange: (value: string | undefined) => void;
}) {
  return (
    <Select
      items={options}
      value={value ?? ALL}
      onValueChange={(next) => onChange(next === ALL || next === null ? undefined : String(next))}
    >
      <SelectTrigger size="sm" aria-label={label} className="min-w-36">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function LogFilters({ values, keys, aliases }: { values: LogFilterValues; keys: Option[]; aliases: string[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();

  function update(next: LogFilterValues) {
    // Any filter change starts again from the newest page (drops the ?before cursor).
    const params = new URLSearchParams();
    for (const [name, value] of Object.entries({ ...values, ...next })) {
      if (value) params.set(name, value);
    }
    const query = params.toString();
    startTransition(() => router.replace(query ? `${pathname}?${query}` : pathname));
  }

  const active = Boolean(values.key || values.alias || values.status);

  return (
    <div className="flex flex-wrap items-center gap-2" data-pending={pending || undefined}>
      <FilterSelect
        label="Key"
        value={values.key}
        options={[{ value: ALL, label: "All keys" }, ...keys]}
        onChange={(key) => update({ key })}
      />
      <FilterSelect
        label="Alias"
        value={values.alias}
        options={[{ value: ALL, label: "All aliases" }, ...aliases.map((a) => ({ value: a, label: a }))]}
        onChange={(alias) => update({ alias })}
      />
      <FilterSelect
        label="Status"
        value={values.status}
        options={STATUS_OPTIONS}
        onChange={(status) => update({ status: status as LogFilterValues["status"] })}
      />
      {active && (
        <Button variant="ghost" size="sm" onClick={() => startTransition(() => router.replace(pathname))}>
          <XIcon />
          Clear
        </Button>
      )}
    </div>
  );
}
