"use client";

import { useState } from "react";
import { CalendarDays } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import type { AnalyticsPeriod } from "@/types/analytics";

const PERIOD_OPTIONS: { value: AnalyticsPeriod; label: string }[] = [
  { value: "7d", label: "7 jours" },
  { value: "30d", label: "30 jours" },
  { value: "90d", label: "90 jours" },
  { value: "custom", label: "Personnalisé" },
];

interface PeriodSelectorProps {
  period: AnalyticsPeriod;
  onPeriodChange: (period: AnalyticsPeriod) => void;
  dateRange?: { from: Date; to: Date };
  onDateRangeChange?: (range: { from: Date; to: Date }) => void;
}

export function PeriodSelector({
  period,
  onPeriodChange,
  dateRange,
  onDateRangeChange,
}: PeriodSelectorProps) {
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [selectedRange, setSelectedRange] = useState<{
    from?: Date;
    to?: Date;
  }>({
    from: dateRange?.from,
    to: dateRange?.to,
  });

  function handlePeriodChange(value: string) {
    const p = value as AnalyticsPeriod;
    onPeriodChange(p);
    if (p === "custom") {
      setCalendarOpen(true);
    }
  }

  function handleRangeSelect(range: { from?: Date; to?: Date } | undefined) {
    if (!range) return;
    setSelectedRange(range);
    if (range.from && range.to) {
      onDateRangeChange?.({ from: range.from, to: range.to });
      setCalendarOpen(false);
    }
  }

  const formatDate = (d: Date) =>
    d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });

  return (
    <div className="flex items-center gap-2">
      <Select value={period} onValueChange={handlePeriodChange}>
        <SelectTrigger className="w-[160px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PERIOD_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {period === "custom" && (
        <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" className="gap-2">
              <CalendarDays className="h-4 w-4" />
              {dateRange
                ? `${formatDate(dateRange.from)} – ${formatDate(dateRange.to)}`
                : "Sélectionner"}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="end">
            <Calendar
              mode="range"
              selected={selectedRange as { from: Date; to?: Date }}
              onSelect={handleRangeSelect}
              numberOfMonths={2}
              disabled={{ after: new Date() }}
            />
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}
