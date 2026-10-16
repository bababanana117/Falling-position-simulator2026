"""Serial only; measurements require approved real GFS and flight config."""
import argparse
import copy
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from n05_adapter import EngineBinding, strict_json, file_hash, write_new, coordinate, error_info

def benchmark(binding, config, weather_path, sites, count, reload_each=False):
    if len(sites) < count:
        raise ValueError('not enough supplied case coordinates; no automatic generation')
    records = []
    begin = time.perf_counter()
    shared, first_info = binding.load_gfs(weather_path)
    total_load = first_info['load_seconds']
    for i, site in enumerate(sites[:count]):
        field, info = (shared, first_info)
        if reload_each and i:
            field, info = binding.load_gfs(weather_path)
            if info['sha256'] != first_info['sha256']:
                raise ValueError('weather changed between loads')
            total_load += info['load_seconds']
        record = binding.run(config, field, site['latitude_deg'], site['longitude_deg'])
        records.append(record)
        print(f'{count} cases / {"reload" if reload_each else "reuse"}: {i+1}/{count}', file=sys.stderr)
    total_s = time.perf_counter() - begin
    times = [r['simulate_seconds'] for r in records if r['simulate_seconds'] is not None]
    return {'count': count, 'mode': 'reload_each' if reload_each else 'reuse_loaded',
            'weather': first_info, 'weather_load_count': count if reload_each else 1,
            'total_load_seconds': total_load, 'batch_seconds': total_s,
            'simulate_seconds_sum': sum(times),
            'simulate_median_seconds': statistics.median(times) if times else None,
            'states': dict(Counter(r['state'] for r in records)), 'cases': records}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--engine-root', required=True); p.add_argument('--config', required=True)
    p.add_argument('--weather', required=True); p.add_argument('--sites', required=True)
    p.add_argument('--counts', nargs='+', type=int, default=[1, 10, 50])
    p.add_argument('--compare-reload', action='store_true'); p.add_argument('--out', required=True)
    a = p.parse_args()
    try:
        if any(n not in (1, 10, 50) for n in a.counts) or len(set(a.counts)) != len(a.counts):
            raise ValueError('counts must be distinct choices from 1,10,50')
        binding = EngineBinding(a.engine_root); out = binding.outside_repo(a.out)
        if out.exists(): raise FileExistsError('output already exists')
        c = strict_json(a.config); sites = strict_json(a.sites)
        if not isinstance(sites, list) or not sites: raise ValueError('sites must be an explicit nonempty list')
        for s in sites:
            if not isinstance(s, dict) or set(s) != {'latitude_deg', 'longitude_deg'}:
                raise ValueError('each site needs exactly latitude_deg and longitude_deg')
            coordinate(s['latitude_deg'], 'latitude', -90, 90, True)
            coordinate(s['longitude_deg'], 'longitude', -180, 180)
        if len(sites) < max(a.counts): raise ValueError('insufficient supplied sites')
        hashes = {str(Path(x).resolve()): file_hash(x) for x in (a.config, a.weather, a.sites)}
        batches = []
        for n in a.counts:
            batches.append(benchmark(binding, c, a.weather, sites, n))
            if a.compare_reload:
                batches.append(benchmark(binding, c, a.weather, sites, n, True))
            binding.assert_unchanged()
            if any(file_hash(k) != v for k, v in hashes.items()):
                raise ValueError('input bytes changed; benchmark not accepted')
            # Save a separate checkpoint after every completed batch; no overwrite.
            checkpoint = out.with_name(out.stem + f'.batch-{len(batches)}' + out.suffix)
            write_new(checkpoint, {'provenance': binding.provenance(), 'input_sha256': hashes, 'batches': copy.deepcopy(batches)})
        write_new(out, {'provenance': binding.provenance(), 'input_sha256': hashes,
                        'timing_note': 'batch includes loading/hash/validation; excludes final JSON write and source verification', 'batches': batches})
        print(out)
        return 0
    except Exception as exc:
        print(json.dumps(error_info(exc), ensure_ascii=False), file=sys.stderr); return 2

if __name__ == '__main__': raise SystemExit(main())
