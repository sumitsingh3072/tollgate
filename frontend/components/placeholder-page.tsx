import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function PlaceholderPage({ title, phase }: { title: string; phase: number }) {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <Card>
        <CardHeader>
          <CardTitle>Coming in Phase {phase}</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">See docs/phase.md.</CardContent>
      </Card>
    </div>
  );
}
