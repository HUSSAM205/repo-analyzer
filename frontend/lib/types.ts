export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface ApiError {
  detail: string;
}

export interface Repo {
  id: string;
  url: string;
  name: string;
  status: "pending" | "ready" | "failed";
  created_at: string;
}

export interface Job {
  id: string;
  repo_id: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  error_message: string | null;
  skipped_files: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface AnalyzeRepoResponse {
  repo_id: string;
  job_id: string;
}

export interface FileTreeEntry {
  name: string;
  path: string;
  type: "file" | "directory";
  children: FileTreeEntry[] | null;
}

export interface FileTreeResponse {
  entries: FileTreeEntry[];
}
