"use client";

import { useEffect, useRef } from "react";

// Deliberately CSS-only (a radial-gradient positioned via custom properties
// updated on mousemove), not a canvas/WebGL particle system -- this reads
// as an interactive glow mesh at a fraction of the cost, with no risk to
// the "0 lag, 60fps" requirement on lower-end devices. Two independent
// layers: a mouse-following glow (skipped under prefers-reduced-motion,
// where it just sits centered) and a static dot-grid for depth, both
// pointer-events-none so they never intercept clicks on the real content
// stacked above them.
export function HeroGlowBackground() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    function handleMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      el!.style.setProperty("--glow-x", `${x}%`);
      el!.style.setProperty("--glow-y", `${y}%`);
    }

    el.addEventListener("mousemove", handleMove);
    return () => el.removeEventListener("mousemove", handleMove);
  }, []);

  return (
    <div ref={ref} className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <div
        className="absolute inset-0 opacity-40 transition-opacity duration-500 dark:opacity-60"
        style={{
          background:
            "radial-gradient(600px circle at var(--glow-x, 50%) var(--glow-y, 30%), hsl(var(--primary) / 0.18), transparent 70%)",
        }}
      />
      <div
        className="absolute inset-0 opacity-[0.07] dark:opacity-[0.12]"
        style={{
          backgroundImage: "radial-gradient(hsl(var(--foreground) / 0.5) 1px, transparent 1px)",
          backgroundSize: "24px 24px",
        }}
      />
    </div>
  );
}
