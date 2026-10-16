"""N05 only: bind to an unmodified external Balloon Lab installation."""
from __future__ import annotations
import copy
import hashlib
import importlib
import importlib.metadata
import json
import math
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_COMMIT = 'fbb1cc76c112d8c495d2044604b330f1c0f5c8d6'

def package_versions():
    versions = {}
    for name in ('numpy', 'scipy', 'geographiclib'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions

class N05Error(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)

def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def strict_json(path):
    def pairs(items):
        d = {}
        for k, v in items:
            if k in d:
                raise N05Error('INVALID_JSON', 'duplicate key: ' + k)
            d[k] = v
        return d
    def invalid(value):
        raise N05Error('INVALID_JSON', 'nonfinite number: ' + value)
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            invalid(value)
        return number
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=invalid, parse_float=finite_float)

def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, allow_nan=False, indent=2)
        f.write('\n')

def coordinate(value, name, low, high, strict=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise N05Error('INVALID_COORDINATE', name + ' must be numeric')
    try:
        good = math.isfinite(value) and (low < value < high if strict else low <= value <= high)
    except (ValueError, OverflowError):
        good = False
    if not good:
        raise N05Error('INVALID_COORDINATE', name + ' is outside the engine domain')
    return value

def change_location(config, latitude=None, longitude=None):
    if not isinstance(config, dict) or not isinstance(config.get('launch'), dict):
        raise N05Error('INVALID_CONFIG', 'config.launch must be an object')
    c = copy.deepcopy(config)
    lat = c['launch'].get('latitude_deg') if latitude is None else latitude
    lon = c['launch'].get('longitude_deg') if longitude is None else longitude
    c['launch']['latitude_deg'] = coordinate(lat, 'latitude', -90, 90, True)
    c['launch']['longitude_deg'] = coordinate(lon, 'longitude', -180, 180)
    return c

def extract_landing(result):
    if not isinstance(result, dict) or result.get('status') not in ('landed', 'stopped'):
        raise N05Error('INVALID_ENGINE_RESULT', 'unknown flight result status')
    if result['status'] == 'stopped':
        return None
    landing = result.get('summary', {}).get('landing')
    if result.get('complete') is not True or not isinstance(landing, dict):
        raise N05Error('INVALID_ENGINE_RESULT', 'landed result has no complete landing')
    coordinate(landing.get('latitude_deg'), 'landing latitude', -90, 90, True)
    coordinate(landing.get('longitude_deg'), 'landing longitude', -180, 180)
    return copy.deepcopy(landing)

def error_info(exc):
    return {'code': getattr(exc, 'code', type(exc).__name__), 'type': type(exc).__name__, 'message': str(exc)}

def run_loaded(config, weather, *, latitude=None, longitude=None, simulator=None, validator=None):
    """Mocks can be injected in unit tests; CLI always uses the original engine."""
    submitted = copy.deepcopy(config)
    started = time.perf_counter()
    resolved = None
    try:
        resolved = change_location(config, latitude, longitude)
        if validator is None:
            from balloon_sim.flight.config import validate_config
            validator = validate_config
        # Validate with the original engine, not a parallel physical validator.
        validator(copy.deepcopy(resolved))
    except Exception as exc:
        return {'state': 'input_error', 'input': submitted, 'case_config': resolved,
                'result': None, 'landing': None, 'error': error_info(exc),
                'validation_seconds': time.perf_counter() - started, 'simulate_seconds': None}
    validation_s = time.perf_counter() - started
    if simulator is None:
        from balloon_sim.flight.trajectory import simulate
        simulator = simulate
    t0 = time.perf_counter()
    try:
        result = simulator(copy.deepcopy(resolved), weather)
        compute_s = time.perf_counter() - t0
        landing = extract_landing(result)
        return {'state': result['status'], 'input': submitted, 'case_config': resolved,
                'result': result, 'landing': landing, 'error': result.get('stop_reason'),
                'validation_seconds': validation_s, 'simulate_seconds': compute_s}
    except Exception as exc:
        return {'state': 'engine_exception', 'input': submitted, 'case_config': resolved,
                'result': None, 'landing': None, 'error': error_info(exc),
                'validation_seconds': validation_s, 'simulate_seconds': time.perf_counter() - t0}

class EngineBinding:
    def __init__(self, root):
        root = Path(root).resolve()
        if not (root / 'balloon_sim/flight/trajectory.py').is_file():
            raise N05Error('ENGINE_NOT_FOUND', 'engine-root must point to iwata_dir')
        self.root = root
        # Do not write __pycache__ into the existing repository.
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(root))
        importlib.invalidate_caches()
        self.module = importlib.import_module('balloon_sim.flight.trajectory')
        if Path(self.module.__file__).resolve() != root / 'balloon_sim/flight/trajectory.py':
            raise N05Error('WRONG_ENGINE_IMPORT', 'another balloon_sim is already imported')
        self.storage = importlib.import_module('balloon_sim.environment.storage')
        self.validate = importlib.import_module('balloon_sim.flight.config').validate_config
        self.before = self.source_hashes()
        self.environment = {'python': platform.python_version(), 'platform': platform.platform(),
                            'packages': package_versions(),
                            'expected_packages': {'numpy': '2.4.4', 'scipy': '1.17.1', 'geographiclib': '2.1'}}
        try:
            self.commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            self.commit = None
        if self.commit != EXPECTED_COMMIT:
            raise N05Error('COMMIT_MISMATCH', 'use the verified fixed commit; re-audit a newer checkout first')

    def source_hashes(self):
        return {p.relative_to(self.root).as_posix(): file_hash(p)
                for folder in ('balloon_sim', 'backend') for p in sorted((self.root / folder).rglob('*.py'))}

    def assert_unchanged(self):
        if self.source_hashes() != self.before:
            raise N05Error('ENGINE_CHANGED', 'existing engine source changed during verification')

    def outside_repo(self, output):
        p = Path(output).resolve()
        # Git repo root can contain iwata_dir and other tracked folders.
        try:
            git_root = Path(subprocess.check_output(['git', '-C', str(self.root), 'rev-parse', '--show-toplevel'], text=True).strip())
        except (OSError, subprocess.CalledProcessError):
            git_root = self.root
        if p == git_root or git_root in p.parents:
            raise N05Error('OUTPUT_IN_REPOSITORY', 'write verification output outside the existing repository')
        return p

    def load_gfs(self, path):
        path = Path(path).resolve()
        before = file_hash(path)
        t0 = time.perf_counter()
        field = self.storage.load_weather(path)
        load_s = time.perf_counter() - t0
        # Do not silently accept JRA or unknown weather as a GFS experiment.
        from balloon_sim.environment.bundle import WeatherField
        if type(field) is not WeatherField or not field.metadata.get('run_utc') or 'GFS' not in str(field.metadata.get('source', '')).upper():
            raise N05Error('NOT_VERIFIED_GFS', 'requires a saved GFS bundle with source and run_utc metadata')
        if file_hash(path) != before:
            raise N05Error('WEATHER_CHANGED', 'weather bytes changed while loading')
        return field, {'path': str(path), 'sha256': before, 'bytes': path.stat().st_size,
                       'metadata': copy.deepcopy(field.metadata), 'load_seconds': load_s}

    def run(self, config, field, latitude=None, longitude=None):
        return run_loaded(config, field, latitude=latitude, longitude=longitude,
                          simulator=self.module.simulate, validator=self.validate)

    def provenance(self):
        return {'engine_root': str(self.root), 'commit': self.commit,
                'source_sha256': self.before, 'environment': self.environment,
                'created_utc': datetime.now(timezone.utc).isoformat(), 'mock': False}
