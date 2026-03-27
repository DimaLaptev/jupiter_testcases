# Лист «Лучшие»: по каждому resist_id — строка с максимальным «Качество, %» (после ячейки с сохранением Итог)
df_best = pd.DataFrame()
if not df_results.empty:
    df_best = (
        df_results.sort_values(
            ["Качество, %", "Конфигурация", "Набор признаков"],
            ascending=[False, True, True],
        )
        .drop_duplicates("resist_id", keep="first")
        .sort_values("resist_id")
        .reset_index(drop=True)
    )

if not OUT_XLSX.exists():
    raise FileNotFoundError(
        f"Нет файла {OUT_XLSX}; сначала выполните предыдущую ячейку с экспортом Excel."
    )

with pd.ExcelWriter(
    OUT_XLSX,
    engine="openpyxl",
    mode="a",
    if_sheet_exists="replace",
) as w:
    df_best.to_excel(w, sheet_name="Лучшие", index=False)
print(f"Лист «Лучшие» записан: {OUT_XLSX.resolve()}")