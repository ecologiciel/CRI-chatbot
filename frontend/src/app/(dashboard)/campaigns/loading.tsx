import { Card, CardContent } from "@/components/ui/card";

export default function CampaignsLoading() {
  return (
    <div className="space-y-6">
      {/* Header skeleton */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-7 w-40 bg-muted animate-pulse rounded" />
          <div className="h-4 w-64 bg-muted animate-pulse rounded" />
        </div>
        <div className="h-9 w-44 bg-muted animate-pulse rounded" />
      </div>

      {/* Filter skeleton */}
      <div className="flex gap-3">
        <div className="h-9 flex-1 bg-muted animate-pulse rounded" />
        <div className="h-9 w-[180px] bg-muted animate-pulse rounded" />
      </div>

      {/* Table skeleton */}
      <Card>
        <CardContent className="p-0">
          <div className="space-y-0 divide-y">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 p-4">
                <div className="h-4 w-40 bg-muted animate-pulse rounded" />
                <div className="h-4 w-24 bg-muted animate-pulse rounded hidden sm:block" />
                <div className="h-4 w-16 bg-muted animate-pulse rounded hidden md:block" />
                <div className="h-5 w-20 bg-muted animate-pulse rounded-full" />
                <div className="ms-auto h-4 w-12 bg-muted animate-pulse rounded" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
