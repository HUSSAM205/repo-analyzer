import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "How RepoLens AI handles guest sessions, local preferences, and public GitHub repository data.",
};

export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <Link href="/repos" className="text-sm text-muted-foreground transition-colors hover:text-foreground">
        &larr; Back to Workspace
      </Link>
      <h1 className="mb-2 mt-6 text-3xl font-bold tracking-tight text-foreground">Privacy Policy</h1>
      <p className="mb-10 text-sm text-muted-foreground">Last updated August 2026</p>

      <div className="flex flex-col gap-8 text-sm leading-relaxed text-muted-foreground">
        <section>
          <h2 className="mb-2 text-lg font-semibold text-foreground">Guest sessions, not accounts</h2>
          <p>
            RepoLens AI does not require sign-up. Visiting the app mints a cookie-based guest session
            automatically -- there is no password, email, or personal account created, and no separate login
            step. The session cookie exists only to keep your analyzed repositories associated with your browser
            for the duration of your visit.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-lg font-semibold text-foreground">Local preferences</h2>
          <p>
            Interface preferences -- such as your chosen light/dark theme -- are stored in your browser&apos;s
            localStorage. This data never leaves your device and is not transmitted to our servers.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-lg font-semibold text-foreground">Public GitHub repository data</h2>
          <p>
            RepoLens AI only analyzes repositories you explicitly submit, and only public GitHub repositories are
            supported. Analyzing a repository clones its public contents, parses them into an AST and file index,
            and generates the briefing, chat context, and other workbench views you see -- this processing is
            ephemeral and scoped to your session. Repository source code is not used to train any machine learning
            model, and is not sold or shared with third parties beyond the LLM provider calls needed to answer your
            own chat questions in real time.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-lg font-semibold text-foreground">Feedback submissions</h2>
          <p>
            If you submit feedback through the in-app feedback form, the message content and an optional contact
            email you provide are sent to the RepoLens AI team via email for the sole purpose of reviewing and
            responding to that feedback.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-lg font-semibold text-foreground">Contact</h2>
          <p>
            Questions about this policy can be sent through the in-app feedback form, accessible from the
            workspace sidebar.
          </p>
        </section>
      </div>
    </main>
  );
}
