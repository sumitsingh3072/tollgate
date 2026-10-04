import { admin } from "@/lib/server/gateway";
import type { AliasInfo } from "@/lib/types";

import { Playground } from "./_components/playground";

export default async function PlaygroundPage() {
  const aliases = await admin<AliasInfo[]>("/aliases");
  return <Playground aliases={aliases} />;
}
