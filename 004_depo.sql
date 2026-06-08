-- Фаза depo (svod_depo): ручные правки, реестр, архив предсвода.

CREATE TABLE IF NOT EXISTS ruki_temp (
    col_01 TEXT,
    col_02 TEXT,
    col_03 TEXT,
    col_04 TEXT,
    col_05 TEXT,
    col_06 TEXT,
    col_07 TEXT,
    col_08 TEXT
);

CREATE TABLE IF NOT EXISTS editable_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT 'predsvod',
    portfolio_section TEXT,
    n_zakladnoy TEXT,
    depository TEXT,
    owner TEXT,
    schet_depo TEXT,
    razdel_scheta TEXT,
    quantity TEXT,
    fio TEXT,
    nomer_kd TEXT,
    ngri_v_depo TEXT,
    ngri_v_portfele TEXT,
    vremennoe_snyatie TEXT,
    enc TEXT,
    agent_soprovozhdeniya TEXT,
    pul_zakladnyh TEXT,
    gorod_hraneniya TEXT,
    comment TEXT,
    massiv_po_n TEXT,
    massiv_po_ngri TEXT,
    master_date TEXT,
    investor TEXT,
    servisny_agent TEXT,
    status_eis TEXT,
    data_pogasheniya_eis TEXT,
    status_hraneniya TEXT,
    hranitel TEXT,
    data_priema TEXT,
    schet_depo2 TEXT,
    razdel TEXT,
    nomer_kd2 TEXT,
    sverka_s_defoltami TEXT,
    sovpad TEXT,
    lock INTEGER NOT NULL DEFAULT 0,
    loaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_editable_registry_portfolio
    ON editable_registry (portfolio_section);

CREATE INDEX IF NOT EXISTS idx_editable_registry_ngri
    ON editable_registry (ngri_v_depo);

CREATE INDEX IF NOT EXISTS idx_editable_registry_zakladnoy
    ON editable_registry (n_zakladnoy);

CREATE TABLE IF NOT EXISTS predsvod_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT NOT NULL,
    archived_at TEXT NOT NULL,
    col_01 TEXT, col_02 TEXT, col_03 TEXT, col_04 TEXT, col_05 TEXT, col_06 TEXT,
    col_07 TEXT, col_08 TEXT, col_09 TEXT, col_10 TEXT, col_11 TEXT, col_12 TEXT,
    col_13 TEXT, col_14 TEXT, col_15 TEXT, col_16 TEXT, col_17 TEXT, col_18 TEXT,
    col_19 TEXT, col_20 TEXT, col_21 TEXT, col_22 TEXT, col_23 TEXT, col_24 TEXT
);

CREATE INDEX IF NOT EXISTS idx_predsvod_archive_at
    ON predsvod_archive (archived_at, source_table);
