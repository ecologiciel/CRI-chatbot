"use client";

import { cn } from "@/lib/utils";

interface WhatsAppPreviewProps {
  body: string;
  variables?: Record<string, string>;
  headerText?: string;
  footerText?: string;
  buttons?: string[];
  className?: string;
}

/**
 * Replaces {{1}}, {{2}} etc. with mapped values or highlights them.
 */
function renderBody(body: string, variables?: Record<string, string>) {
  const parts = body.split(/(\{\{\d+\}\})/g);
  return parts.map((part, i) => {
    const match = part.match(/^\{\{(\d+)\}\}$/);
    if (!match) return part;
    const key = match[1];
    const resolved = variables?.[key];
    if (resolved) {
      return (
        <span key={i} className="font-semibold text-primary">
          {resolved}
        </span>
      );
    }
    return (
      <span
        key={i}
        className="rounded bg-yellow-100 px-0.5 font-mono text-xs"
      >
        {part}
      </span>
    );
  });
}

export function WhatsAppPreview({
  body,
  variables,
  headerText,
  footerText,
  buttons,
  className,
}: WhatsAppPreviewProps) {
  return (
    <div className={cn("max-w-[320px]", className)}>
      {/* Phone mockup frame */}
      <div className="rounded-2xl border-2 border-gray-800 bg-gray-800 p-1">
        {/* Top bar */}
        <div className="flex items-center gap-2 rounded-t-xl bg-[#075E54] px-3 py-2">
          <div className="h-6 w-6 rounded-full bg-gray-300" />
          <span className="text-xs font-medium text-white">
            CRI Rabat-Salé-Kénitra
          </span>
        </div>

        {/* Chat area */}
        <div
          className="min-h-[180px] px-3 py-4"
          style={{ backgroundColor: "#E5DDD5" }}
        >
          {/* Message bubble */}
          <div className="relative ms-auto max-w-[85%]">
            <div
              className="rounded-lg rounded-tr-none px-3 py-2 shadow-sm"
              style={{ backgroundColor: "#DCF8C6" }}
            >
              {headerText && (
                <p className="mb-1 text-sm font-bold text-gray-900">
                  {headerText}
                </p>
              )}
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-900">
                {renderBody(body, variables)}
              </p>
              {footerText && (
                <p className="mt-1 text-xs text-gray-500">{footerText}</p>
              )}
              {/* Timestamp */}
              <span className="mt-0.5 flex justify-end text-[10px] text-gray-500">
                10:30
              </span>
            </div>
            {/* Bubble tail */}
            <div
              className="absolute -end-1.5 top-0 h-3 w-3"
              style={{
                backgroundColor: "#DCF8C6",
                clipPath: "polygon(0 0, 100% 0, 0 100%)",
              }}
            />
          </div>

          {/* Quick-reply buttons */}
          {buttons && buttons.length > 0 && (
            <div className="ms-auto mt-2 flex max-w-[85%] flex-col gap-1">
              {buttons.map((btn) => (
                <div
                  key={btn}
                  className="rounded-lg bg-white px-3 py-1.5 text-center text-sm font-medium text-[#00A5F4] shadow-sm"
                >
                  {btn}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
