"use client";

import { useEffect, useRef } from "react";
import { useTheme } from "next-themes";

type Particle = { x: number; y: number; vx: number; vy: number };

const PARTICLE_COUNT_DESKTOP = 70;
const PARTICLE_COUNT_MOBILE = 32;
const MOBILE_BREAKPOINT_PX = 640;
const LINK_DISTANCE_PX = 130;
const MOUSE_INFLUENCE_RADIUS_PX = 160;
const MOUSE_FORCE = 0.6;
const MAX_DPR = 2;

/**
 * Lightweight interactive particle constellation, drawn with plain Canvas 2D
 * -- no Three.js/WebGL. O(n^2) link-distance check with n<=70 is a few
 * thousand ops/frame, trivial for 60fps. Pauses entirely when the tab is
 * hidden and renders a single static frame (no rAF loop at all) under
 * prefers-reduced-motion.
 */
export function HeroCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !parent || !ctx) return;

    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const isDark = resolvedTheme !== "light";
    const dotColorRgb = isDark ? "255, 255, 255" : "30, 41, 59";
    const lineColorRgb = isDark ? "96, 165, 250" : "37, 99, 235";

    let width = 0;
    let height = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
    let particles: Particle[] = [];
    const mouse = { x: -9999, y: -9999 };
    let rafId = 0;

    function resize() {
      width = parent!.clientWidth;
      height = parent!.clientHeight;
      canvas!.width = width * dpr;
      canvas!.height = height * dpr;
      canvas!.style.width = `${width}px`;
      canvas!.style.height = `${height}px`;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function initParticles() {
      const count = width < MOBILE_BREAKPOINT_PX ? PARTICLE_COUNT_MOBILE : PARTICLE_COUNT_DESKTOP;
      particles = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25,
      }));
    }

    function drawFrame() {
      ctx!.clearRect(0, 0, width, height);

      for (let i = 0; i < particles.length; i++) {
        const a = particles[i];
        for (let j = i + 1; j < particles.length; j++) {
          const b = particles[j];
          const dist = Math.hypot(a.x - b.x, a.y - b.y);
          if (dist < LINK_DISTANCE_PX) {
            ctx!.strokeStyle = `rgba(${lineColorRgb}, ${0.18 * (1 - dist / LINK_DISTANCE_PX)})`;
            ctx!.lineWidth = 1;
            ctx!.beginPath();
            ctx!.moveTo(a.x, a.y);
            ctx!.lineTo(b.x, b.y);
            ctx!.stroke();
          }
        }
        ctx!.fillStyle = `rgba(${dotColorRgb}, 0.55)`;
        ctx!.beginPath();
        ctx!.arc(a.x, a.y, 1.6, 0, Math.PI * 2);
        ctx!.fill();
      }
    }

    function step() {
      for (const p of particles) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0 || p.x > width) p.vx *= -1;
        if (p.y < 0 || p.y > height) p.vy *= -1;

        const dx = p.x - mouse.x;
        const dy = p.y - mouse.y;
        const dist = Math.hypot(dx, dy);
        if (dist < MOUSE_INFLUENCE_RADIUS_PX) {
          const force = (1 - dist / MOUSE_INFLUENCE_RADIUS_PX) * MOUSE_FORCE;
          p.x += (dx / (dist || 1)) * force;
          p.y += (dy / (dist || 1)) * force;
        }
      }
      drawFrame();
      rafId = requestAnimationFrame(step);
    }

    function handlePointerMove(e: PointerEvent) {
      const rect = canvas!.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
    }
    function handlePointerLeave() {
      mouse.x = -9999;
      mouse.y = -9999;
    }
    function handleResize() {
      resize();
      initParticles();
    }
    function handleVisibility() {
      if (prefersReducedMotion) return;
      if (document.visibilityState === "visible") {
        rafId = requestAnimationFrame(step);
      } else {
        cancelAnimationFrame(rafId);
      }
    }

    resize();
    initParticles();

    parent.addEventListener("pointermove", handlePointerMove);
    parent.addEventListener("pointerleave", handlePointerLeave);
    window.addEventListener("resize", handleResize);
    document.addEventListener("visibilitychange", handleVisibility);

    if (prefersReducedMotion) {
      drawFrame();
    } else {
      rafId = requestAnimationFrame(step);
    }

    return () => {
      cancelAnimationFrame(rafId);
      parent.removeEventListener("pointermove", handlePointerMove);
      parent.removeEventListener("pointerleave", handlePointerLeave);
      window.removeEventListener("resize", handleResize);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [resolvedTheme]);

  return <canvas ref={canvasRef} aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full" />;
}
