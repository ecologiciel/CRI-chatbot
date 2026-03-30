import { Card, CardContent, CardHeader } from "@/components/ui/card";

export default function AnalyticsLoading() {
  return (
    <div className="space-y-8">
      {/* Page header skeleton */}
      <div className="flex items-center justify-between">
        <div className="h-8 w-32 bg-muted animate-pulse rounded" />
        <div className="flex items-center gap-3">
          <div className="h-9 w-[160px] bg-muted animate-pulse rounded" />
          <div className="h-9 w-20 bg-muted animate-pulse rounded" />
          <div className="h-9 w-20 bg-muted animate-pulse rounded" />
        </div>
      </div>

      {/* Tabs skeleton */}
      <div className="h-10 w-[500px] bg-muted animate-pulse rounded" />

      {/* KPI cards skeleton */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="p-6">
              <div className="flex items-center gap-3 mb-3">
                <div className="rounded-lg p-2 bg-muted animate-pulse h-9 w-9" />
                <div className="h-4 w-24 bg-muted animate-pulse rounded" />
              </div>
              <div className="h-8 w-20 bg-muted animate-pulse rounded mb-2" />
              <div className="h-3 w-16 bg-muted animate-pulse rounded" />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Line chart skeleton */}
      <Card>
        <CardHeader>
          <div className="h-5 w-48 bg-muted animate-pulse rounded" />
        </CardHeader>
        <CardContent>
          <div className="h-[300px] bg-muted/50 animate-pulse rounded-lg" />
        </CardContent>
      </Card>

      {/* Two-column chart skeletons */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <div className="h-5 w-40 bg-muted animate-pulse rounded" />
          </CardHeader>
          <CardContent>
            <div className="h-[250px] bg-muted/50 animate-pulse rounded-lg" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <div className="h-5 w-44 bg-muted animate-pulse rounded" />
          </CardHeader>
          <CardContent>
            <div className="h-[250px] bg-muted/50 animate-pulse rounded-lg" />
          </CardContent>
        </Card>
      </div>

      {/* Table skeleton */}
      <Card>
        <CardHeader>
          <div className="h-5 w-56 bg-muted animate-pulse rounded" />
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="h-10 bg-muted/50 animate-pulse rounded" />
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="h-12 bg-muted/30 animate-pulse rounded"
              />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
