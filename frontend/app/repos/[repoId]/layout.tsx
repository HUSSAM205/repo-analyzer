export default function RepoWorkspaceLayout({ children }: { children: React.ReactNode }) {
  // `h-full`, not `h-screen`: this nests inside the parent repos layout's
  // `min-h-0 flex-1` content area (which already accounts for AppHeader's
  // height), so it should fill *that* remaining space, not re-claim the
  // whole viewport on top of it.
  return <div className="flex h-full flex-col">{children}</div>;
}
