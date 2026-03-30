"use client";

import { useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { BarChart3 } from "lucide-react";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { PeriodSelector } from "@/components/analytics/period-selector";
import { ExportButtons } from "@/components/analytics/export-buttons";
import { KPICards } from "@/components/analytics/kpi-cards";
import { ConversationsChart } from "@/components/analytics/conversations-chart";
import { LanguagesChart } from "@/components/analytics/languages-chart";
import { QuestionsDonut } from "@/components/analytics/questions-donut";
import { TopQuestionsTable } from "@/components/analytics/top-questions-table";
import {
  useAnalyticsOverview,
  useAnalyticsTimeSeries,
  useAnalyticsLanguages,
  useAnalyticsQuestionTypes,
} from "@/hooks/use-analytics";
import type { AnalyticsPeriod } from "@/types/analytics";

function PlaceholderTab({ label }: { label: string }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center py-16">
        <BarChart3
          className="h-12 w-12 text-muted-foreground/40 mb-4"
          strokeWidth={1.5}
        />
        <h2 className="text-lg font-heading font-semibold text-muted-foreground">
          {label}
        </h2>
        <p className="text-sm text-muted-foreground/70 mt-1">
          Bientôt disponible
        </p>
      </CardContent>
    </Card>
  );
}

function AnalyticsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const period = (searchParams.get("period") ?? "30d") as AnalyticsPeriod;
  const start = searchParams.get("start") ?? undefined;
  const end = searchParams.get("end") ?? undefined;

  const handlePeriodChange = useCallback(
    (newPeriod: AnalyticsPeriod) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("period", newPeriod);
      if (newPeriod !== "custom") {
        params.delete("start");
        params.delete("end");
      }
      router.replace(`/analytics?${params.toString()}`);
    },
    [router, searchParams],
  );

  const handleDateRangeChange = useCallback(
    (range: { from: Date; to: Date }) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("period", "custom");
      params.set("start", range.from.toISOString().split("T")[0]);
      params.set("end", range.to.toISOString().split("T")[0]);
      router.replace(`/analytics?${params.toString()}`);
    },
    [router, searchParams],
  );

  // Data hooks
  const { data: overview, isLoading: overviewLoading } =
    useAnalyticsOverview(period, start, end);
  const { data: timeseries, isLoading: timeseriesLoading } =
    useAnalyticsTimeSeries(period, start, end);
  const { data: languages, isLoading: languagesLoading } =
    useAnalyticsLanguages(period, start, end);
  const { data: questionTypes, isLoading: questionTypesLoading } =
    useAnalyticsQuestionTypes(period, start, end);

  const dateRange =
    start && end ? { from: new Date(start), to: new Date(end) } : undefined;

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold font-heading">Analytics</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Vue d&apos;ensemble des performances
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <PeriodSelector
            period={period}
            onPeriodChange={handlePeriodChange}
            dateRange={dateRange}
            onDateRangeChange={handleDateRangeChange}
          />
          <ExportButtons period={period} start={start} end={end} />
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Vue d&apos;ensemble</TabsTrigger>
          <TabsTrigger value="conversations">Conversations</TabsTrigger>
          <TabsTrigger value="kb">Base de connaissances</TabsTrigger>
          <TabsTrigger value="whatsapp">WhatsApp</TabsTrigger>
          <TabsTrigger value="dossiers">Dossiers</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6 mt-6">
          <KPICards data={overview} isLoading={overviewLoading} />
          <ConversationsChart
            data={timeseries}
            isLoading={timeseriesLoading}
          />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <LanguagesChart data={languages} isLoading={languagesLoading} />
            <QuestionsDonut
              data={questionTypes}
              isLoading={questionTypesLoading}
            />
          </div>
          <TopQuestionsTable period={period} start={start} end={end} />
        </TabsContent>

        <TabsContent value="conversations">
          <PlaceholderTab label="Détails des conversations" />
        </TabsContent>
        <TabsContent value="kb">
          <PlaceholderTab label="Analytics Base de connaissances" />
        </TabsContent>
        <TabsContent value="whatsapp">
          <PlaceholderTab label="Statistiques WhatsApp" />
        </TabsContent>
        <TabsContent value="dossiers">
          <PlaceholderTab label="Suivi des dossiers" />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function AnalyticsPage() {
  return (
    <Suspense>
      <AnalyticsContent />
    </Suspense>
  );
}
