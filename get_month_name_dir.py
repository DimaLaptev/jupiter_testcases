from datetime import datetime, timedelta


def get_current_year_month():
    yesterday = datetime.now() - timedelta(days=1)
    return f"{yesterday.year}_{yesterday.month:02d}"


def get_today_year_month():
    yesterday = datetime.now() - timedelta(days=1)
    return f"{yesterday.year}_{yesterday.month:02d}"


if __name__ == "__main__":
    print(get_current_year_month())
    print(get_today_year_month())
