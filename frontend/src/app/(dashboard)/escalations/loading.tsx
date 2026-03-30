import { Card, CardContent } from "@/components/ui/card";

export default function EscalationsLoading() {
  return (
    <div className="space-y-4">
      {/* Header skeleton */}
      <div className="space-y-2">
        <div className="h-7 w-36 bg-muted animate-pulse rounded" />
        <div className="h-4 w-72 bg-muted animate-pulse rounded" />
      </div>

      {/* Stats bar skeleton */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="p-3">
              <div className="flex items-center gap-3">
                <div className="h-9 w-9 rounded-lg bg-muted animate-pulse" />
                <div className="space-y-1.5">
                  <div className="h-3 w-16 bg-muted animate-pulse rounded" />
                  <div className="h-5 w-10 bg-muted animate-pulse rounded" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Master-detail skeleton */}
      <div className="rounded-lg border bg-card shadow-card overflow-hidden h-[calc(100vh-280px)] min-h-[500px]">
        <div className="hidden md:flex h-full">
          {/* List skeleton */}
          <div className="w-[400px] shrink-0 border-e border-border">
            <div className="flex gap-1 px-3 pt-3 pb-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="h-8 w-20 bg-muted animate-pulse rounded"
                />
              ))}
            </div>
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="px-4 py-3 border-b border-border">
                <div className="flex items-start gap-3">
                  <div className="h-2.5 w-2.5 rounded-full bg-muted animate-pulse mt-1.5" />
                  <div className="flex-1 space-y-2">
                    <div className="flex justify-between">
                      <div className="h-4 w-24 bg-muted animate-pulse rounded" />
                      <div className="h-3 w-10 bg-muted animate-pulse rounded" />
                    </div>
                    <div className="h-3 w-full bg-muted animate-pulse rounded" />
                    <div className="flex gap-1.5">
                      <div className="h-5 w-16 bg-muted animate-pulse rounded-full" />
                      <div className="h-5 w-20 bg-muted animate-pulse rounded-full" />
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Detail skeleton */}
          <div className="flex-1 p-4 space-y-4">
            <div className="flex justify-between">
              <div className="space-y-2">
                <div className="h-5 w-32 bg-muted animate-pulse rounded" />
                <div className="h-3 w-24 bg-muted animate-pulse rounded" />
              </div>
              <div className="h-9 w-36 bg-muted animate-pulse rounded" />
            </div>
            <div className="h-16 w-full bg-muted/50 animate-pulse rounded-lg" />
            <div className="space-y-3 flex-1">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className={`h-16 w-3/4 bg-muted animate-pulse rounded-lg ${i % 2 === 0 ? "ms-auto" : ""}`}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Mobile skeleton */}
        <div className="md:hidden p-4 space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-20 bg-muted animate-pulse rounded-lg"
            />
          ))}
        </div>
      </div>
    </div>
  );
}
