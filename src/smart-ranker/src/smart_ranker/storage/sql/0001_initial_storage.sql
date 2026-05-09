PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ranker_profile (
  id TEXT PRIMARY KEY,
  immich_user_id TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  timezone TEXT NOT NULL,
  locale TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS person_group (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  group_key TEXT NOT NULL,
  display_name TEXT NOT NULL,
  group_type TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  UNIQUE (profile_id, group_key)
);

CREATE TABLE IF NOT EXISTS person_group_member (
  id TEXT PRIMARY KEY,
  person_group_id TEXT NOT NULL REFERENCES person_group(id) ON DELETE CASCADE,
  immich_person_id TEXT NOT NULL,
  immich_person_name TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  UNIQUE (person_group_id, immich_person_id)
);

CREATE TABLE IF NOT EXISTS category (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  category_key TEXT NOT NULL,
  display_name TEXT NOT NULL,
  category_type TEXT NOT NULL,
  media_scope TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  UNIQUE (profile_id, category_key)
);

CREATE TABLE IF NOT EXISTS routing_rule (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  category_id TEXT NOT NULL REFERENCES category(id) ON DELETE CASCADE,
  rule_name TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 100,
  match_json TEXT NOT NULL DEFAULT '{}',
  assignment_mode TEXT NOT NULL,
  stop_after_match INTEGER NOT NULL DEFAULT 0 CHECK (stop_after_match IN (0, 1)),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS training_signal_rule (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  match_json TEXT NOT NULL DEFAULT '{}',
  signal_kind TEXT NOT NULL,
  label_value REAL NOT NULL,
  weight REAL NOT NULL,
  precedence INTEGER NOT NULL DEFAULT 100,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS action_destination (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  destination_key TEXT NOT NULL,
  destination_type TEXT NOT NULL,
  immich_resource_id TEXT NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}',
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  UNIQUE (profile_id, destination_key)
);

CREATE TABLE IF NOT EXISTS action_policy (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  policy_key TEXT NOT NULL,
  display_name TEXT NOT NULL,
  execution_mode TEXT NOT NULL,
  display_json TEXT NOT NULL DEFAULT '{}',
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  UNIQUE (profile_id, policy_key)
);

CREATE TABLE IF NOT EXISTS action_policy_step (
  id TEXT PRIMARY KEY,
  action_policy_id TEXT NOT NULL REFERENCES action_policy(id) ON DELETE CASCADE,
  destination_id TEXT NOT NULL REFERENCES action_destination(id) ON DELETE CASCADE,
  trigger_kind TEXT NOT NULL,
  action_type TEXT NOT NULL,
  step_order INTEGER NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}',
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  UNIQUE (action_policy_id, step_order)
);

CREATE TABLE IF NOT EXISTS category_score_policy (
  id TEXT PRIMARY KEY,
  category_id TEXT NOT NULL REFERENCES category(id) ON DELETE CASCADE,
  action_policy_id TEXT NOT NULL REFERENCES action_policy(id) ON DELETE CASCADE,
  media_type TEXT NOT NULL,
  review_threshold REAL NOT NULL,
  candidate_threshold REAL NOT NULL,
  video_penalty REAL NOT NULL DEFAULT 0,
  aggregation_method TEXT NOT NULL DEFAULT 'max',
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  UNIQUE (category_id, media_type)
);

CREATE TABLE IF NOT EXISTS execution_schedule (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  job_type TEXT NOT NULL,
  run_mode TEXT NOT NULL,
  cron_expr TEXT,
  dry_run INTEGER NOT NULL DEFAULT 1 CHECK (dry_run IN (0, 1)),
  batch_size INTEGER NOT NULL DEFAULT 100,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  UNIQUE (profile_id, job_type)
);

CREATE TABLE IF NOT EXISTS collector_cursor (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  collector_key TEXT NOT NULL,
  updated_after TEXT,
  trashed_after TEXT,
  last_succeeded_at TEXT,
  last_attempted_at TEXT,
  last_run_id TEXT,
  UNIQUE (profile_id, collector_key)
);

CREATE TABLE IF NOT EXISTS inference_trace (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  immich_asset_id TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  execution_mode TEXT NOT NULL,
  candidate_categories_json TEXT NOT NULL DEFAULT '[]',
  score_json TEXT NOT NULL DEFAULT '{}',
  final_score REAL NOT NULL,
  threshold_snapshot_json TEXT NOT NULL DEFAULT '{}',
  protected INTEGER NOT NULL DEFAULT 0 CHECK (protected IN (0, 1)),
  occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback_event (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  category_id TEXT REFERENCES category(id) ON DELETE SET NULL,
  source_trace_id TEXT REFERENCES inference_trace(id) ON DELETE SET NULL,
  immich_asset_id TEXT NOT NULL,
  feedback_type TEXT NOT NULL,
  previous_score REAL,
  label_value REAL NOT NULL,
  sample_weight REAL NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  note TEXT,
  occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_execution_log (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES ranker_profile(id) ON DELETE CASCADE,
  inference_trace_id TEXT NOT NULL REFERENCES inference_trace(id) ON DELETE CASCADE,
  action_policy_id TEXT NOT NULL REFERENCES action_policy(id) ON DELETE CASCADE,
  destination_id TEXT NOT NULL REFERENCES action_destination(id) ON DELETE CASCADE,
  immich_asset_id TEXT NOT NULL,
  action_type TEXT NOT NULL,
  execution_mode TEXT NOT NULL,
  dry_run INTEGER NOT NULL CHECK (dry_run IN (0, 1)),
  status TEXT NOT NULL,
  request_json TEXT NOT NULL DEFAULT '{}',
  response_json TEXT NOT NULL DEFAULT '{}',
  error_message TEXT,
  executed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_event_profile_asset_occurred_at
  ON feedback_event(profile_id, immich_asset_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_collector_cursor_profile_key
  ON collector_cursor(profile_id, collector_key);

CREATE INDEX IF NOT EXISTS idx_inference_trace_profile_asset_occurred_at
  ON inference_trace(profile_id, immich_asset_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_action_execution_log_profile_asset_executed_at
  ON action_execution_log(profile_id, immich_asset_id, executed_at DESC);

CREATE INDEX IF NOT EXISTS idx_action_execution_log_trace
  ON action_execution_log(inference_trace_id);
