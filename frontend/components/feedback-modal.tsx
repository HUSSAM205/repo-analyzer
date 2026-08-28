"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Loader2, MessageCircleQuestion, Star, X } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/utils";

type FeedbackType = "bug" | "feature" | "rating";
type Status = "idle" | "submitting" | "success" | "error";

const TYPES: { key: FeedbackType; label: string }[] = [
  { key: "bug", label: "Bug report" },
  { key: "feature", label: "Feature request" },
  { key: "rating", label: "Rating" },
];

export function FeedbackModal({ onClose }: { onClose: () => void }) {
  const [type, setType] = useState<FeedbackType>("bug");
  const [message, setMessage] = useState("");
  const [rating, setRating] = useState(0);
  const [contactEmail, setContactEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);

  const canSubmit = (type === "rating" ? rating > 0 : message.trim().length > 0) && status !== "submitting";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setStatus("submitting");
    setError(null);

    try {
      const res = await apiFetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type,
          message: message.trim(),
          rating: type === "rating" ? rating : null,
          contact_email: contactEmail.trim() || null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: undefined }));
        setError(body.detail ?? "Could not submit feedback.");
        setStatus("error");
        return;
      }
      setStatus("success");
    } catch {
      setError("Could not reach the server.");
      setStatus("error");
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-label="Feedback"
          initial={{ opacity: 0, scale: 0.96, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 8 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          onClick={(e) => e.stopPropagation()}
          className="glass w-full max-w-md overflow-hidden rounded-2xl border border-border shadow-2xl"
        >
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <MessageCircleQuestion className="h-4 w-4 text-primary" aria-hidden="true" />
              Feedback
            </span>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {status === "success" ? (
            <div className="flex flex-col items-center gap-3 p-8 text-center">
              <CheckCircle2 className="h-8 w-8 text-emerald-400" aria-hidden="true" />
              <p className="text-sm font-medium text-foreground">Thanks for the feedback!</p>
              <button
                type="button"
                onClick={onClose}
                className="glass rounded-full px-4 py-2 text-xs font-medium text-foreground"
              >
                Close
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4 p-4">
              <div role="tablist" aria-label="Feedback type" className="flex gap-1 rounded-full border border-zinc-800/60 p-1">
                {TYPES.map((t) => (
                  <button
                    key={t.key}
                    type="button"
                    role="tab"
                    aria-selected={type === t.key}
                    onClick={() => setType(t.key)}
                    className={cn(
                      "flex-1 rounded-full px-2 py-1.5 text-xs font-medium transition-colors",
                      type === t.key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              {type === "rating" && (
                <div className="flex items-center justify-center gap-1" role="radiogroup" aria-label="Rating">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      type="button"
                      role="radio"
                      aria-checked={rating === n}
                      aria-label={`${n} star${n === 1 ? "" : "s"}`}
                      onClick={() => setRating(n)}
                      className="p-0.5"
                    >
                      <Star
                        className={cn("h-6 w-6 transition-colors", rating >= n ? "fill-primary text-primary" : "text-zinc-600")}
                      />
                    </button>
                  ))}
                </div>
              )}

              <div>
                <label htmlFor="feedback-message" className="mb-1 block text-xs font-medium text-muted-foreground">
                  {type === "bug" ? "What went wrong?" : type === "feature" ? "What would you like to see?" : "Tell us more (optional)"}
                </label>
                <textarea
                  id="feedback-message"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  rows={4}
                  maxLength={4000}
                  required={type !== "rating"}
                  className="glass w-full resize-none rounded-md border border-zinc-800/60 px-3 py-2 text-sm text-foreground"
                  placeholder={type === "rating" ? "Anything you'd like to add..." : "Describe it here..."}
                />
              </div>

              <div>
                <label htmlFor="feedback-email" className="mb-1 block text-xs font-medium text-muted-foreground">
                  Contact email (optional)
                </label>
                <input
                  id="feedback-email"
                  type="email"
                  value={contactEmail}
                  onChange={(e) => setContactEmail(e.target.value)}
                  className="glass w-full rounded-md border border-zinc-800/60 px-3 py-2 text-sm text-foreground"
                  placeholder="you@example.com"
                />
              </div>

              {error && <p className="text-xs text-destructive">{error}</p>}

              <button
                type="submit"
                disabled={!canSubmit}
                className="glow-pill glass flex w-full items-center justify-center gap-2 rounded-full px-4 py-2 text-xs font-medium text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                {status === "submitting" && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                Send feedback
              </button>
            </form>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
