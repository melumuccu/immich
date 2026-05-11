CREATE TABLE IF NOT EXISTS favorite_signal (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  immich_asset_id TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  cleared_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE (profile_id, immich_asset_id)
);

CREATE TABLE IF NOT EXISTS trash_signal (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  immich_asset_id TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  restored_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE (profile_id, immich_asset_id)
);

CREATE TABLE IF NOT EXISTS apply_exclusion_asset (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  immich_asset_id TEXT NOT NULL,
  score_run_id TEXT,
  action_log_id TEXT,
  reason TEXT NOT NULL,
  excluded_at TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS score_threshold_policy (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  policy_key TEXT NOT NULL,
  threshold_value REAL NOT NULL,
  media_scope TEXT NOT NULL DEFAULT 'all',
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  UNIQUE (profile_id, policy_key)
);

CREATE TABLE IF NOT EXISTS score_run (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  model_run_id TEXT,
  trigger_type TEXT NOT NULL,
  status TEXT NOT NULL,
  scope_json TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS score_result (
  id TEXT PRIMARY KEY,
  score_run_id TEXT NOT NULL REFERENCES score_run(id) ON DELETE CASCADE,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  immich_asset_id TEXT NOT NULL,
  total_score REAL NOT NULL,
  rank_index INTEGER NOT NULL,
  category_scores_json TEXT NOT NULL DEFAULT '{}',
  current_state_json TEXT NOT NULL DEFAULT '{}',
  scored_at TEXT NOT NULL,
  UNIQUE (score_run_id, immich_asset_id)
);

CREATE TABLE IF NOT EXISTS job_run (
  id TEXT PRIMARY KEY,
  profile_id TEXT,
  job_type TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  status TEXT NOT NULL,
  summary_json TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_favorite_signal_profile_asset
  ON favorite_signal(profile_id, immich_asset_id);

CREATE INDEX IF NOT EXISTS idx_trash_signal_profile_asset
  ON trash_signal(profile_id, immich_asset_id);

CREATE INDEX IF NOT EXISTS idx_apply_exclusion_profile_asset_active
  ON apply_exclusion_asset(profile_id, immich_asset_id, active);

CREATE INDEX IF NOT EXISTS idx_score_run_profile_completed_at
  ON score_run(profile_id, completed_at DESC);

CREATE INDEX IF NOT EXISTS idx_score_result_run_rank
  ON score_result(score_run_id, rank_index ASC);

CREATE INDEX IF NOT EXISTS idx_job_run_job_type_started_at
  ON job_run(job_type, started_at DESC);
