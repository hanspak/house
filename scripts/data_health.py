"""게시 자료의 기준기간·수집일을 별도로 점검한다. 공식 공표 주기 판정은 아니다."""
import datetime as dt
import re

KST = dt.timezone(dt.timedelta(hours=9))
WEEKLY_DAYS, MONTHLY_MONTHS, COLLECTION_DAYS = 14, 2, 3


def kst_today(now=None):
    return (now or dt.datetime.now(KST)).astimezone(KST).date()


def parse_date(value):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def month_age(value, today):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}', value):
        return None
    try:
        date = dt.date.fromisoformat(value + '-01')
    except ValueError:
        return None
    return (today.year-date.year)*12 + today.month-date.month


def assess(source, today=None):
    today = today or kst_today()
    kind = source.get('kind', 'monthly')
    issues, notes = [], []
    age = None
    if kind == 'weekly':
        date = parse_date(source.get('period'))
        age = (today-date).days if date else None
        if age is None:
            issues.append('자료 기준일 확인 불가')
        elif age < 0:
            issues.append('자료 기준일이 점검일보다 미래')
        elif age > WEEKLY_DAYS:
            issues.append(f'기준일 {age}일 경과 · {WEEKLY_DAYS}일 기준 초과')
        notes.append('새 주간 엑셀을 드라이브에 올린 후 정기·수동 갱신')
    elif kind == 'forecast':
        start = month_age(source.get('horizon_start'), today)
        end = month_age(source.get('horizon_end'), today)
        if start is None or end is None or start < end:
            issues.append('전망 범위 확인 불가')
        elif start < 0 or end > 0:
            issues.append('현재 월이 공식 전망 범위 밖')
        elif end > -11:
            issues.append('현재 월 포함 12개월 전망 범위 부족')
        if parse_date(source.get('asof')) is None:
            issues.append('공식 전망 기준일 확인 불가')
        elif parse_date(source['asof']) > today:
            issues.append('공식 전망 기준일이 점검일보다 미래')
        notes.append('예정월은 실적 기준일이 아님 · 공식 전망 기준일과 범위를 함께 확인')
    else:
        age = month_age(source.get('period'), today)
        if age is None:
            issues.append('자료 기준월 확인 불가')
        elif age < 0:
            issues.append('자료 기준월이 점검월보다 미래')
        elif age > MONTHLY_MONTHS:
            issues.append(f'기준월 {age}개월 경과 · {MONTHLY_MONTHS}개월 기준 초과')
        if kind == 'kb_monthly':
            notes.append('새 월간 엑셀을 드라이브에 올린 후 정기·수동 갱신')
    collected = parse_date(source.get('collected'))
    collection_age = (today-collected).days if collected else None
    if kind not in ('weekly', 'kb_monthly'):
        if collection_age is None:
            issues.append('수집일 확인 불가')
        elif collection_age < 0:
            issues.append('수집일이 점검일보다 미래')
        elif collection_age > COLLECTION_DAYS:
            issues.append(f'수집 {collection_age}일 경과 · {COLLECTION_DAYS}일 기준 초과')
        notes.append('정기·수동 실행의 수집 결과는 다음 배포에 반영')
    elif collected is None:
        notes.append('수집일 기록 없음 · 파일 기준기간으로만 점검')
    return {'status': 'review' if issues else 'within',
            'label': '확인 필요' if issues else '점검 기준 이내',
            'issues': issues, 'note': ' / '.join(notes),
            'period_age': age, 'collection_age_days': collection_age}


def report(sources, today=None):
    today = today or kst_today()
    rows = [{**source, 'health': assess(source, today)} for source in sources]
    return {'checked_on': today.isoformat(), 'timezone': 'Asia/Seoul',
            'review_count': sum(row['health']['status']=='review' for row in rows),
            'sources': rows,
            'policy': f'화면 생성 시 점검 · 주간 {WEEKLY_DAYS}일, 월간 {MONTHLY_MONTHS}개월, 수집 {COLLECTION_DAYS}일 초과 시 확인 권장. 대시보드 운영 기준이며 공식 공표 일정·수집 성공 여부를 판정하지 않습니다.'}
