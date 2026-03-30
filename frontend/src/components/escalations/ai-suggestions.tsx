"use client";

import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

// Mock suggestions — replace with API call when backend endpoint is ready
const MOCK_SUGGESTIONS = [
  "Bonjour, je prends en charge votre demande. Pouvez-vous me préciser votre numéro de dossier ?",
  "Je comprends votre préoccupation. Permettez-moi de vérifier l'état de votre demande.",
  "Merci pour votre patience. Je vais vous aider à résoudre ce problème rapidement.",
];

interface AiSuggestionsProps {
  escalationId: string;
  onSelect: (text: string) => void;
}

export function AiSuggestions({ onSelect }: AiSuggestionsProps) {
  return (
    <div className="flex gap-2 overflow-x-auto px-4 pb-2 scrollbar-thin">
      {MOCK_SUGGESTIONS.map((suggestion, i) => (
        <Button
          key={i}
          variant="outline"
          size="sm"
          className="shrink-0 gap-1.5 text-xs max-w-[280px] h-auto py-1.5 px-2.5 whitespace-normal text-start bg-secondary/10 border-secondary/20 hover:bg-secondary/20"
          onClick={() => onSelect(suggestion)}
        >
          <Sparkles className="h-3 w-3 shrink-0 text-secondary" strokeWidth={2} />
          <span className="line-clamp-2">{suggestion}</span>
        </Button>
      ))}
    </div>
  );
}
