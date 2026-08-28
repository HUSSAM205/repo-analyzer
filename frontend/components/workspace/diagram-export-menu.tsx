"use client";

import { copyText, downloadSvgAsPng, downloadTextFile } from "@/lib/export-utils";
import { ExportMenu } from "./export-menu";

// Shared by ModuleMapViewer and FlowMapViewer -- both render a Mermaid
// diagram from a raw `diagram` source string into an `svg` string, and
// offer the same three export shapes on that same pair of values.
export function DiagramExportMenu({ diagram, svg, filenamePrefix }: { diagram: string; svg: string; filenamePrefix: string }) {
  return (
    <ExportMenu
      options={[
        { label: "Download SVG", onSelect: () => downloadTextFile(svg, `${filenamePrefix}.svg`, "image/svg+xml") },
        { label: "Download PNG", onSelect: () => downloadSvgAsPng(svg, `${filenamePrefix}.png`) },
        { label: "Copy Mermaid source", onSelect: () => copyText(diagram) },
      ]}
    />
  );
}
