/** Persist only an opaque idempotency key, never the message itself. */
export function replyStorageName(tenant: string, actor: string, escalation: string): string {
  return `agent-reply:v1:${tenant}:${actor}:${escalation}`;
}

async function locked<T>(name: string, callback: () => T): Promise<T> {
  if (!navigator.locks || !window.isSecureContext || !crypto.randomUUID) {
    throw new Error("secure browser locking unavailable");
  }
  return navigator.locks.request(name, { mode: "exclusive" }, callback);
}

export function readReplyKey(name: string): Promise<string | null> {
  return locked(name, () => localStorage.getItem(name));
}

export function acquireReplyKey(name: string): Promise<string> {
  return locked(name, () => {
    const existing = localStorage.getItem(name);
    if (existing) return existing;
    const created = crypto.randomUUID();
    localStorage.setItem(name, created);
    if (localStorage.getItem(name) !== created) throw new Error("storage unavailable");
    return created;
  });
}

export function releaseReplyKey(name: string, key: string): Promise<string | null> {
  return locked(name, () => {
    if (localStorage.getItem(name) === key) localStorage.removeItem(name);
    return localStorage.getItem(name);
  });
}
