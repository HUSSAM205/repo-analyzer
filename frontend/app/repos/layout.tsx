import { AppShell } from "@/components/layout/app-shell";

export default function ReposLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
