"""
Поиск аномальных fact_value в app_history_resistparametercalculatehistory.

По каждой операции строится ряд по всей истории. Точка — аномалия, если
fact_value строго больше ANOMALY_RATIO × running-max всех предыдущих месяцев.
В отчёт попадают только периоды 2025–2026.

Запуск:
    python postgres_anomaly_detection.py
    python postgres_anomaly_detection.py --resist-id 46
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import psycopg2

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "sla_app_backup_3"
DB_USER = "user"
DB_PASSWORD = "password"

ANOMALY_RATIO = 3.0
ANOMALY_YEARS = (2025, 2026)

EXCLUDED_RESIST_IDS = [
    25, 26, 27, 29, 54, 57, 61, 63, 66, 68, 80, 81, 82, 83, 100, 101, 102, 103,
    104, 105, 106, 109, 112, 113, 115, 116, 119, 120, 121, 122, 123, 125, 126,
    129, 131, 132, 134, 135, 136, 137, 138, 140, 141, 143, 144, 146, 147, 148,
    149, 150, 151, 152, 153, 154, 156, 157, 158, 162, 165, 169, 170, 171, 172,
    173, 174, 175, 176, 177, 178, 179, 181, 196, 139,
]


def connect():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def fetch_resist_ids(conn) -> List[int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT resist_id
            FROM app_history_resistparametercalculatehistory
            ORDER BY resist_id
            """
        )
        return [int(row[0]) for row in cur.fetchall() if row[0] is not None]


def fetch_rows_for_resist_id(conn, resist_id: int) -> List[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, period, resist_id, operation_parameter::jsonb
            FROM app_history_resistparametercalculatehistory
            WHERE resist_id = %s
            ORDER BY period, id
            """,
            (resist_id,),
        )
        return list(cur.fetchall())


def extract_operation_data(operation_param_json) -> List[Dict[str, Any]]:
    if operation_param_json is None:
        return []
    try:
        data = (
            json.loads(operation_param_json)
            if isinstance(operation_param_json, str)
            else operation_param_json
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    result: List[Dict[str, Any]] = []
    if isinstance(data, list):
        items: Iterable[Any] = data
        for item in items:
            if not isinstance(item, dict):
                continue
            op_id = item.get("operation_id", item.get("id"))
            fact_value = item.get("fact_value")
            parsed = _parse_op_point(op_id, fact_value)
            if parsed is not None:
                result.append(parsed)
        return result

    if isinstance(data, dict):
        for op_id, payload in data.items():
            fact_value = payload.get("fact_value") if isinstance(payload, dict) else payload
            parsed = _parse_op_point(op_id, fact_value)
            if parsed is not None:
                result.append(parsed)
    return result


def _parse_op_point(op_id, fact_value) -> Optional[Dict[str, Any]]:
    if op_id is None or fact_value is None:
        return None
    try:
        return {"operation_id": str(op_id), "fact_value": float(fact_value)}
    except (TypeError, ValueError):
        return None


def period_year(period) -> Optional[int]:
    if period is None:
        return None
    try:
        return int(str(period)[:4])
    except (TypeError, ValueError):
        return None


def find_anomalies(rows_all: Sequence[tuple]) -> List[Dict[str, Any]]:
    """Аномалии 2025–2026; running-max считается по всей истории операции."""
    op_data: Dict[str, List[Dict[str, Any]]] = {}
    for _row_id, period, _resist_id, operation_param in rows_all:
        for op in extract_operation_data(operation_param):
            op_data.setdefault(op["operation_id"], []).append(
                {"period": period, "fact_value": op["fact_value"]}
            )

    anomalies: List[Dict[str, Any]] = []
    for op_id, records in op_data.items():
        records.sort(key=lambda item: str(item["period"]) if item["period"] is not None else "")
        if len(records) < 2:
            continue

        max_previous = records[0]["fact_value"]
        for rec in records[1:]:
            current = rec["fact_value"]
            year = period_year(rec["period"])
            if (
                max_previous is not None
                and max_previous > 0
                and current > ANOMALY_RATIO * max_previous
                and year in ANOMALY_YEARS
            ):
                anomalies.append(
                    {
                        "period": rec["period"],
                        "operation_id": op_id,
                        "fact_value": current,
                        "max_previous": max_previous,
                        "ratio": current / max_previous,
                    }
                )
            if current > max_previous:
                max_previous = current

    anomalies.sort(key=lambda item: (str(item["period"]), str(item["operation_id"])))
    return anomalies


def summarize(anomalies: Sequence[Dict[str, Any]]) -> Tuple[int, Optional[float], Optional[float]]:
    if not anomalies:
        return 0, None, None
    ratios = [float(a["ratio"]) for a in anomalies]
    return len(ratios), max(ratios), sum(ratios) / len(ratios)


def print_resist_summary(resist_id: int, n: int, max_x: Optional[float], mean_x: Optional[float]) -> None:
    print(f"resist_id={resist_id}")
    print(f"  аномалий ({ANOMALY_YEARS[0]}-{ANOMALY_YEARS[-1]}, порог x{ANOMALY_RATIO:g}): {n}")
    if n == 0:
        print("  max x: —")
        print("  mean x: —")
        return
    print(f"  max x: {max_x:.2f}")
    print(f"  mean x: {mean_x:.2f}")


def process_resist_id(conn, resist_id: int) -> Tuple[int, Optional[float], Optional[float]]:
    rows = fetch_rows_for_resist_id(conn, resist_id)
    anomalies = find_anomalies(rows)
    n, max_x, mean_x = summarize(anomalies)
    print_resist_summary(resist_id, n, max_x, mean_x)
    return n, max_x, mean_x


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Аномалии fact_value по моделям численности")
    parser.add_argument(
        "--resist-id",
        type=int,
        action="append",
        dest="resist_ids",
        help="Обработать только этот resist_id (можно повторять). По умолчанию — все, кроме EXCLUDED.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    conn = connect()
    try:
        if args.resist_ids:
            resist_ids = list(args.resist_ids)
        else:
            resist_ids = [
                rid for rid in fetch_resist_ids(conn) if rid not in EXCLUDED_RESIST_IDS
            ]

        print(
            f"Порог: x{ANOMALY_RATIO:g}, годы флага: {ANOMALY_YEARS[0]}-{ANOMALY_YEARS[-1]}, "
            f"сравнение со всей историей. Моделей: {len(resist_ids)}"
        )
        print()

        totals = []
        for resist_id in resist_ids:
            n, max_x, mean_x = process_resist_id(conn, resist_id)
            totals.append((resist_id, n, max_x, mean_x))
            print()

        with_hits = [row for row in totals if row[1] > 0]
        print("=" * 60)
        print(f"Итого моделей с аномалиями: {len(with_hits)} из {len(totals)}")
        if with_hits:
            print(f"{'resist_id':>10} {'n':>6} {'max x':>10} {'mean x':>10}")
            for resist_id, n, max_x, mean_x in with_hits:
                print(f"{resist_id:>10} {n:>6} {max_x:10.2f} {mean_x:10.2f}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
