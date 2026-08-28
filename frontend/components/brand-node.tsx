"use client";

import { TiltCard } from "@/components/tilt-card";

// A small, dependency-free 3D "coin" -- the same diamond+node mark used in
// icon.svg / apple-icon / opengraph-image, spinning on its Y axis via a
// pure-CSS keyframe (animate-spin-3d, see tailwind.config.ts -- no JS
// animation loop, so it's cheap even on low-power devices and automatically
// respects prefers-reduced-motion via motion-reduce:animate-none). TiltCard
// layers a real, mouse-driven tilt on top when the cursor is over it,
// giving the "ambient rotation + responds to the cursor" effect without
// pulling in a 3D/WebGL library.
export function BrandNode() {
  return (
    <div className="flex flex-col items-center gap-3">
      <TiltCard
        className="group relative flex h-16 w-16 items-center justify-center sm:h-20 sm:w-20"
        style={{ perspective: "900px" }}
      >
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 rounded-full bg-primary/20 blur-xl transition-opacity duration-300 group-hover:opacity-80 dark:bg-indigo-500/25"
        />
        <div
          className="relative h-full w-full animate-spin-3d motion-reduce:animate-none [transform-style:preserve-3d]"
        >
          <BrandNodeFace className="[backface-visibility:hidden]" />
          <BrandNodeFace className="[backface-visibility:hidden] [transform:rotateY(180deg)]" />
        </div>
      </TiltCard>
      <p className="select-none text-center font-mono text-[10px] font-medium uppercase tracking-widest text-zinc-900/80 transition-colors duration-300 hover:text-indigo-600 dark:text-zinc-200/80 dark:hover:text-indigo-400 sm:text-xs">
        Managed &amp; Powered by{" "}
        <span className="bg-gradient-to-r from-primary to-indigo-500 bg-clip-text text-transparent">
          ES Easy Solutions
        </span>
      </p>
    </div>
  );
}

function BrandNodeFace({ className }: { className: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      className={`absolute inset-0 h-full w-full drop-shadow-[0_0_8px_rgba(99,102,241,0.35)] ${className}`}
      fill="none"
      aria-hidden="true"
    >
      <rect width="32" height="32" rx="7" className="fill-white/80 dark:fill-zinc-900/80" />
      <path
        d="M16 4 L27 10.5 V21.5 L16 28 L5 21.5 V10.5 Z"
        stroke="currentColor"
        className="text-primary dark:text-indigo-400"
        strokeWidth={1.8}
        strokeLinejoin="round"
      />
      <path
        d="M16 4 V16 M16 16 L27 10.5 M16 16 L5 10.5 M16 16 V28"
        stroke="currentColor"
        className="text-primary dark:text-indigo-400"
        strokeWidth={1.2}
        strokeOpacity={0.5}
      />
      <circle cx="16" cy="16" r="2.6" fill="currentColor" className="text-primary dark:text-indigo-400" />
    </svg>
  );
}
