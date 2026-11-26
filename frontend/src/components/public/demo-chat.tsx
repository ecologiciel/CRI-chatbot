"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

type Source = { title?: string | null; url?: string | null; published_at?: string | null; section_path?: string[]; page_numbers?: number[]; language?: string | null };
type ChatMessage = { role: "user" | "assistant"; content: string; sources?: Source[] };

const INTRO: ChatMessage = {
  role: "assistant",
  content: "Bonjour. Je suis un assistant documentaire de démonstration. Posez-moi une question sur les informations disponibles dans la base de connaissances.",
};

export function DemoChat({ tenantSlug }: { tenantSlug: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([INTRO]);
  const [input, setInput] = useState("");
  const [ready, setReady] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [institution, setInstitution] = useState<string | null>(null);
  const started = useRef(false);

  const startSession = useCallback(() => {
    if (started.current) return;
    started.current = true;
    fetch(`/api/v1/public/${tenantSlug}/session`, { method: "POST", credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Impossible de démarrer la démonstration.");
        const body = await response.json() as { tenant_name?: string };
        setInstitution(body.tenant_name || null);
        setReady(true);
      })
      .catch(() => setError("Impossible de démarrer la démonstration. Veuillez réessayer."))
      .finally(() => { started.current = false; });
  }, [tenantSlug]);

  useEffect(() => {
    startSession();
  }, [startSession]);

  async function send(event: FormEvent) {
    event.preventDefault();
    const message = input.trim();
    if (!message || !ready || sending) return;

    setInput("");
    setError(null);
    setMessages((current) => [...current, { role: "user", content: message }]);
    setSending(true);
    try {
      const response = await fetch(`/api/v1/public/${tenantSlug}/messages`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "La réponse n’a pas pu être générée.");
      }
      const body = await response.json() as { answer: string; sources?: Source[] };
      setMessages((current) => [...current, { role: "assistant", content: body.answer, sources: body.sources }]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Une erreur est survenue.");
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 text-slate-900 sm:px-6">
      <section className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl shadow-slate-200/50">
        <header className="border-b border-slate-200 bg-emerald-800 px-6 py-5 text-white">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-100">Démonstration non officielle</p>
          <h1 className="mt-1 text-2xl font-semibold">Assistant documentaire{institution ? ` — ${institution}` : ""}</h1>
          <p className="mt-2 text-sm text-emerald-100">Réponses fondées sur les sources validées de la base de connaissances.</p>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto bg-slate-50 p-5" aria-live="polite">
          {messages.map((message, index) => (
            <article key={`${message.role}-${index}`} className={message.role === "user" ? "ml-auto max-w-[85%]" : "max-w-[90%]"}>
              <div className={message.role === "user" ? "rounded-2xl rounded-br-md bg-emerald-700 px-4 py-3 text-white" : "rounded-2xl rounded-bl-md border border-slate-200 bg-white px-4 py-3 shadow-sm"}>
                <p className="whitespace-pre-wrap text-sm leading-6">{message.content}</p>
              </div>
              {message.sources && message.sources.length > 0 && (
                <div className="mt-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                  <p className="font-semibold text-slate-700">Documents consultés</p>
                  <ul className="mt-1 space-y-1">
                    {message.sources.map((source, sourceIndex) => (
                      <li key={`${source.url ?? source.title}-${sourceIndex}`}>
                        {source.url ? <a className="text-emerald-700 underline" href={source.url} target="_blank" rel="noreferrer">{source.title ?? "Source officielle"}</a> : source.title ?? "Source officielle"}
                        {source.published_at ? ` — ${source.published_at}` : ""}
                        {source.section_path?.length ? ` — ${source.section_path.join(" › ")}` : ""}
                        {source.page_numbers?.length ? ` — pages consultées : ${source.page_numbers.join(", ")}` : ""}
                        {source.language ? ` — ${source.language.toUpperCase()}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </article>
          ))}
          {sending && <p className="text-sm text-slate-500">L’assistant prépare sa réponse…</p>}
        </div>

        <footer className="border-t border-slate-200 bg-white p-4">
          {error && <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          {error && !ready && (
            <button type="button" className="mb-3 rounded-lg border border-emerald-700 px-4 py-2 text-sm font-semibold text-emerald-700" onClick={() => { setError(null); startSession(); }}>
              Réessayer de démarrer
            </button>
          )}
          <form onSubmit={send} className="flex gap-2">
            <label className="sr-only" htmlFor="question">Votre question</label>
            <input id="question" value={input} onChange={(event) => setInput(event.target.value)} disabled={!ready || sending} maxLength={2000} placeholder={ready ? "Posez votre question…" : "Initialisation…"} className="min-w-0 flex-1 rounded-xl border border-slate-300 px-4 py-3 text-sm outline-none ring-emerald-600 focus:ring-2 disabled:bg-slate-100" />
            <button type="submit" disabled={!ready || sending || !input.trim()} className="rounded-xl bg-emerald-700 px-5 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:bg-slate-400">Envoyer</button>
          </form>
          <p className="mt-3 text-xs leading-5 text-slate-500">N’envoyez aucune donnée personnelle ou confidentielle. Vérifiez les informations importantes auprès des canaux officiels.</p>
        </footer>
      </section>
    </main>
  );
}
