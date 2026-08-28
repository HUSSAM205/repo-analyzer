import type { MetadataRoute } from "next";

const SITE_URL = "https://repolens-ai-app.vercel.app";

// /repos/[repoId] is per-user/dynamic (a workspace for whatever repo someone
// just analyzed) -- it has no fixed, crawlable set of values, so it's
// intentionally left out of this list rather than enumerated.
export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  return [
    { url: SITE_URL, lastModified, changeFrequency: "weekly", priority: 1 },
    { url: `${SITE_URL}/repos`, lastModified, changeFrequency: "weekly", priority: 0.8 },
    { url: `${SITE_URL}/settings`, lastModified, changeFrequency: "monthly", priority: 0.3 },
    { url: `${SITE_URL}/privacy`, lastModified, changeFrequency: "yearly", priority: 0.2 },
    { url: `${SITE_URL}/terms`, lastModified, changeFrequency: "yearly", priority: 0.2 },
  ];
}
