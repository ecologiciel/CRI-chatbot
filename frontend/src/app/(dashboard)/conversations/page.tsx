"use client";

import { useState } from "react";
import { ArrowLeft, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConversationList } from "./components/conversation-list";
import { ConversationDetail } from "./components/conversation-detail";

export default function ConversationsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      {/* Page header — visible on mobile when list is shown */}
      <div className="md:hidden">
        {selectedId ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedId(null)}
            className="gap-2"
          >
            <ArrowLeft className="h-4 w-4 rtl:rotate-180" strokeWidth={1.75} />
            Retour aux conversations
          </Button>
        ) : (
          <div>
            <h1 className="text-2xl font-bold font-heading text-foreground">
              Conversations
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Supervision des conversations WhatsApp
            </p>
          </div>
        )}
      </div>

      {/* Desktop header */}
      <div className="hidden md:block">
        <h1 className="text-2xl font-bold font-heading text-foreground">
          Conversations
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Supervision des conversations WhatsApp
        </p>
      </div>

      {/* Master-detail layout */}
      <div className="rounded-lg border bg-card shadow-card overflow-hidden h-[calc(100vh-220px)] min-h-[500px]">
        {/* Desktop: side-by-side */}
        <div className="hidden md:flex h-full">
          <div className="w-[350px] shrink-0">
            <ConversationList
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>
          <div className="flex-1">
            {selectedId ? (
              <ConversationDetail conversationId={selectedId} />
            ) : (
              <EmptyState />
            )}
          </div>
        </div>

        {/* Mobile: list OR detail */}
        <div className="md:hidden h-full">
          {selectedId ? (
            <ConversationDetail conversationId={selectedId} />
          ) : (
            <ConversationList
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-3">
      <MessageSquare className="h-12 w-12 opacity-30" strokeWidth={1.5} />
      <p className="text-sm">Sélectionnez une conversation</p>
    </div>
  );
}
