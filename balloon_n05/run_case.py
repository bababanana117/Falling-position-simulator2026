"""Run one genuine saved-GFS case. Does not acquire weather or call APIs."""
import argparse
import sys
from pathlib import Path
from n05_adapter import EngineBinding, strict_json, file_hash, write_new, error_info

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--engine-root', required=True)
    p.add_argument('--config', required=True)
    p.add_argument('--weather', required=True)
    p.add_argument('--latitude', type=float)
    p.add_argument('--longitude', type=float)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    try:
        binding = EngineBinding(a.engine_root)
        out = binding.outside_repo(a.out)
        if out.exists():
            raise FileExistsError('output already exists; use a new filename')
        config = strict_json(a.config)
        config_hash = file_hash(a.config)
        try:
            field, weather = binding.load_gfs(a.weather)
        except Exception as exc:
            write_new(out, {'provenance': binding.provenance(), 'state': 'weather_load_error',
                            'config_path': str(Path(a.config).resolve()), 'config_sha256': config_hash,
                            'weather_path': str(Path(a.weather).resolve()), 'error': error_info(exc), 'landing': None})
            return 2
        record = binding.run(config, field, a.latitude, a.longitude)
        binding.assert_unchanged()
        if file_hash(a.weather) != weather['sha256'] or file_hash(a.config) != config_hash:
            raise ValueError('input files changed during calculation; output not accepted')
        write_new(out, {'provenance': binding.provenance(), 'weather': weather,
                        'config_path': str(Path(a.config).resolve()), 'config_sha256': config_hash, **record})
        print(record['state'], '=>', out)
        return 0 if record['state'] == 'landed' else 2
    except Exception as exc:
        print(error_info(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
