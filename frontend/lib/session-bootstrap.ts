// Shared across every client component that might need a guest session to
// exist before it can call an authenticated API route (RepoListClient's
// mount-time repo-list fetch, SubmitRepoForm's analyze submission) --
// module-level, not component state, so concurrent callers from different
// components in the same tab still only ever trigger ONE
// POST /api/v1/auth/guest, not one per caller. See middleware.ts and
// app/api/auth/bootstrap/route.ts for the rest of this flow.
let bootstrapPromise: Promise<void> | null = null;

export function ensureSessionBootstrapped(): Promise<void> {
  if (!bootstrapPromise) {
    bootstrapPromise = fetch("/api/auth/bootstrap?format=json")
      .then(() => undefined)
      .catch((err) => {
        // Reset on failure so a later caller (not just a full page reload,
        // which would reset this module anyway) can retry instead of a
        // transient failure being cached forever for the rest of this
        // tab's lifetime.
        bootstrapPromise = null;
        throw err;
      });
  }
  return bootstrapPromise;
}
