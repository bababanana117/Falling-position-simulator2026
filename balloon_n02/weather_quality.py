"""N02: validate point forecast values and attach quality metadata.

No assessment of launch safety or forecast skill. Does not modify physics.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Any
from weather_service import JST, LABELS

FIELD_MAP = {
    'weather_code': 'weather_code',
    'wind_direction_deg': 'wind_direction_10m',
    'wind_speed_ms': 'wind_speed_10m',
    'wind_gust_ms': 'wind_gusts_10m',
    'precipitation_mm': 'precipitation',
    'temperature_c': 'temperature_2m',
}

DEFAULT_THRESHOLDS = {
    'wind_speed_ms': {'max': 45.0},
    'wind_gust_ms': {'max': 65.0},
    'precipitation_mm': {'max': 100.0},
    'temperature_c': {'min': -50.0, 'max': 50.0},
}


def check_config(thresholds: dict | None) -> dict:
    config = {k: dict(v) for k, v in DEFAULT_THRESHOLDS.items()}
    if thresholds is None:
        return config
    if not isinstance(thresholds, dict):
        raise ValueError('警告閾値はオブジェクトで指定してください')
    for field, limits in thresholds.items():
        if field not in config or not isinstance(limits, dict):
            raise ValueError(f'未対応の警告閾値: {field}')
        for bound, value in limits.items():
            if bound not in config[field] or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'警告閾値が不正: {field}.{bound}')
            config[field][bound] = float(value)
        if config[field].get('min', -math.inf) > config[field].get('max', math.inf):
            raise ValueError(f'警告閾値の上下限が逆です: {field}')
    return config


def classify(field: str, value: Any, config: dict) -> tuple[str, str | None]:
    if value is None:
        return 'missing', None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 'invalid_value', None
    if field == 'weather_code':
        if not isinstance(value, int) and not (isinstance(value, float) and value.is_integer()):
            return 'invalid_value', None
        if int(value) not in LABELS:
            return 'unknown_weather_code', None
    if field == 'wind_direction_deg' and not 0 <= value < 360:
        return 'invalid_value', None
    if field in ('wind_speed_ms', 'wind_gust_ms', 'precipitation_mm') and value < 0:
        return 'invalid_value', None
    if field == 'temperature_c' and not -100 <= value <= 60:
        return 'invalid_value', None
    bounds = config.get(field)
    if bounds and (value < bounds.get('min', -math.inf) or value > bounds.get('max', math.inf)):
        return 'extreme_value', 'warning'
    return 'valid', None


def normalize_refresh(refresh: dict | None) -> dict:
    if refresh is None:
        return {'status': 'unknown', 'error_code': None}
    status = refresh.get('status', 'unknown')
    if status not in ('success', 'failed', 'not_attempted', 'unknown'):
        status = 'unknown'
    code = refresh.get('error_code') if status == 'failed' else None
    return {'status': status, 'error_code': code}


def apply_quality(result: dict, raw: dict | None, *, now: datetime | None = None,
                  ttl: timedelta = timedelta(minutes=30),
                  thresholds: dict | None = None,
                  last_refresh: dict | None = None,
                  cache_hit: bool | None = None) -> dict:
    """Mutate only a shallow copy of a N01 result; returns N01 JSON plus quality."""
    now = (now or datetime.now(JST)).astimezone(JST)
    config = check_config(thresholds)
    result = dict(result)
    refresh = normalize_refresh(last_refresh)
    stamp = result.get('fetched_at')
    try:
        fetched = datetime.fromisoformat(stamp)
        if fetched.tzinfo is None:
            raise ValueError('timezone required')
        age = max(0, (now - fetched.astimezone(JST)).total_seconds())
        freshness = 'fresh' if age < ttl.total_seconds() else 'stale'
    except (ValueError, TypeError, AttributeError):
        age, freshness = None, 'unknown'
    if raw is None and not result.get('forecast'):
        freshness = 'unavailable'
    issues = []
    forecast = result.get('forecast')
    hourly = raw.get('hourly', {}) if isinstance(raw, dict) else {}
    times = hourly.get('time', []) if isinstance(hourly, dict) else []
    time_lookup = {t: i for i, t in enumerate(times) if isinstance(t, str)}
    if isinstance(forecast, dict):
        forecast = dict(forecast)
        for slot in ('before', 'after'):
            record = forecast.get(slot)
            if record is None:
                continue
            record = dict(record)
            valid_time = record.get('valid_time')
            # N01 returns explicit JST offset, Open-Meteo uses local ISO time.
            key = valid_time[:16] if isinstance(valid_time, str) else ''
            index = time_lookup.get(key)
            states = {}
            for output_field, source_field in FIELD_MAP.items():
                values = hourly.get(source_field)
                if index is None or not isinstance(values, list) or index >= len(values):
                    original = None
                else:
                    original = values[index]
                kind, severity = classify(output_field, original, config)
                states[output_field] = kind
                if kind != 'valid':
                    issue = {'time_slot': slot, 'valid_time': valid_time,
                             'field': output_field, 'type': kind,
                             'severity': severity or ('info' if kind == 'missing' else 'warning')}
                    if kind == 'extreme_value':
                        issue['value'] = original
                    issues.append(issue)
                if kind in ('missing', 'invalid_value', 'unknown_weather_code'):
                    record[output_field] = None if kind != 'unknown_weather_code' else original
                    if kind == 'unknown_weather_code':
                        record['weather_label'] = '不明'
                elif kind == 'valid' or kind == 'extreme_value':
                    record[output_field] = int(original) if output_field == 'weather_code' else original
            record['missing_fields'] = [field for field, kind in states.items()
                                        if kind in ('missing', 'invalid_value')]
            record['field_quality'] = states
            forecast[slot] = record
        result['forecast'] = forecast
        missing = any(x['type'] in ('missing', 'invalid_value', 'unknown_weather_code') for x in issues)
        incomplete = bool(any(result.get('missing_bracket', {}).values()))
        if result.get('status') in ('success', 'partial'):
            result['status'] = 'partial' if missing or incomplete else 'success'
    result['quality'] = {
        'freshness': freshness,
        'fetched_at': stamp,
        'age_seconds': round(age) if age is not None else None,
        'last_refresh': refresh,
        'cache_hit': cache_hit,
        'issues': issues,
        'thresholds': config,
        'model_run_time': None,
    }
    return result
