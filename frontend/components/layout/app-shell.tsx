import { AppHeader } from "@/components/app-header";
import { AppSidebar } from "@/components/layout/app-sidebar";

// Shared by every top-level route's own layout.tsx (app/repos/layout.tsx,
// app/settings/layout.tsx) rather than living in the root layout -- "/"
// (app/page.tsx) is just a brief pre-redirect fallback and doesn't need
// the full app chrome around it.
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen">
      <AppSidebar />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <AppHeader />
        <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">{children}</div>
      </div>
    </div>
  );
}
