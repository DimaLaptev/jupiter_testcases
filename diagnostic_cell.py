# Прицельная диагностика 2025: почему месяцы не проходят фильтр
# Использует объекты из расширенной диагностики: diag, m_send, m_not_cancel, m_approved, m_not_predict.

year_target = 2025

if "diag" not in globals():
    print("Сначала запустите ячейку 'Расширенная диагностика фильтров'.")
else:
    year_prefix = f"{year_target}-"
    months_target = sorted([m for m in diag["month_key"].unique() if str(m).startswith(year_prefix)])

    if not months_target:
        print(f"В исходном массиве нет строк за {year_target} год")
    else:
        diag_year = diag[diag["month_key"].isin(months_target)].copy()

        diag_year["m_send"] = m_send.loc[diag_year.index]
        diag_year["m_not_cancel"] = m_not_cancel.loc[diag_year.index]
        diag_year["m_approved"] = m_approved.loc[diag_year.index]
        diag_year["m_not_predict"] = m_not_predict.loc[diag_year.index]

        diag_year["step1"] = diag_year["m_send"]
        diag_year["step2"] = diag_year["step1"] & diag_year["m_not_cancel"]
        diag_year["step3"] = diag_year["step2"] & diag_year["m_approved"]
        diag_year["step4"] = diag_year["step3"] & diag_year["m_not_predict"]

        summary_year = (
            diag_year.groupby("month_key", as_index=False)
            .agg(
                total_rows=("month_key", "size"),
                send_true=("m_send", "sum"),
                not_cancel_true=("m_not_cancel", "sum"),
                approved_true=("m_approved", "sum"),
                not_predict_true=("m_not_predict", "sum"),
                step1_pass=("step1", "sum"),
                step2_pass=("step2", "sum"),
                step3_pass=("step3", "sum"),
                step4_pass=("step4", "sum"),
                validate_count_0=("validate_count", lambda s: (s == 0).sum()),
                validate_count_1=("validate_count", lambda s: (s == 1).sum()),
                validate_count_ge2=("validate_count", lambda s: (s >= 2).sum()),
                v1_true=("validate_one", "sum"),
                v2_true=("validate_two", "sum"),
                predict_comment_true=("comment", lambda s: (s == "first_predict_value_record").sum()),
                cancel_approve_true=("cancel_approve", "sum"),
            )
            .sort_values("month_key")
            .reset_index(drop=True)
        )

        print(f"=== {year_target}: breakdown по маскам ===")
        print(summary_year.to_string(index=False))

        print(f"\n=== Топ причин отсечения в {year_target} (по строкам) ===")
        reason_rows = []
        for m in months_target:
            sub = diag_year[diag_year["month_key"] == m]
            if sub.empty:
                continue
            reason_rows.append({
                "month_key": m,
                "total": len(sub),
                "fail_send": int((~sub["m_send"]).sum()),
                "fail_cancel": int((sub["m_send"] & ~sub["m_not_cancel"]).sum()),
                "fail_validation": int((sub["m_send"] & sub["m_not_cancel"] & ~sub["m_approved"]).sum()),
                "fail_comment": int((sub["m_send"] & sub["m_not_cancel"] & sub["m_approved"] & ~sub["m_not_predict"]).sum()),
                "final_pass": int(sub["step4"].sum()),
            })

        if reason_rows:
            print(pd.DataFrame(reason_rows).to_string(index=False))

        # Показываем небольшой сэмпл строк за год, которые не прошли step3 (валидацию)
        failed_step3 = diag_year[diag_year["step2"] & ~diag_year["step3"]].copy()
        if not failed_step3.empty:
            show_cols = [
                c for c in [
                    "id", "period", "month_key", "send", "cancel_approve",
                    "validate_count", "validate_one", "validate_two", "comment", "forecast"
                ] if c in failed_step3.columns
            ]
            print(f"\n=== Пример строк {year_target}, не прошедших step3 (валидацию) ===")
            print(failed_step3[show_cols].head(20).to_string(index=False))