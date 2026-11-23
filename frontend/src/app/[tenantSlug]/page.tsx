import { notFound } from "next/navigation";

import { DemoChat } from "@/components/public/demo-chat";

export default async function PublicDemoPage({ params }: { params: Promise<{ tenantSlug: string }> }) {
  const { tenantSlug } = await params;
  if (!/^[a-z][a-z0-9-]{1,49}$/.test(tenantSlug) || ["admin", "api", "login", "dashboard", "sa"].includes(tenantSlug)) {
    notFound();
  }
  return <DemoChat tenantSlug={tenantSlug} />;
}
