import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="mt-16 flex flex-col items-center gap-3 border-t border-border/60 py-8 text-center text-xs">
      <p className="text-zinc-500 transition-colors duration-300 hover:text-indigo-500 dark:text-zinc-600 dark:hover:text-indigo-400">
        RepoLens AI &copy; {new Date().getFullYear()} &bull; Managed and Powered by ES Easy Solutions (Project
        Management &amp; AI Solutions)
      </p>
      <nav className="flex items-center gap-4 text-muted-foreground">
        <Link href="/privacy" className="transition-colors hover:text-foreground">
          Privacy Policy
        </Link>
        <Link href="/terms" className="transition-colors hover:text-foreground">
          Terms of Service
        </Link>
      </nav>
    </footer>
  );
}
