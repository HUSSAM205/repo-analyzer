import Link from "next/link";
import { FileQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background px-6 text-center">
      <FileQuestion className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-2xl font-semibold text-zinc-100">Page not found</h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        The repository or page you&apos;re looking for doesn&apos;t exist, or may have been removed.
      </p>
      <Button asChild className="mt-2">
        <Link href="/repos">Back to your repositories</Link>
      </Button>
    </main>
  );
}
