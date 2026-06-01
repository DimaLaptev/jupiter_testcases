-- Итоговая таблица после post_process (аналог наполнение_изменяемой).

CREATE TABLE IF NOT EXISTS working_mortgage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    schet TEXT,
    data_json TEXT NOT NULL,
    loaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
