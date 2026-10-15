CREATE TABLE bot_autopilot (
    bot_id TEXT PRIMARY KEY REFERENCES bots(id) ON DELETE CASCADE,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    changed_by TEXT NOT NULL REFERENCES users(id),
    changed_at TEXT NOT NULL
);
ALTER TABLE approvals ADD COLUMN decision_source TEXT CHECK(decision_source IN ('manual','policy','autopilot','observation'));
ALTER TABLE approvals ADD COLUMN autopilot_revision INTEGER;
UPDATE approvals SET decision_source = CASE
    WHEN policy_id IS NOT NULL THEN 'policy'
    WHEN decided_by = 'system:observation' THEN 'observation'
    WHEN decided_by IS NOT NULL THEN 'manual'
END;
