-- Staging-таблицы (temp tables) для legacy VBA ETL → SQLite.
-- Маппинг имён: memory/sql_temp_tables_schema.md

CREATE TABLE IF NOT EXISTS gpb_temp (
    col_01 TEXT,
    col_02 TEXT,
    col_03 TEXT,
    col_04 TEXT,
    col_05 TEXT,
    col_06 TEXT,
    col_07 TEXT,
    col_08 TEXT,
    col_09 TEXT
);

CREATE TABLE IF NOT EXISTS region_temp (
    col_01 TEXT,
    col_02 TEXT,
    col_03 TEXT,
    col_04 TEXT,
    col_05 TEXT,
    col_06 TEXT,
    col_07 TEXT,
    col_08 TEXT,
    col_09 TEXT,
    col_10 TEXT,
    col_11 TEXT,
    col_12 TEXT,
    col_13 TEXT,
    col_14 TEXT,
    col_15 TEXT,
    col_16 TEXT,
    col_17 TEXT,
    col_18 TEXT,
    col_19 TEXT,
    col_20 TEXT,
    col_21 TEXT,
    col_22 TEXT,
    col_23 TEXT,
    col_24 TEXT,
    col_25 TEXT,
    col_26 TEXT,
    col_27 TEXT,
    col_28 TEXT,
    col_29 TEXT,
    col_30 TEXT,
    col_31 TEXT,
    col_32 TEXT,
    col_33 TEXT,
    col_34 TEXT,
    col_35 TEXT,
    col_36 TEXT,
    col_37 TEXT,
    col_38 TEXT,
    col_39 TEXT,
    col_40 TEXT
);

CREATE TABLE IF NOT EXISTS region2_temp (
    depo_account TEXT,
    division_name TEXT,
    quantity TEXT,
    agreement_number TEXT,
    registration_number TEXT
);

CREATE TABLE IF NOT EXISTS vtb_temp (
    schet TEXT,
    col_01 TEXT,
    col_02 TEXT,
    col_03 TEXT,
    col_04 TEXT,
    col_05 TEXT,
    col_06 TEXT,
    col_07 TEXT,
    col_08 TEXT,
    col_09 TEXT,
    col_10 TEXT,
    col_11 TEXT,
    col_12 TEXT
);

CREATE TABLE IF NOT EXISTS rsd_temp (
    col_01 TEXT,
    col_02 TEXT,
    col_03 TEXT,
    col_04 TEXT,
    col_05 TEXT,
    col_06 TEXT
);

CREATE TABLE IF NOT EXISTS rsd_dop_temp (
    schet TEXT,
    col_02 TEXT,
    col_03 TEXT,
    col_04 TEXT,
    col_05 TEXT,
    col_06 TEXT,
    col_07 TEXT,
    col_08 TEXT,
    col_09 TEXT,
    col_10 TEXT
);
