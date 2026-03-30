"use client";

import { useState } from "react";
import { Download, FileSpreadsheet, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApiClient } from "@/hooks/use-auth";

interface ExportButtonsProps {
  period: string;
  start?: string;
  end?: string;
}

export function ExportButtons({ period, start, end }: ExportButtonsProps) {
  const api = useApiClient();
  const [loadingPdf, setLoadingPdf] = useState(false);
  const [loadingExcel, setLoadingExcel] = useState(false);

  async function handleExport(format: "pdf" | "excel") {
    const setter = format === "pdf" ? setLoadingPdf : setLoadingExcel;
    setter(true);

    try {
      const blob = await api.download(
        `/dashboard/analytics/export/${format}`,
        { period, start, end },
      );

      const ext = format === "pdf" ? "pdf" : "xlsx";
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `analytics_${period}.${ext}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(a.href);
    } catch (err) {
      console.error("Export error:", err);
    } finally {
      setter(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => handleExport("pdf")}
        disabled={loadingPdf}
      >
        {loadingPdf ? (
          <Loader2 className="h-4 w-4 me-2 animate-spin" />
        ) : (
          <Download className="h-4 w-4 me-2" />
        )}
        PDF
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => handleExport("excel")}
        disabled={loadingExcel}
      >
        {loadingExcel ? (
          <Loader2 className="h-4 w-4 me-2 animate-spin" />
        ) : (
          <FileSpreadsheet className="h-4 w-4 me-2" />
        )}
        Excel
      </Button>
    </div>
  );
}
