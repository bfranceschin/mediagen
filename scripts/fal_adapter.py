"""Explicit fal schemas -> local-output executor. No independent publisher.

Only fal.media CDN downloads are supported; this is not an arbitrary URL fetcher.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import json
import re
import signal
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from generation_executor import GeneratedOutputs, GenerationSpec, LocalInput, LocalOutput, execute_generation

WAN_MODELS = {'wan26flash', 'wan2.6flash', 'wan'}
WAN_ENDPOINT = 'wan/v2.6/image-to-video/flash'


def add_arguments(parser):
    before = set(parser._option_string_actions)
    parser.add_argument('--negative-prompt', default='', help='Wan Flash negative prompt, max 500 characters')
    parser.add_argument('--no-prompt-expansion', action='store_true', help='Wan Flash: disable prompt expansion')
    parser.add_argument('--multi-shots', action='store_true', help='Wan Flash: multiple shots; requires prompt expansion')
    parser.add_argument('--run-id', help='Durable generation ID; same ID retries publication only')
    parser.add_argument('--fal-endpoint', help='fal endpoint identifier, not a URL')
    parser.add_argument('--fal-args', help='Explicit request JSON object (inline)')
    parser.add_argument('--operation', choices=['generate', 'edit', 'upscale', 'text-to-video', 'image-to-video'])
    parser.add_argument('--fal-kind', choices=['image', 'video'], help='Declared output kind')
    parser.add_argument('--fal-input-map', default='[]', help='JSON array: input index, path, role, kind')
    parser.add_argument('--fal-output-map', help='JSON array: response dot/index path and kind for each output')
    return set(parser._option_string_actions) - before


def _json(text, expected):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError):
        raise ValueError('invalid fal JSON configuration') from None
    if not isinstance(value, expected):
        raise ValueError('incorrect fal JSON configuration type')
    return value


def _parts(path):
    if not isinstance(path, str) or not re.fullmatch(r'(?:[A-Za-z_][A-Za-z0-9_]*|0|[1-9][0-9]*)(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|0|[1-9][0-9]*))*', path):
        raise ValueError('mapping path must use dot keys and nonnegative list indices')
    return path.split('.')


def _get(value, path):
    for key in _parts(path):
        try:
            value = value[int(key)] if isinstance(value, list) and key.isdigit() else value[key]
        except (KeyError, IndexError, TypeError):
            raise ValueError('mapping path does not exist or has incorrect container type') from None
    return value


def _bind(value, path, url):
    parts = _parts(path)
    parent = _get(value, '.'.join(parts[:-1])) if len(parts) > 1 else value
    key = parts[-1]
    if isinstance(parent, list) and key.isdigit():
        parent[int(key)] = url
    else:
        parent[key] = url


def _generic(args):
    if not isinstance(args.fal_endpoint, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)+', args.fal_endpoint):
        raise ValueError('fal endpoint must be a model identifier, not a URL')
    arguments = _json(args.fal_args, dict)
    # Explicit top-level control only: unknown endpoint schemas must not receive
    # invented fields or recursive edits to arbitrary nested provider data.
    if 'enable_safety_checker' in arguments:
        arguments['enable_safety_checker'] = False
    bindings = _json(args.fal_input_map, list)
    outputs = _json(args.fal_output_map, list)
    if not args.operation or not args.fal_kind or not outputs:
        raise ValueError('generic fal requires operation, kind and output mapping')
    sources = args.inputs or []
    if len(bindings) != len(sources):
        raise ValueError('every local input must have an ordered explicit binding')
    inputs = []
    paths = []
    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict) or set(binding) != {'input', 'path', 'role', 'kind'}:
            raise ValueError('input mapping requires input, path, role and kind')
        if type(binding['input']) is not int or binding['input'] != index:
            raise ValueError('input mappings must follow local input order')
        _get(arguments, binding['path'])
        parts = _parts(binding['path'])
        if parts[0] == 'enable_safety_checker':
            raise ValueError('input mapping cannot overwrite the safety checker control')
        if any(parts[:len(other)] == other or other[:len(parts)] == parts for other in paths):
            raise ValueError('input mapping paths must not duplicate or overlap')
        paths.append(parts)
        inputs.append(LocalInput(Path(sources[index]), binding['role'], binding['kind']))
    for output in outputs:
        if not isinstance(output, dict) or set(output) != {'path', 'kind'} or output['kind'] != args.fal_kind:
            raise ValueError('output mappings require explicit path and matching kind')
        _parts(output['path'])
    if args.prompt is not None:
        if 'prompt' in arguments and arguments['prompt'] != args.prompt:
            raise ValueError('conflicting prompt; use fal request JSON as source of truth')
        arguments['prompt'] = args.prompt
    if args.seed is not None:
        if 'seed' in arguments and arguments['seed'] != args.seed:
            raise ValueError('conflicting seed')
        arguments['seed'] = args.seed
    seed = arguments.get('seed')
    if seed is not None and type(seed) is not int:
        raise ValueError('seed must be an integer or null')
    prompt = arguments.get('prompt', '')
    if not isinstance(prompt, str):
        raise ValueError('prompt must be text')
    spec = GenerationSpec(args.run_id or uuid4().hex, args.operation, 'fal', args.fal_endpoint,
                          args.fal_endpoint, prompt, seed,
                          {'arguments': arguments, 'input_mapping': bindings, 'output_mapping': outputs}, tuple(inputs))
    return spec, arguments, bindings, outputs


def _cdn_url(url):
    try:
        if not isinstance(url, str) or '\\' in url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
            raise ValueError()
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if (parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.fragment
                or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*fal\.media', host)):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('output URL must be HTTPS on the supported fal.media CDN') from None
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('provider output redirects are not supported')


@contextmanager
def _download_deadline(timeout):
    """Linux CLI nested wall deadline, without resetting the callback's budget."""
    started = time.monotonic()
    previous = signal.getsignal(signal.SIGALRM)
    remaining, interval = signal.getitimer(signal.ITIMER_REAL)
    outer_first = 0 < remaining <= timeout
    budget = min(timeout, remaining) if remaining > 0 else timeout
    deadline = started + budget
    outer_fired = False

    def expired(signum: int = signal.SIGALRM, frame=None):
        nonlocal outer_fired
        if outer_first:
            outer_fired = True
            if callable(previous):
                previous(signum, frame)
        raise TimeoutError('provider download timed out')

    def check():
        if time.monotonic() >= deadline:
            expired()

    signal.signal(signal.SIGALRM, expired)
    try:
        check()
        signal.setitimer(signal.ITIMER_REAL, max(deadline - time.monotonic(), 1e-6))
        yield check
        check()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if remaining > 0 and not outer_fired:
            # Restore only the unused outer budget, even on I/O errors/timeouts.
            left = remaining - (time.monotonic() - started)
            signal.setitimer(signal.ITIMER_REAL, max(left, 1e-6), interval)
        elif outer_fired and interval > 0:
            signal.setitimer(signal.ITIMER_REAL, interval, interval)


def download_output(url, destination, *, max_bytes=100 * 1024 * 1024, timeout=120):
    request = urllib.request.Request(_cdn_url(url), headers={'Accept': '*/*'})
    # Never inherit provider auth, proxy credentials, cookies or redirect auth.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with _download_deadline(timeout) as check:
        with opener.open(request, timeout=timeout) as response, destination.open('wb') as target:
            check()
            total = 0
            while True:
                check()
                chunk = response.read(min(64 * 1024, max_bytes - total + 1))
                check()  # EOF must not turn an over-budget read into success.
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError('provider output exceeds byte limit')
                target.write(chunk)
            if not total:
                raise ValueError('provider output is empty')


def _wan(args):
    sources = args.inputs or []
    if len(sources) != 1 or not args.prompt:
        raise ValueError('Wan Flash requires a prompt and exactly one start frame')
    if len(args.prompt) > 1500 or len(args.negative_prompt) > 500:
        raise ValueError('Wan Flash prompt maximum is 1500 characters; negative prompt maximum is 500')
    if args.duration not in (5, 10, 15) or args.resolution not in (None, '720p', '1080p'):
        raise ValueError('Wan Flash requires duration 5|10|15 and resolution 720p|1080p')
    if args.multi_shots and args.no_prompt_expansion:
        raise ValueError('Wan Flash multi-shots requires prompt expansion')
    arguments = {'prompt': args.prompt, 'image_url': None, 'duration': str(args.duration),
                 'resolution': args.resolution or '720p', 'negative_prompt': args.negative_prompt,
                 'enable_prompt_expansion': not args.no_prompt_expansion, 'multi_shots': args.multi_shots,
                 'enable_safety_checker': False, 'generate_audio': not args.no_audio}
    if args.seed is not None:
        arguments['seed'] = args.seed
    bindings = [{'input': 0, 'path': 'image_url', 'role': 'start_frame', 'kind': 'image'}]
    outputs = [{'path': 'video.url', 'kind': 'video'}]
    spec = GenerationSpec(args.run_id or uuid4().hex, 'image-to-video', 'fal', 'wan26flash',
                          WAN_ENDPOINT, args.prompt, args.seed,
                          {'arguments': arguments, 'input_mapping': bindings, 'output_mapping': outputs},
                          (LocalInput(Path(sources[0]), 'start_frame', 'image'),))
    return spec, arguments, bindings, outputs


def run(args, *, workspace, require_client):
    spec, arguments, bindings, outputs = _wan(args) if args.model in WAN_MODELS else _generic(args)
    log_path = Path(workspace) / 'logs' / f'{spec.run_id}.json'
    resuming = log_path.exists() or log_path.with_suffix('.intent.json').exists()
    with tempfile.TemporaryDirectory(prefix='mediagen-fal-') as scratch:
        def generate(request):
            # Validate the executor's durable copy, only for a fresh generation.
            # Publication recovery must never depend on the original's contents.
            if args.model in WAN_MODELS:
                from PIL import Image
                try:
                    with Image.open(request.inputs[0].path) as image:
                        if any(not 240 <= side <= 7680 for side in image.size):
                            raise ValueError('Wan Flash start frame dimensions must each be 240..7680')
                        image.verify()
                except (OSError, SyntaxError):
                    raise ValueError('Wan Flash start frame must be a readable image') from None
            client = require_client()
            payload = copy.deepcopy(arguments)
            def timeout_handler(*_):
                raise TimeoutError('fal request timed out; outcome uncertain, never auto-resubmit')
            previous = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(300)
            try:
                for binding, item in zip(bindings, request.inputs):
                    _bind(payload, binding['path'], client.upload_file(str(item.path)))
                result = client.subscribe(spec.endpoint, arguments=payload)
                urls = [_cdn_url(_get(result, item['path'])) for item in outputs]
                local = []
                for index, (url, output) in enumerate(zip(urls, outputs)):
                    path = Path(scratch) / f'output-{index}.{ "png" if output["kind"] == "image" else "mp4"}'
                    download_output(url, path)
                    local.append(LocalOutput(path, output['kind']))
                seed = result.get('seed', spec.seed) if isinstance(result, dict) else spec.seed
                metadata = result if isinstance(result, dict) else {'response': result}
                return GeneratedOutputs(local, seed, metadata)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)
        result = execute_generation(spec, generate, workspace=workspace)
    print(f'PUBLICATION={result.publication["status"]} RUN_ID={spec.run_id}', file=sys.stderr)
    generation = json.loads(result.log_path.read_text())['generation']
    seed = generation['seed']
    prompt = generation['prompt'].replace('\n', ' ').replace('\r', ' ')
    print(f'FILENAME={result.outputs[0]} PROMPT={prompt} SEED={seed if seed is not None else "n/a"}')
    if resuming and result.publication['status'] not in ('completed', 'disabled'):
        raise SystemExit(1)
    return result
