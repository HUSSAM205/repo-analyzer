"use client";

import { useRef, useState, type HTMLAttributes } from "react";
import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import { cn } from "@/lib/utils";

const TILT_RANGE_DEG = 8;
const SPRING_CONFIG = { stiffness: 300, damping: 30, mass: 0.5 };

/**
 * Wraps children in a perspective transform that tilts toward the cursor on
 * hover -- pure CSS transform (no continuous animation loop), so it's cheap
 * even with many cards on a page. Disabled under prefers-reduced-motion.
 */
// framer-motion's MotionProps types onAnimationStart/onAnimationEnd/onDrag*
// differently than React's native DOM event handlers -- omit them from the
// plain HTML props so TS doesn't see a conflict when both get spread onto
// the same motion.div below (we don't use any of these on TiltCard anyway).
type TiltCardProps = Omit<
  HTMLAttributes<HTMLDivElement>,
  "onAnimationStart" | "onAnimationEnd" | "onDrag" | "onDragStart" | "onDragEnd"
>;

export function TiltCard({ children, className, ...props }: TiltCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [reducedMotion] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );

  const x = useMotionValue(0.5);
  const y = useMotionValue(0.5);
  const rotateX = useSpring(useTransform(y, [0, 1], [TILT_RANGE_DEG, -TILT_RANGE_DEG]), SPRING_CONFIG);
  const rotateY = useSpring(useTransform(x, [0, 1], [-TILT_RANGE_DEG, TILT_RANGE_DEG]), SPRING_CONFIG);

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    if (reducedMotion) return;
    const rect = ref.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return;
    x.set((e.clientX - rect.left) / rect.width);
    y.set((e.clientY - rect.top) / rect.height);
  }

  function handleMouseLeave() {
    x.set(0.5);
    y.set(0.5);
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={reducedMotion ? undefined : { rotateX, rotateY, transformPerspective: 800 }}
      className={cn("will-change-transform", className)}
      {...props}
    >
      {children}
    </motion.div>
  );
}
