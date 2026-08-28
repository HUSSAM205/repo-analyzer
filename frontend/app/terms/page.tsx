import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "Acceptable use terms for automated repository analysis and AI chat interactions on RepoLens AI.",
};

export default function TermsPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <Link href="/repos" className="text-sm text-muted-foreground transition-colors hover:text-foreground">
        &larr; Back to Workspace
      </Link>
      <h1 className="mb-2 mt-6 text-3xl font-bold tracking-tight text-foreground">Terms of Service</h1>
      <p className="mb-10 text-sm text-muted-foreground">Last updated August 2026</p>

      <div className="flex flex-col gap-8 text-sm leading-relaxed text-muted-foreground">
        <section>
          <h2 className="mb-2 text-lg font-semibold text-foreground">Acceptance of terms</h2>
          <p>
            By using RepoLens AI, you agree to these terms. If you do not agree, please discontinue use of the
            service.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-lg font-semibold text-foreground">Acceptable use</h2>
          <p>
            RepoLens AI is provided for analyzing public GitHub repositories you have the right to inspect. You
            agree not to use the service to: submit repositories for the purpose of overwhelming or abusing
            shared infrastructure; attempt to bypass rate limits or other technical safeguards; or use the AI chat
            feature to generate content that is unlawful, harmful, or infringing.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-lg font-semibold text-foreground">Automated analysis and AI output</h2>
          <p>
            Repository analysis (AST parsing, architecture mapping, complexity metrics) and AI chat responses are
            generated automatically and may contain inaccuracies. RepoLens AI is a research and productivity aid,
            not a substitute for your own review of the underlying code -- do not rely on its output as the sole
            basis for security, legal, or production decisions.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-lg font-semibold text-foreground">Service availability</h2>
          <p>
            RepoLens AI is provided on an &quot;as is&quot; and &quot;as available&quot; basis, with no guarantee
            of uninterrupted availability. Features depending on third-party AI providers may be temporarily
            degraded or unavailable if those providers experience outages or rate limits.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-lg font-semibold text-foreground">Changes to these terms</h2>
          <p>
            These terms may be updated from time to time to reflect changes in the service. Continued use after an
            update constitutes acceptance of the revised terms.
          </p>
        </section>
      </div>
    </main>
  );
}
