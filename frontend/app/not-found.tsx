import Link from "next/link";
import { FileQuestion } from "lucide-react";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <div className="glass flex flex-col items-center gap-3 rounded-2xl border border-border/60 bg-white/70 px-8 py-10 shadow-xl dark:bg-zinc-900/60">
        <FileQuestion className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-2xl font-semibold text-foreground">404 - Repository or Page Not Found</h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          The repository or page you&apos;re looking for doesn&apos;t exist, or may have been removed. Let&apos;s
          get you back on track.
        </p>
        <Link
          href="/repos"
          className="mt-2 inline-flex items-center gap-1 rounded-md bg-gradient-to-r from-primary to-indigo-500 px-4 py-2 text-sm font-medium text-primary-foreground shadow-md transition-transform hover:scale-[1.02]"
        >
          Back to Workspace &rarr;
        </Link>
      </div>
    </main>
  );
}
