import { ArrowRightIcon } from "lucide-react";

const STEPS = [
  { name: "Auth", detail: "key lookup in Redis" },
  { name: "Limits", detail: "RPM + daily tokens" },
  { name: "Cache", detail: "hit? answer in ms", accent: true },
  { name: "Coalesce", detail: "same request in flight? share it", accent: true },
  { name: "Fair queue", detail: "VTC picks who goes next", accent: true },
  { name: "Model", detail: "with fallback chain" },
];

/** The request pipeline as a row of steps (wraps on small screens). */
export function Pipeline() {
  return (
    <ol className="flex flex-wrap items-stretch gap-2" aria-label="Request pipeline">
      {STEPS.map((step, i) => (
        <li key={step.name} className="flex items-center gap-2">
          <div
            className={
              step.accent
                ? "rounded-lg border border-primary/40 bg-primary/5 px-3 py-2"
                : "rounded-lg border bg-card px-3 py-2"
            }
          >
            <div className="text-sm font-medium">{step.name}</div>
            <div className="text-xs text-muted-foreground">{step.detail}</div>
          </div>
          {i < STEPS.length - 1 && <ArrowRightIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
        </li>
      ))}
    </ol>
  );
}
