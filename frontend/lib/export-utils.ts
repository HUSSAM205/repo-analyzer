"use client";

export function downloadTextFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard access denied by the browser/embedding context -- caller
    // decides how to surface (or not surface) this; not every call site
    // needs a visible error for a non-essential convenience action.
    return false;
  }
}

// Rasterizes an already-rendered Mermaid SVG string to a PNG download.
// Goes through an <img> + <canvas> round-trip (draw the SVG as an image,
// then read the canvas back out as a PNG blob) rather than any SVG-to-PNG
// library -- the browser's own image decoder already understands SVG, so
// this needs no new dependency.
export function downloadSvgAsPng(svgMarkup: string, filename: string, scale = 2): Promise<void> {
  return new Promise((resolve, reject) => {
    // Mermaid's rendered SVG often omits explicit width/height (relying on
    // its viewBox + CSS sizing), which would make an <img> report 0x0 and
    // rasterize to an empty canvas -- fall back to the viewBox dimensions
    // when that happens.
    const widthMatch = svgMarkup.match(/width="([\d.]+)"/);
    const heightMatch = svgMarkup.match(/height="([\d.]+)"/);
    const viewBoxMatch = svgMarkup.match(/viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"/);
    const width = Number(widthMatch?.[1] ?? viewBoxMatch?.[1] ?? 800);
    const height = Number(heightMatch?.[1] ?? viewBoxMatch?.[2] ?? 600);

    const svgBlob = new Blob([svgMarkup], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);
    const img = new Image();

    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = width * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        URL.revokeObjectURL(url);
        reject(new Error("Canvas 2D context unavailable"));
        return;
      }
      // Mermaid's dark-theme SVG has a transparent background -- without
      // filling it first, a PNG (no alpha channel semantics most image
      // viewers respect the same way) would show whatever's behind it,
      // typically white, making dark-theme text unreadable.
      ctx.fillStyle = "#09090b";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);

      canvas.toBlob((blob) => {
        if (!blob) {
          reject(new Error("Failed to rasterize diagram"));
          return;
        }
        const pngUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = pngUrl;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(pngUrl);
        resolve();
      }, "image/png");
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Failed to load diagram for rasterization"));
    };
    img.src = url;
  });
}
