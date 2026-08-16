import Link from "next/link";

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-4 text-center">
      <h1 className="text-4xl font-semibold tracking-tight">Repo Analyzer</h1>
      <p className="max-w-md text-muted-foreground">
        Analyze a GitHub repository, browse its code, and chat with an AI that
        cites the exact files and lines it&apos;s talking about.
      </p>
      <Link
        href="/repos"
        className="rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        Get started
      </Link>
    </main>
  );
}
