"""Release behavior through the public package CLI and extracted ZIP only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / 'skills/wechat-group-daily'


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='daily-package-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skill = self.root / 'wechat-group-daily'
        shutil.copytree(SKILL, self.skill, ignore=shutil.ignore_patterns('__pycache__'))
        # This release branch starts at T0. T1 is integrated by the controller.
        # A clearly synthetic module in temporary CLI copies tests packaging only.
        # Never replace real collection.py when running against the integrated tree.
        collection = self.skill / 'scripts/lib/wechat_data/collection.py'
        if not collection.exists():
            collection.write_text('# Synthetic packaging fixture; no collection implementation.\n',
                                  encoding='utf-8')
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                        WECHAT_DAILY_CONFIG=str(self.root / 'external/config.json'))

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(self.skill / 'scripts/tools/package.py'),
                               *map(str, args)], cwd=self.root, env=self.env,
                              capture_output=True, text=True, timeout=30)

    def test_missing_frontend_blocks_build(self):
        shutil.rmtree(self.skill / 'scripts/web')
        result = self.run_cli('--build')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('scripts/web/index.html', result.stdout)
        self.assertFalse(list(self.root.rglob('*.zip')))

    def test_inconsistent_versions_block_build(self):
        p = self.skill / 'SKILL.md'
        p.write_text(re.sub(r'^version:.*$', 'version: 0.0.0', p.read_text(encoding='utf-8'), flags=re.M), encoding='utf-8')
        result = self.run_cli('--build', '--output', self.root / 'candidate.zip')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('VERSION_MISMATCH', result.stdout)
        self.assertFalse((self.root / 'candidate.zip').exists())

    def align_test_versions(self):
        path = self.skill / 'SKILL.md'
        version = (self.skill / 'VERSION').read_text(encoding='utf-8').strip()
        path.write_text(re.sub(r'^version:.*$', f'version: {version}', path.read_text(encoding='utf-8'), flags=re.M), encoding='utf-8')

    def test_css_private_group_marker_blocks_and_is_not_echoed(self):
        self.align_test_versions()
        marker = '123456789012345' + '@chatroom'  # Synthetic, never a real chat.
        with (self.skill / 'scripts/web/app.css').open('a', encoding='utf-8') as output:
            output.write('\n/* ' + marker + ' */\n')
        result = self.run_cli('--build', '--output', self.root / 'candidate.zip')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('PRIVACY', result.stdout)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertFalse((self.root / 'candidate.zip').exists())

    def test_unknown_files_and_runtime_state_block_instead_of_being_silently_skipped(self):
        self.align_test_versions()
        for name in ('surprise.bin', 'scripts/config.json', 'scripts/web/note.html'):
            with self.subTest(name=name):
                path = self.skill / name
                path.write_text('{}', encoding='utf-8')
                result = self.run_cli('--build', '--output', self.root / 'candidate.zip')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('UNKNOWN_FILE', result.stdout)
                self.assertFalse((self.root / 'candidate.zip').exists())
                path.unlink()

    def test_html_and_whitelisted_svg_are_scanned(self):
        self.align_test_versions()
        for name in ('scripts/web/index.html', 'scripts/web/probe.svg'):
            with self.subTest(name=name):
                path = self.skill / name
                previous = path.read_bytes() if path.exists() else None
                manifest_path = self.skill / 'references/release-files.json'
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                if previous is None:
                    manifest['files'].append(name)
                    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
                path.write_text('<svg><!-- WECHAT_DAILY_' + 'SYNTHETIC_LEAK --></svg>', encoding='utf-8')
                result = self.run_cli('--build', '--output', self.root / 'candidate.zip')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('PRIVACY', result.stdout)
                if previous is not None:
                    path.write_bytes(previous)
                else:
                    path.unlink()
                    manifest['files'].remove(name)
                    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

    def test_candidate_is_rechecked_after_extracting_and_hash_is_reported(self):
        self.align_test_versions()  # Only this synthetic installed copy; source stays blocked.
        output = self.root / 'candidate.zip'
        result = self.run_cli('--build', '--output', output)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['kind'], 'internal_candidate')
        self.assertEqual(receipt['sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertTrue(receipt['extracted_check_passed'])
        with zipfile.ZipFile(output) as archive:
            archive.extractall(self.root / 'expanded')
        skill = self.root / 'expanded/wechat-group-daily'
        self.assertTrue((skill / 'scripts/web/vendor/vue.global.prod.js').is_file())
        self.assertFalse((skill / 'scripts/config.json').exists())
        self.assertFalse((self.root / 'external').exists())

    def test_capabilities_execute_known_vectors_without_initializing_user_state(self):
        result = self.run_cli('--capabilities', '--node', sys.executable)
        self.assertIn(result.returncode, (0, 1), result.stdout + result.stderr)
        report = json.loads(result.stdout)
        if report['required']['aes_cbc']['state'] == 'failed':
            self.assertEqual(result.returncode, 1)
        else:
            self.assertEqual(result.returncode, 0)
        self.assertEqual(report['required']['sqlite']['state'], 'passed')
        self.assertEqual(report['optional']['node_zstd']['state'], 'failed')
        self.assertEqual(report['optional']['voice']['state'], 'not_tested')
        self.assertEqual(report['windows_live_read']['state'], 'not_tested')
        self.assertFalse((self.root / 'external').exists())

    def test_broken_relative_reference_blocks_the_candidate(self):
        self.align_test_versions()
        with (self.skill / 'references/dependencies.md').open('a', encoding='utf-8') as stream:
            stream.write('\n[required guide](missing-guide.md)\n')
        result = self.run_cli('--build', '--output', self.root / 'candidate.zip')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('REFERENCE_MISSING', result.stdout)

    def test_changed_vendor_or_license_requires_new_source_review(self):
        self.align_test_versions()
        with (self.skill / 'licenses/vue-MIT.txt').open('a', encoding='utf-8') as stream:
            stream.write('\nmodified\n')
        result = self.run_cli('--build', '--output', self.root / 'candidate.zip')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('THIRD_PARTY_HASH_MISMATCH', result.stdout)

    def test_personal_values_in_example_config_block_even_without_an_id_pattern(self):
        self.align_test_versions()
        path = self.skill / 'scripts/config.example.json'
        config = json.loads(path.read_text(encoding='utf-8'))
        config['wechat']['account'] = 'SYNTHETIC-OWNER'
        path.write_text(json.dumps(config), encoding='utf-8')
        result = self.run_cli('--build', '--output', self.root / 'candidate.zip')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('CONFIG_TEMPLATE_NOT_EMPTY', result.stdout)
        self.assertNotIn('SYNTHETIC-OWNER', result.stdout)

    def test_zip_tamper_missing_file_and_traversal_are_rejected(self):
        self.align_test_versions()
        original = self.root / 'candidate.zip'
        built = self.run_cli('--build', '--output', original)
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        digest = json.loads(built.stdout)['sha256']
        verified = self.run_cli('--verify-zip', original, '--sha256', digest)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        with zipfile.ZipFile(original) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        for mode in ('modified', 'missing', 'traversal', 'duplicate'):
            with self.subTest(mode=mode):
                damaged = self.root / f'{mode}.zip'
                with zipfile.ZipFile(damaged, 'w') as archive:
                    for name, content in contents.items():
                        if mode == 'missing' and name.endswith('/scripts/web/index.html'):
                            continue
                        if mode == 'modified' and name.endswith('/scripts/web/app.css'):
                            content += b'\n/* benign modification */\n'
                        archive.writestr(name, content)
                    if mode == 'traversal':
                        archive.writestr('../escape.txt', b'synthetic')
                    if mode == 'duplicate':
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore', UserWarning)
                            name = 'wechat-group-daily/VERSION'
                            archive.writestr(name, contents[name])
                result = self.run_cli('--verify-zip', damaged)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('ZIP_', result.stdout)
                self.assertFalse((self.root / 'escape.txt').exists())
        mismatch = self.run_cli('--verify-zip', original, '--sha256', '0' * 64)
        self.assertEqual(mismatch.returncode, 1)
        self.assertIn('ZIP_HASH_MISMATCH', mismatch.stdout)

    def test_bad_text_and_symlinks_are_rejected_without_following_them(self):
        self.align_test_versions()
        path = self.skill / 'scripts/web/app.css'
        original = path.read_bytes()
        path.write_bytes(b'\xff\xfe')
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn('TEXT_INVALID', result.stdout)
        path.unlink()
        target = self.root / 'external-synthetic.css'
        target.write_bytes(original)
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('symlink unavailable for this test account')
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn('SYMLINK', result.stdout)

    def test_existing_output_is_not_replaced(self):
        self.align_test_versions()
        output = self.root / 'existing.zip'
        output.write_bytes(b'keep existing candidate')
        result = self.run_cli('--build', '--output', output)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(output.read_bytes(), b'keep existing candidate')

    def test_runtime_state_cannot_be_added_to_the_whitelist(self):
        self.align_test_versions()
        path = self.skill / 'scripts/config.json'
        path.write_text('{}', encoding='utf-8')
        manifest_path = self.skill / 'references/release-files.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['files'].append('scripts/config.json')
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        result = self.run_cli('--build', '--output', self.root / 'candidate.zip')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('MANIFEST_INVALID', result.stdout)


    @unittest.skipUnless(importlib.util.find_spec('PIL'), 'Pillow not installed in this interpreter')
    def test_installed_pillow_can_encode_and_decode_a_png(self):
        result = self.run_cli('--capabilities')
        self.assertIn(result.returncode, (0, 1), result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['optional']['pillow']['state'], 'passed')


    def test_missing_t1_collection_module_blocks_complete_asset_check(self):
        self.align_test_versions()
        (self.skill / 'scripts/lib/wechat_data/collection.py').unlink()
        result = self.run_cli('--build', '--output', self.root / 'candidate.zip')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('MISSING_FILE: scripts/lib/wechat_data/collection.py', result.stdout)
        self.assertFalse((self.root / 'candidate.zip').exists())

    def test_t1_collection_and_report_records_cannot_be_whitelisted(self):
        self.align_test_versions()
        manifest_path = self.skill / 'references/release-files.json'
        initial = manifest_path.read_text(encoding='utf-8')
        for directory in ('collections', 'report-records'):
            with self.subTest(directory=directory):
                relative = f'scripts/{directory}/2026-10-25/synthetic.json'
                path = self.skill / relative
                path.parent.mkdir(parents=True)
                path.write_text('{}', encoding='utf-8')
                manifest = json.loads(initial)
                manifest['files'].append(relative)
                manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
                result = self.run_cli('--build', '--output', self.root / 'candidate.zip')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('MANIFEST_INVALID', result.stdout)
                self.assertFalse((self.root / 'candidate.zip').exists())
                shutil.rmtree(self.skill / 'scripts' / directory)
                manifest_path.write_text(initial, encoding='utf-8')
