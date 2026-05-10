ALTER TABLE collector_cursor ADD COLUMN pending_page TEXT;
ALTER TABLE collector_cursor ADD COLUMN pending_page_size INTEGER;
ALTER TABLE collector_cursor ADD COLUMN pending_updated_before TEXT;
ALTER TABLE collector_cursor ADD COLUMN pending_trashed_before TEXT;
