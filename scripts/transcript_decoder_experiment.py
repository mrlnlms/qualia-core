"""Ensaios isolados do decoder. Sem --execute apenas descreve o trabalho.

Imports de modelos/NumPy e leitura dos áudios ocorrem somente no worker.
Referências de comparação nunca são abertas pelo ensaio.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from qualia.transcription.segments import repeated_segment_runs


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def windows(samples, size, rate=16000):
    if samples <= 0 or size < 0 or rate <= 0:
        raise ValueError('Áudio vazio ou janela inválida')
    width = round(size * rate) if size else samples
    if width < 1:
        raise ValueError('Janela menor que uma amostra')
    return [(start, min(start + width, samples)) for start in range(0, samples, width)]


def global_segments(segments, offset):
    return [{'start': s.t0 / 100 + offset, 'end': s.t1 / 100 + offset,
             'text': s.text} for s in segments]


def default_variants():
    variants = []
    for name, params in [('default', {}), ('no-context', {'no_context': True}),
                         ('zero-text-context', {'n_max_text_ctx': 0})]:
        for callback in [False, True]:
            variants.append({'id': name + ('-callback' if callback else '-no-callback'),
                             'callback': callback, 'chunk_seconds': 0, 'decoder': dict(params)})
    for seconds in [60, 180]:
        variants.append({'id': f'chunks-{seconds}s', 'callback': False,
                         'chunk_seconds': seconds, 'decoder': {'no_context': True}})
    return variants


def validate(config):
    if config['model'] != 'large-v3' or config['language'] != 'pt':
        raise ValueError('Esta versão controla large-v3/pt')
    ids = [x['id'] for x in config['inputs']]
    variants = [x['id'] for x in config['variants']]
    if len(set(ids)) != len(ids) or len(set(variants)) != len(variants):
        raise ValueError('IDs duplicados')
    for key in ids + variants:
        if not key or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in key):
            raise ValueError('ID inválido')
    for variant in config['variants']:
        if not isinstance(variant['callback'], bool):
            raise ValueError('callback deve ser booleano')
        windows(1, variant['chunk_seconds'])
        params = variant['decoder']
        if 'no_context' in params and not isinstance(params['no_context'], bool):
            raise ValueError('no_context deve ser booleano')
        if 'n_max_text_ctx' in params and (type(params['n_max_text_ctx']) is not int or params['n_max_text_ctx'] < 0):
            raise ValueError('n_max_text_ctx deve ser inteiro não negativo')
        if set(params) - {'no_context', 'n_max_text_ctx'}:
            raise ValueError('Parâmetro fora do ensaio controlado')


def signature(config, root):
    files = ['scripts/transcript_decoder_experiment.py', 'scripts/transcript_benchmark.py',
             'qualia/transcription/segments.py', 'qualia/transcription/decoder.py',
             'qualia/transcription/speech.py', 'qualia/transcription/audit.py']
    return {'config': config,
            'sources': {x['id']: sha(root / x['audio']) for x in config['inputs']},
            'code': {p: sha(REPO / p) for p in files}}


def prepare(config, root, out):
    sig = signature(config, root)
    target = out / 'config-and-sources.json'
    if target.exists():
        if read(target) != sig:
            raise ValueError('Código/configuração/fontes mudaram; crie outra versão')
        return
    model_file = config.get('model_file')
    if model_file and sha(Path(model_file)) != config['model_sha256']:
        raise ValueError('Modelo mudou; revisar proveniência antes de executar')
    out.mkdir(parents=True, exist_ok=True)
    packages = {}
    for name in ['pywhispercpp', 'numpy', 'torch', 'pyannote.audio']:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    save(out / 'environment.json', {'python': sys.version, 'packages': packages})
    if model_file:
        stat = Path(model_file).stat()
        save(out / 'model-provenance.json', {'file': model_file, 'sha256': config['model_sha256'],
                                             'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns})
    for p in sig['code']:
        dest = out / 'source' / p
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / p, dest)
    save(target, sig)


def worker(config, root, out, variant, case):
    # Este caminho só é chamado após --execute no coordenador.
    from pywhispercpp.model import Model
    from pywhispercpp.constants import PARAMS_SCHEMA
    from transcript_benchmark import audio_array

    sig = read(out / 'config-and-sources.json')
    if signature(config, root) != sig:
        raise ValueError('Proveniência mudou antes do worker')
    dest = out / variant['id'] / f"{case['id']}.transcription.json"
    if dest.exists():
        previous = read(dest)
        if previous['source_sha256'] != sig['sources'][case['id']] or previous['variant'] != variant:
            raise ValueError('Resultado incompatível')
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    journal = dest.with_name(f"{case['id']}.chunks.jsonl")
    if config.get('model_file'):
        evidence = read(out / 'model-provenance.json')
        stat = Path(config['model_file']).stat()
        if stat.st_size != evidence['size'] or stat.st_mtime_ns != evidence['mtime_ns']:
            raise ValueError('Arquivo de modelo mudou depois da verificação')
    waveform = audio_array(root / case['audio'])
    bounds = windows(len(waveform), variant['chunk_seconds'])
    rows, chunks, effective = [], [], None
    begin = time.monotonic()
    # Journal diagnóstico de tentativa, não checkpoint reutilizável.
    # Retomada ocorre por áudio concluído; tentativa interrompida ganha outro journal.
    if journal.exists():
        journal.rename(journal.with_name(journal.name + f'.interrupted-{time.time_ns()}'))
    with journal.open('x') as stream:
        for index, (start, end) in enumerate(bounds):
            # Modelo novo por chamada: não herdar callback/contexto de outra janela.
            model = Model(config.get('model_file', config['model']), params_sampling_strategy=0, n_threads=4,
                          print_progress=False, print_realtime=False,
                          redirect_whispercpp_logs_to=None, **variant['decoder'])
            effective = {}
            for key in PARAMS_SCHEMA:
                value = getattr(model._params, key, None)
                if value is None or isinstance(value, (str, int, float, bool)):
                    effective[key] = value
            emitted = []
            options = {'new_segment_callback': emitted.append} if variant['callback'] else {}
            started = time.monotonic()
            result = model.transcribe(waveform[start:end], language=config['language'], **options)
            effective['language'] = config['language']
            local = global_segments(result, start / 16000)
            callback_rows = global_segments(emitted, start / 16000)
            chunk = {'index': index, 'start_sample': start, 'end_sample': end,
                     'elapsed_seconds': time.monotonic() - started, 'segments': local,
                     'callback_segments': callback_rows if variant['callback'] else None,
                     'callback_equals_return': callback_rows == local if variant['callback'] else None}
            stream.write(json.dumps(chunk, ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
            chunks.append(chunk)
            rows.extend(local)
            del result, model
            print(variant['id'], case['id'], f'janela {index+1}/{len(bounds)}', flush=True)
    repeats = repeated_segment_runs(rows)
    save(dest, {'source': Path(case['audio']).name, 'source_sha256': sig['sources'][case['id']],
                'model': config['model'], 'language': config['language'], 'variant': variant,
                'effective_decoder_params': effective, 'sampling_strategy': 'greedy',
                'pywhispercpp': importlib.metadata.version('pywhispercpp'),
                'audio_duration_seconds': len(waveform) / 16000,
                'elapsed_seconds': time.monotonic() - begin, 'segments': rows,
                'chunks': [{k: v for k, v in c.items() if k not in ('segments', 'callback_segments')} for c in chunks],
                'repeat_runs': repeats,
                'longest_identical_run': max((r['count'] for r in repeats), default=0),
                'nonpositive_intervals': sum(s['end'] <= s['start'] for s in rows),
                'out_of_bounds_intervals': sum(s['start'] < 0 or s['end'] > len(waveform)/16000 + .02 for s in rows),
                'warning': 'Janelas sem sobreposição; fronteiras exigem conferência auditiva. Ausência de repetição não prova recuperação.'})


def summarize(config, out):
    reports = []
    for variant in config['variants']:
        for case in config['inputs']:
            p = out / variant['id'] / f"{case['id']}.transcription.json"
            if not p.exists():
                reports.append({'variant': variant['id'], 'input': case['id'], 'status': 'pending'})
                continue
            d = read(p)
            reports.append({'variant': variant['id'], 'input': case['id'], 'status': 'completed',
                            'segments': len(d['segments']), 'words': sum(len(s['text'].split()) for s in d['segments']),
                            **{k: d[k] for k in ['elapsed_seconds', 'longest_identical_run', 'nonpositive_intervals', 'out_of_bounds_intervals']}})
    save(out / 'summary.json', reports)
    return reports


def select(config, root, out, selected, target):
    variant = next(v for v in config['variants'] if v['id'] == selected)
    if signature(config, root) != read(out / 'config-and-sources.json'):
        raise ValueError('Proveniência mudou')
    if target.exists():
        raise ValueError('Manifesto de destino já existe; não sobrescrever')
    inputs = []
    diarizations = []
    for case in config['inputs']:
        transcript = out / selected / f"{case['id']}.transcription.json"
        if not transcript.exists():
            raise ValueError('Seleção exige os três áudios concluídos')
        diar_path = root / case['reuse_diarization']
        diar = read(diar_path)
        if diar.get('source_sha256') != sha(root / case['audio']) or diar.get('speaker_options') != {}:
            raise ValueError('Diarização não corresponde à fonte/contagem automática')
        data = read(transcript)
        if data.get('source_sha256') != sha(root / case['audio']) or data.get('variant') != variant:
            raise ValueError('Transcrição candidata incompatível')
        entry = {k: v for k, v in case.items() if k != 'reuse_diarization'}
        for key in ['audio', 'reference', 'baseline']:
            if entry.get(key):
                entry[key] = str((root / entry[key]).resolve())
        entry['reuse_transcription'] = str(transcript.resolve())
        inputs.append(entry)
        diarizations.append((case['id'], diar_path, diar))
    v3 = root / 'runs' / '2026-10-14-v3'
    if v3.exists():
        raise ValueError('Pasta v3 já existe; não sobrescrever')
    # Apenas cópias verificadas; nenhuma inferência é executada na seleção.
    for case_id, diar_path, diar in diarizations:
        save(v3 / f'{case_id}.diarization.json',
             {**diar, 'reused_from': str(diar_path.resolve()), 'reused_sha256': sha(diar_path)})
    save(target, {'output': str(v3.resolve()),
                  'model': config['model'], 'language': config['language'], 'device': 'mps',
                  'num_speakers': None, 'max_gap': 1.5, 'inputs': inputs,
                  'decoder_experiment': {'manifest': str((out / 'config-and-sources.json').resolve()),
                                         'selected_variant': variant, 'status': 'selected_for_validation'}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='Inicia inferência; usar somente com a máquina livre')
    parser.add_argument('--variant')
    parser.add_argument('--case')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--select', choices=None, help='Congela candidato após revisão dos ensaios')
    parser.add_argument('--target-manifest', type=Path)
    args = parser.parse_args()
    config = read(args.manifest)
    validate(config)
    root = args.manifest.resolve().parent
    out = root / config['output']
    if args.select:
        if args.execute or not args.target_manifest:
            parser.error('--select requer --target-manifest e não aceita --execute')
        select(config, root, out, args.select, args.target_manifest.resolve())
        return
    variants = [v for v in config['variants'] if args.variant is None or v['id'] == args.variant]
    cases = [c for c in config['inputs'] if args.case is None or c['id'] == args.case]
    if not variants or not cases:
        parser.error('Variante ou entrada desconhecida')
    if not args.execute:
        print(json.dumps({'status': 'prepared_not_executed', 'output': str(out),
                          'variants': variants, 'inputs': [c['id'] for c in cases],
                          'jobs': len(variants)*len(cases)}, ensure_ascii=False, indent=2))
        return
    if args.worker:
        if len(variants) != 1 or len(cases) != 1:
            parser.error('Worker exige uma variante e uma entrada')
        worker(config, root, out, variants[0], cases[0])
        return
    prepare(config, root, out)
    for variant in variants:
        for case in cases:
            log = out / variant['id'] / f"{case['id']}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open('a') as stream:
                subprocess.run([sys.executable, str(Path(__file__).resolve()), '--manifest', str(args.manifest.resolve()),
                                '--execute', '--worker', '--variant', variant['id'], '--case', case['id']],
                               stdout=stream, stderr=subprocess.STDOUT, check=True)
            summarize(config, out)
            print('Concluído:', variant['id'], case['id'], flush=True)


if __name__ == '__main__':
    main()
