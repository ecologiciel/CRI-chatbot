export default function UsersLoading() {
  return (
    <div className="space-y-6">
      {/* Header skeleton */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-8 w-56 bg-muted animate-pulse rounded" />
          <div className="h-4 w-80 bg-muted animate-pulse rounded" />
        </div>
        <div className="h-10 w-40 bg-muted animate-pulse rounded" />
      </div>

      {/* Tabs skeleton */}
      <div className="h-10 w-64 bg-muted animate-pulse rounded" />

      {/* Filter bar skeleton */}
      <div className="flex gap-3">
        <div className="h-10 flex-1 bg-muted animate-pulse rounded" />
        <div className="h-10 w-36 bg-muted animate-pulse rounded" />
      </div>

      {/* Table skeleton */}
      <div className="rounded-lg border bg-card p-1 space-y-0">
        {/* Header row */}
        <div className="flex gap-4 px-4 py-3 border-b">
          <div className="h-4 w-40 bg-muted animate-pulse rounded" />
          <div className="h-4 w-24 bg-muted animate-pulse rounded hidden sm:block" />
          <div className="h-4 w-16 bg-muted animate-pulse rounded hidden md:block" />
          <div className="h-4 w-32 bg-muted animate-pulse rounded hidden lg:block" />
        </div>
        {/* Body rows */}
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex gap-4 px-4 py-4 border-b last:border-0">
            <div className="space-y-1.5 flex-1">
              <div className="h-4 w-32 bg-muted animate-pulse rounded" />
              <div className="h-3 w-44 bg-muted animate-pulse rounded" />
            </div>
            <div className="h-5 w-20 bg-muted animate-pulse rounded hidden sm:block self-center" />
            <div className="h-5 w-12 bg-muted animate-pulse rounded hidden md:block self-center" />
            <div className="h-4 w-24 bg-muted animate-pulse rounded hidden lg:block self-center" />
            <div className="h-8 w-8 bg-muted animate-pulse rounded self-center" />
          </div>
        ))}
      </div>
    </div>
  );
}
