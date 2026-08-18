import { AppHeader } from "@/components/app-header";

export default function ReposLayout({ children }: { children: React.ReactNode }) {
  // `flex h-screen flex-col` with AppHeader taking its natural (shrink-0)
  // height and the content area filling the rest via `min-h-0 flex-1`. This
  // way nothing below needs to know AppHeader's exact height in px/rem --
  // the workspace route's own layout/shell just fill whatever's left.
  return (
    <div className="flex h-screen flex-col">
      <AppHeader />
      <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">{children}</div>
    </div>
  );
}
