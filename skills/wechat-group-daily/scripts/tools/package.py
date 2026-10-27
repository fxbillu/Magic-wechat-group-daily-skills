"""Validate an explicit release inventory and build an internal candidate ZIP.

No publishing, tags, dependency installation, or user configuration access.
Exit 0: requested checks passed; 1: blocked; 2: invalid CLI usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import importlib.metadata
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
from pathlib import Path, PurePosixPath
import shutil
import stat
import sqlite3
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
NAME = 'wechat-group-daily'
MANIFEST = 'references/release-files.json'
RUNTIME_NAMES = {'config.json', 'all_keys.json', '.stamp.json', '.env', 'data', 'reports',
                 'logs', 'secrets', 'decrypted', 'dist', '__pycache__', 'legacy-import',
                 'collections', 'report-records', 'daily-state'}
# These cannot be made optional by deleting a line from the release inventory.
ESSENTIAL = {
    'SKILL.md', 'VERSION', MANIFEST, 'references/writing-spec.md',
    'references/dependencies.md', 'references/third-party.md', 'references/third-party.json',
    'references/windows-acceptance.md', 'licenses/vue-MIT.txt', 'licenses/wcdb-key-tool-MIT.txt',
    'scripts/config.example.json', 'scripts/fetch.py', 'scripts/lib/wechat_data/collection.py',
    'scripts/lib/wechat_data/daily.py',
    'scripts/tools/setup.py', 'scripts/tools/doctor.py',
    'scripts/tools/desktop.py', 'scripts/lib/wechat_data/desktop.py',
    'scripts/assets/magic-reader.ico', 'scripts/assets/magic-reader.svg',
    'scripts/tools/serve.py', 'scripts/tools/render_daily.py',
    'scripts/tools/check_story.py', 'scripts/tools/safe_decrypt.py',
    'scripts/tools/wcdb_key_tool_windows.py', 'scripts/tools/zstd_bridge.js',
    'scripts/tools/package.py', 'scripts/web/index.html', 'scripts/web/app.css',
    'scripts/web/app.js', 'scripts/web/vendor/vue.global.prod.js',
}


class Blocked(Exception):
    pass


# Only this reviewed original icon is accepted as a binary; all other payloads
# remain UTF-8 text, including SVG and extensionless VERSION.
REVIEWED_BINARY_SHA256 = {
    'scripts/assets/magic-reader.ico': 'cfb7588a4aae63cf86e276c311b8bbe01a9b377445653ffb2a8be3b1a78c27eb',
}
TEXT_SUFFIXES = {'.py', '.js', '.md', '.json', '.txt', '.html', '.css', '.svg'}
LEAK_RULES = [
    ('account_id', re.compile(r'wxid_[A-Za-z0-9_-]{6,}')),
    ('group_id', re.compile(r'\b[A-Za-z0-9_-]{6,}@chatroom\b')),
    ('windows_home', re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s"<>]+', re.I)),
    ('unix_home', re.compile(r'/(?:Users|home)/[A-Za-z0-9_.-]+/')),
    ('private_key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('key_value', re.compile(r'["\'](?:enc_key|passphrase|api_key|access_token)["\']\s*:\s*["\'][A-Za-z0-9_+/=-]{16,}', re.I)),
    ('synthetic_marker', re.compile('WECHAT_DAILY_' + 'SYNTHETIC_LEAK')),
]


def scan_text(path, rel):
    if rel in REVIEWED_BINARY_SHA256:
        return ([] if hashlib.sha256(path.read_bytes()).hexdigest() == REVIEWED_BINARY_SHA256[rel]
                else [f'BINARY_ASSET_HASH_MISMATCH: {rel}'])
    if path.suffix.lower() not in TEXT_SUFFIXES and rel != 'VERSION':
        return [f'UNSUPPORTED_TEXT: {rel}']
    try:
        content = path.read_text(encoding='utf-8')
    except (UnicodeError, OSError):
        return [f'TEXT_INVALID: {rel}']
    if '\0' in content:
        return [f'TEXT_INVALID: {rel}']
    problems = []
    for line_number, line in enumerate(content.splitlines(), 1):
        for label, pattern in LEAK_RULES:
            if pattern.search(line):
                # Do not repeat secret values or surrounding source lines in diagnostics.
                problems.append(f'PRIVACY: {rel}:{line_number}: {label}')
    return problems


def inventory(root):
    try:
        if (root / MANIFEST).is_symlink():
            raise ValueError()
        manifest = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
        files = manifest['files']
        if manifest['schema_version'] != 1 or not isinstance(files, list):
            raise ValueError()
        if any(not isinstance(p, str) or not p or '\\' in p or
               PurePosixPath(p).is_absolute() or '..' in PurePosixPath(p).parts or
               str(PurePosixPath(p)) != p or any(part.casefold() in RUNTIME_NAMES for part in PurePosixPath(p).parts) or any(ord(c) < 32 or c in ':<>|?*\"' for c in p) for p in files):
            raise ValueError()
        if len(files) != len({p.casefold() for p in files}) or not ESSENTIAL <= set(files):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise Blocked('MANIFEST_INVALID: release inventory missing or invalid') from None
    return set(files)


def config_template(root):
    path = root / 'scripts/config.example.json'
    if path.is_symlink() or not path.is_file():
        return ['CONFIG_TEMPLATE_INVALID']
    try:
        template = json.loads(path.read_text(encoding='utf-8'))
        if template.get('created_at') != '' or template.get('chats') != []:
            return ['CONFIG_TEMPLATE_NOT_EMPTY']
        for section in ('wechat', 'paths'):
            values = template[section]
            if not isinstance(values, dict) or not values or any(value != '' for value in values.values()):
                return ['CONFIG_TEMPLATE_NOT_EMPTY']
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return ['CONFIG_TEMPLATE_INVALID']
    return []


def third_party(root, files):
    problems = []
    try:
        document = json.loads((root / 'references/third-party.json').read_text(encoding='utf-8'))
        components = document['components']
        if document['schema_version'] != 1 or not isinstance(components, list):
            raise ValueError()
        if sorted(c['id'] for c in components) != ['vue', 'wcdb-key-tool']:
            raise ValueError()
        for component in components:
            hashes = component['sha256']
            if component['license'] != 'MIT' or component['license_file'] not in hashes:
                raise ValueError()
            if not isinstance(hashes, dict) or not hashes:
                raise ValueError()
            for rel, expected in hashes.items():
                if rel not in files or not re.fullmatch('[0-9a-f]{64}', expected):
                    raise ValueError()
                path = root / rel
                if path.is_symlink() or not path.is_file():
                    problems.append(f'THIRD_PARTY_FILE_MISSING: {rel}')
                elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    problems.append(f'THIRD_PARTY_HASH_MISMATCH: {rel}')
    except (OSError, ValueError, TypeError, KeyError):
        problems.append('THIRD_PARTY_INVALID')
    return problems


class AssetReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        key = 'href' if tag == 'link' else 'src'
        if tag in {'link', 'script', 'img', 'source'} and attributes.get(key):
            self.paths.append(attributes[key])


def references(root, files):
    problems = []
    for rel in sorted(files):
        path = root / rel
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix == '.md':
            links = re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text(encoding='utf-8'))
        elif rel == 'scripts/web/index.html':
            parser = AssetReferences()
            parser.feed(path.read_text(encoding='utf-8'))
            links = parser.paths
        else:
            continue
        for link in links:
            location = urlsplit(link.strip('<>'))
            if location.scheme or location.netloc or not location.path:
                continue
            local = unquote(location.path)
            target = root / 'scripts/web' / local.lstrip('/') if local.startswith('/') else path.parent / local
            target = target.resolve()
            if not target.is_relative_to(root.resolve()) or not target.is_file():
                # Do not reflect untrusted URI values in the output.
                problems.append(f'REFERENCE_MISSING: {rel}')
    return problems


def audit(root, files):
    problems = []
    actual = set()
    directories = {str(PurePosixPath(p).parent) for p in files}
    directories |= {str(p) for f in files for p in PurePosixPath(f).parents}
    for path in root.rglob('*'):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            problems.append(f'SYMLINK: {rel}')
        elif path.is_file():
            actual.add(rel)
            problems.extend(scan_text(path, rel))
            if rel not in files:
                problems.append(f'UNKNOWN_FILE: {rel}')
        elif path.is_dir() and rel not in directories:
            problems.append(f'UNKNOWN_DIRECTORY: {rel}')
        elif not path.is_dir():
            problems.append(f'UNSUPPORTED_ENTRY: {rel}')
    problems += [f'MISSING_FILE: {p}' for p in sorted(files - actual)]
    skill = root / 'SKILL.md'
    if skill.is_file() and not skill.is_symlink() and (root / 'VERSION').is_file() and not (root / 'VERSION').is_symlink():
        text = skill.read_text(encoding='utf-8')
        match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', text, re.S)
        pairs = re.findall(r'^(name|version|description):[ \t]*(.+)$', match[1], re.M) if match else []
        fields = dict(pairs)
        if len(pairs) != 3 or len(fields) != 3:
            problems.append('FRONTMATTER_INVALID')
        version = (root / 'VERSION').read_text(encoding='utf-8').strip()
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', version):
            problems.append('VERSION_INVALID')
        if fields.get('version', '').strip("\"' ") != version:
            problems.append('VERSION_MISMATCH: SKILL frontmatter and VERSION must agree')
        if fields.get('name') != NAME or not fields.get('description'):
            problems.append('FRONTMATTER_INVALID')
    if problems:
        return problems
    problems.extend(references(root, files))
    problems.extend(third_party(root, files))
    problems.extend(config_template(root))
    return problems


def file_hashes(root, files):
    return {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in sorted(files)}


def verify_zip(path, files, expected_hashes, expected_sha256=None):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha256 and digest != expected_sha256.lower():
        raise Blocked('ZIP_HASH_MISMATCH')
    with tempfile.TemporaryDirectory(prefix='daily-unzip-') as temp:
        expanded = Path(temp)
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            expected = {f'{NAME}/{rel}' for rel in files}
            if len(names) != len(set(names)) or set(names) != expected:
                raise Blocked('ZIP_INVENTORY_MISMATCH')
            if sum(m.file_size for m in members) > 64 * 1024 * 1024:
                raise Blocked('ZIP_TOO_LARGE')
            for member in members:
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode) or member.is_dir():
                    raise Blocked('ZIP_UNSUPPORTED_ENTRY')
                # Names already match the validated, exact inventory. No extractall traversal.
                target = expanded / member.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
        package = expanded / NAME
        if inventory(package) != files:
            raise Blocked('ZIP_MANIFEST_MISMATCH')
        problems = audit(package, files)
        if problems:
            raise Blocked('ZIP_EXTRACTED_CHECK_FAILED\n' + '\n'.join(problems))
        if file_hashes(package, files) != expected_hashes:
            raise Blocked('ZIP_CONTENT_MISMATCH')
        return {'sha256': digest, 'extracted_check_passed': True, 'files': len(files)}


def source_revision():
    try:
        revision = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                                  capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        dirty = bool(subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain'],
                                   capture_output=True, text=True, timeout=5, check=True).stdout.strip())
        return {'source_commit': revision, 'source_dirty': dirty}
    except (OSError, subprocess.SubprocessError):
        return {'source_commit': None, 'source_dirty': None}


def build(files, output):
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    output = (output or Path.cwd() / f'{NAME}-{version}-candidate.zip').resolve()
    receipt_path = output.with_suffix(output.suffix + '.json')
    if output.is_relative_to(ROOT) or output.exists() or receipt_path.exists():
        raise Blocked('OUTPUT_INVALID: choose a new path outside the Skill')
    created = []
    try:
        with tempfile.TemporaryDirectory(prefix='daily-stage-') as temp:
            stage = Path(temp) / NAME
            for rel in sorted(files):
                target = stage / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / rel, target)
            problems = audit(stage, files)
            if problems:
                raise Blocked('STAGED_CHECK_FAILED\n' + '\n'.join(problems))
            hashes = file_hashes(stage, files)
            candidate = Path(temp) / 'candidate.zip'
            with zipfile.ZipFile(candidate, 'x', zipfile.ZIP_DEFLATED) as archive:
                for rel in sorted(files):
                    info = zipfile.ZipInfo(f'{NAME}/{rel}', date_time=(2020, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, (stage / rel).read_bytes())
            verified = verify_zip(candidate, files, hashes)
            receipt = dict(kind='internal_candidate', version=version, release_tag=None,
                           windows_acceptance='not_verified', file_sha256=hashes,
                           **source_revision(), **verified)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('xb') as stream:
                created.append(output)
                stream.write(candidate.read_bytes())
            # Reopen the actual delivered bytes, not merely the temporary ZIP.
            verify_zip(output, files, hashes, verified['sha256'])
            with receipt_path.open('x', encoding='utf-8') as stream:
                created.append(receipt_path)
                json.dump(receipt, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            return dict(receipt, zip=str(output), receipt=str(receipt_path))
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def probe(command, timeout=15):
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout)
        return {'state': 'passed' if result.returncode == 0 else 'failed',
                'code': 'OK' if result.returncode == 0 else 'PROBE_FAILED'}
    except (OSError, subprocess.SubprocessError):
        return {'state': 'failed', 'code': 'PROBE_UNAVAILABLE'}


def capabilities(node, browser):
    required = {'python': {'state': 'passed' if sys.version_info >= (3, 11) else 'failed',
                           'version': '.'.join(map(str, sys.version_info[:3]))}}
    try:
        with sqlite3.connect(':memory:') as connection:
            connection.execute('create table capability(value text)')
            connection.execute('insert into capability values (?)', ('synthetic',))
            if connection.execute('select value from capability').fetchone() != ('synthetic',):
                raise RuntimeError('SQLite vector mismatch')
        required['sqlite'] = {'state': 'passed', 'version': sqlite3.sqlite_version}
    except (sqlite3.Error, RuntimeError):
        required['sqlite'] = {'state': 'failed', 'code': 'SQLITE_PROBE_FAILED'}
    # NIST SP 800-38A F.2.5/6 first AES-256-CBC block. Public test vector, no user keys.
    aes_program = """
import sys
sys.path.insert(0, sys.argv[1])
from safe_decrypt import aes_cbc_decrypt
key = bytes.fromhex('603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4')
iv = bytes.fromhex('000102030405060708090a0b0c0d0e0f')
ciphertext = bytes.fromhex('f58c4c04d6e5f1ba779eabfb5f7bfbd6')
if aes_cbc_decrypt(key, iv, ciphertext).hex() != '6bc1bee22e409f96e93d7e117393172a':
    raise RuntimeError('AES vector mismatch')
"""
    required['aes_cbc'] = probe([sys.executable, '-B', '-c', aes_program, str(ROOT / 'scripts/tools')])
    with tempfile.TemporaryDirectory(prefix='daily-capability-') as temp:
        folder = Path(temp)
        # Zstd frame containing a raw block with the known plaintext "hello".
        compressed = bytes.fromhex('28b52ffd200529000068656c6c6f')
        input_path, output_path = folder / 'input.bin', folder / 'output.bin'
        input_path.write_bytes(struct.pack('<I', len(compressed)) + compressed)
        node_result = probe([node, str(ROOT / 'scripts/tools/zstd_bridge.js'), str(input_path), str(output_path)])
        if node_result['state'] == 'passed' and (not output_path.exists() or output_path.read_bytes() != b'\x05\x00\x00\x00hello'):
            node_result = {'state': 'failed', 'code': 'ZSTD_VECTOR_MISMATCH'}
        png = {'state': 'not_tested', 'code': 'BROWSER_NOT_REQUESTED'}
        if browser:
            page, screenshot = folder / 'probe.html', folder / 'probe.png'
            page.write_text('<!doctype html><title>Capability probe</title><p>Synthetic page</p>', encoding='utf-8')
            png = probe([str(browser), '--headless', '--disable-gpu', '--no-first-run',
                         '--no-default-browser-check', f'--user-data-dir={folder / "profile"}',
                         f'--screenshot={screenshot}', '--window-size=320,240', page.as_uri()], timeout=25)
            if png['state'] == 'passed':
                data = screenshot.read_bytes() if screenshot.exists() else b''
                if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', data[16:24]) != (320, 240):
                    png = {'state': 'failed', 'code': 'PNG_NOT_PRODUCED'}
    pillow_program = """
import io
from PIL import Image
out = io.BytesIO()
Image.new('RGB', (2, 3)).save(out, format='PNG')
if Image.open(io.BytesIO(out.getvalue())).size != (2, 3):
    raise RuntimeError('PNG vector mismatch')
"""
    distributions = {}
    for name in ('cryptography', 'Pillow', 'pilk', 'silk-python', 'ctranslate2', 'faster-whisper', 'opencc-python-reimplemented'):
        try:
            distributions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            distributions[name] = None
    return {'required': required,
            'optional': {'node_zstd': node_result, 'browser_png': png,
                         'pillow': probe([sys.executable, '-B', '-c', pillow_program]),
                         'voice': {'state': 'not_tested', 'code': 'NO_MODEL_OR_AUDIO_EXERCISED'}},
            'installed_distributions': distributions,
            'windows_live_read': {'state': 'not_tested'},
            'workbuddy_schedule': {'state': 'not_tested'},
            'ready_for_windows_acceptance': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--build', action='store_true')
    mode.add_argument('--verify-zip', type=Path)
    mode.add_argument('--capabilities', action='store_true')
    parser.add_argument('--node', default='node', help='executable for optional Zstd capability probe')
    parser.add_argument('--browser', type=Path, help='explicit Chromium executable for optional PNG probe')
    parser.add_argument('--output', type=Path, help='new candidate ZIP outside the source package')
    parser.add_argument('--sha256', help='expected ZIP hash for --verify-zip')
    args = parser.parse_args()
    if args.output and not args.build:
        parser.error('--output requires --build')
    if args.sha256 and (not args.verify_zip or not re.fullmatch(r'[0-9a-fA-F]{64}', args.sha256)):
        parser.error('--sha256 requires --verify-zip and 64 hexadecimal characters')
    if args.browser and not args.capabilities:
        parser.error('--browser requires --capabilities')
    try:
        if args.capabilities:
            report = capabilities(args.node, args.browser)
            print(json.dumps(report))
            return 0 if all(p['state'] == 'passed' for p in report['required'].values()) else 1
        files = inventory(ROOT)
        problems = audit(ROOT, files)
        if problems:
            raise Blocked('\n'.join(problems))
        if args.verify_zip:
            print(json.dumps(verify_zip(args.verify_zip, files, file_hashes(ROOT, files), args.sha256)))
            return 0
        if args.build:
            result = build(files, args.output)
            print(json.dumps({k: v for k, v in result.items() if k != 'file_sha256'}))
        else:
            print('SOURCE_CHECK_PASSED: static release checks; no Windows acceptance implied')
        return 0
    except (Blocked, OSError, UnicodeError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        # Unexpected file contents and external tools must not echo private values.
        print(str(error) if isinstance(error, Blocked) else f'CHECK_FAILED: {type(error).__name__}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
