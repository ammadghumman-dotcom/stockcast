import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const health = await fetchHealth();
  const ok = health?.status === "ok";

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-6 p-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Stockcast</h1>
        <p className="text-muted-foreground">
          AI demand forecasting and raw-material planning for ecommerce brands.
        </p>
      </div>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>API health</CardTitle>
          <Badge variant={ok ? "success" : "destructive"} data-testid="health-badge">
            {ok ? "Online" : "Offline"}
          </Badge>
        </CardHeader>
        <CardContent className="text-sm">
          {health ? (
            <dl className="grid grid-cols-2 gap-y-1">
              <dt className="text-muted-foreground">Service</dt>
              <dd>{health.service}</dd>
              <dt className="text-muted-foreground">Version</dt>
              <dd>{health.version}</dd>
              <dt className="text-muted-foreground">Environment</dt>
              <dd>{health.env}</dd>
              <dt className="text-muted-foreground">Server time</dt>
              <dd>{new Date(health.time).toLocaleString()}</dd>
            </dl>
          ) : (
            <p className="text-muted-foreground">
              Could not reach the API. Is it running? Try <code>make dev</code>.
            </p>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
