"""N01: Point forecast retrieval. Independent of the balloon flight simulator.

N03 cache policy is implemented separately in weather_cache.py.
All timestamps at interface are explicit JST offsets (+09:00).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import json
import math
import urllib.parse
import urllib.request

JST = timezone(timedelta(hours=9))
API = 'https://api.open-meteo.com/v1/forecast'
FIELDS = ('weather_code','wind_direction_10m','wind_speed_10m','wind_gusts_10m','precipitation','temperature_2m')
LABELS = {0:'快晴',1:'晴れ',2:'一部曇り',3:'曇り',45:'霧',48:'着氷性の霧',51:'弱い霧雨',53:'霧雨',55:'強い霧雨',56:'弱い着氷性の霧雨',57:'強い着氷性の霧雨',61:'弱い雨',63:'雨',65:'強い雨',66:'弱い着氷性の雨',67:'強い着氷性の雨',71:'弱い雪',73:'雪',75:'強い雪',77:'霧雪',80:'弱いにわか雨',81:'にわか雨',82:'激しいにわか雨',85:'弱いにわか雪',86:'強いにわか雪',95:'雷雨',96:'雷雨（弱いひょう）',99:'雷雨（強いひょう）'}


def jst_now():
    return datetime.now(JST)


def parse_datetime(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError('日時はISO 8601の文字列で指定してください')
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('日時の形式が不正です') from exc
    if dt.tzinfo is None or dt.utcoffset() != timedelta(hours=9):
        raise ValueError('日時には+09:00を明示してください')
    if dt.second or dt.microsecond:
        raise ValueError('日時は分単位で指定してください')
    return dt.astimezone(JST)


def validate(latitude: Any, longitude: Any, when: str, now: datetime):
    for label, n, lo, hi in [('緯度', latitude, -90, 90), ('経度', longitude, -180, 180)]:
        if isinstance(n, bool) or not isinstance(n, (int,float)) or not math.isfinite(n) or not lo <= n <= hi:
            raise ValueError(f'{label}は{lo}〜{hi}の数値で指定してください')
    requested = parse_datetime(when)
    start = now.astimezone(JST).date()
    if not start <= requested.date() < start + timedelta(days=7):
        raise LookupError('当日を含む7暦日の範囲外です')
    return requested


def api_url(lat: float, lon: float) -> str:
    params = {
        'latitude':lat, 'longitude':lon,
        'hourly':','.join(FIELDS), 'timezone':'Asia/Tokyo',
        'wind_speed_unit':'ms', 'temperature_unit':'celsius',
        'precipitation_unit':'mm', 'forecast_days':'7',
        'models':'best_match'
    }
    return API + '?' + urllib.parse.urlencode(params)


def fetch_raw(lat: float, lon: float) -> dict:
    request = urllib.request.Request(api_url(lat,lon), headers={'User-Agent':'BalloonLab-WeatherPoC/0.1'})
    with urllib.request.urlopen(request,timeout=10) as res:
        return json.load(res)


def _number(values, index, integer=False):
    if not isinstance(values,list) or index >= len(values):
        return None
    value = values[index]
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        return None
    return int(value) if integer and int(value)==value else value


def _item(hourly, idx, dt):
    code = _number(hourly.get('weather_code'),idx,True)
    result = {
        'valid_time':dt.isoformat(timespec='minutes'),
        'weather_code':code,
        'weather_label':LABELS.get(code,'不明'),
        'wind_direction_deg':_number(hourly.get('wind_direction_10m'),idx),
        'wind_speed_ms':_number(hourly.get('wind_speed_10m'),idx),
        'wind_gust_ms':_number(hourly.get('wind_gusts_10m'),idx),
        'precipitation_mm':_number(hourly.get('precipitation'),idx),
        'temperature_c':_number(hourly.get('temperature_2m'),idx)
    }
    missing=[key for key in ('weather_code','wind_direction_deg','wind_speed_ms','wind_gust_ms','precipitation_mm','temperature_c') if result[key] is None]
    result['missing_fields']=missing
    return result


def interpret(raw: dict, *, latitude: float, longitude: float, when: str, candidate_id=None, fetched_at=None, now=None) -> dict:
    now=now or jst_now()
    try:
        requested=validate(latitude,longitude,when,now)
    except (ValueError,LookupError) as exc:
        return {'status':'out_of_range' if isinstance(exc,LookupError) else 'invalid_input', 'error':str(exc)}
    try:
        hourly=raw['hourly']
        times=[datetime.fromisoformat(t).replace(tzinfo=JST) for t in hourly['time']]
        if not times or any(times[i] >= times[i+1] for i in range(len(times)-1)):
            raise ValueError('時間軸が不正です')
        previous=[i for i,t in enumerate(times) if t<=requested]
        following=[i for i,t in enumerate(times) if t>=requested]
        before=previous[-1] if previous else None
        after=following[0] if following else None
        if before is None and after is None:
            raise ValueError('利用できる予報時刻がありません')
        before_data=_item(hourly,before,times[before]) if before is not None else None
        after_data=_item(hourly,after,times[after]) if after is not None and after!=before else None
        missing=bool((before_data and before_data['missing_fields']) or (after_data and after_data['missing_fields']))
        incomplete=before is None or after is None
        returned=[x for x in (before_data,after_data) if x]
        # A single matching instant is a complete bracket, not a partial result.
        if before is not None and after == before:
            incomplete=False
        return {
            'status':'partial' if missing or incomplete else 'success',
            'candidate_id':candidate_id,
            'requested_location':{'latitude':latitude,'longitude':longitude},
            'api_location':{'latitude':raw.get('latitude'),'longitude':raw.get('longitude'),'elevation_m':raw.get('elevation')},
            'requested_datetime':requested.isoformat(timespec='minutes'),
            'source':'open-meteo','model_selection':'best_match',
            'fetched_at':(fetched_at or jst_now()).astimezone(JST).isoformat(timespec='seconds'),
            'forecast':{'before':before_data,'after':after_data},
            'missing_bracket':{'before':before is None,'after':after is None},
            'available_hourly_count':len(times)
        }
    except (KeyError,TypeError,ValueError,AttributeError) as exc:
        return {'status':'api_error','error':'APIデータ構造が不正です: '+str(exc)}


def get_weather(latitude,longitude,when,candidate_id=None,fetcher=fetch_raw,now=None):
    now=now or jst_now()
    try:
        validate(latitude,longitude,when,now)
    except (ValueError,LookupError) as exc:
        return {'status':'out_of_range' if isinstance(exc,LookupError) else 'invalid_input','error':str(exc)}
    try:
        raw=fetcher(latitude,longitude)
        stamp=jst_now()
    except Exception as exc:
        return {'status':'api_error','error':'予報APIを取得できません: '+str(exc)}
    return interpret(raw,latitude=latitude,longitude=longitude,when=when,candidate_id=candidate_id,fetched_at=stamp,now=now)
