"""Configure one confirmed account transactionally; first report and scheduling are separate."""
import argparse
import copy
from datetime import date, datetime, timedelta, timezone
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'lib'))
from wechat_data import ChatResolver, archive, capabilities, desktop, guard, settings


class SetupFailure(Exception):
    def __init__(self, code, action, *, candidates=None, retryable=False):
        self.code, self.action = code, action
        self.candidates, self.retryable = candidates, retryable


def emit(**payload):
    print(json.dumps({'schema_version': 1, **payload}, ensure_ascii=False))


def ask(prompt, default=None):
    if not sys.stdin.isatty():
        return None
    try:
        value = input(prompt).strip()
        return value or default
    except EOFError:
        return None


def digest_config():
    return hashlib.sha256(Path(settings.CONFIG_PATH).read_bytes()).hexdigest() if settings.exists() else None


def progress_path():
    return settings.external_path(settings.CONFIG_PATH + '.onboarding.json')


def detect_accounts():
    directory = Path(os.environ.get('APPDATA', '')) / 'Tencent/xwechat/config'
    roots, accounts = [], []
    for path in directory.glob('*.ini') if directory.is_dir() else []:
        for encoding in ('utf-8', 'gbk'):
            try:
                root = path.read_text(encoding=encoding).strip()
                if os.path.isdir(root):
                    roots.append(root)
                break
            except (UnicodeError, OSError):
                continue
    for root in dict.fromkeys(roots):
        for path in Path(root).glob('xwechat_files/*/db_storage'):
            if path.is_dir():
                accounts.append({'account': path.parent.name, 'db_dir': str(path.resolve()), 'root': root})
    return accounts


def select_account(args, old):
    accounts = ([{'account': Path(args.db_dir).resolve().parent.name,
                  'db_dir': str(Path(args.db_dir).resolve()), 'root': str(Path(args.db_dir).resolve().parent.parent)}]
                if args.db_dir else detect_accounts())
    if not accounts:
        raise SetupFailure('ACCOUNT_NOT_FOUND', 'locate_wechat_account_in_workbuddy')
    token = args.account
    previous = (old or {}).get('wechat') or {}
    if not token and len(accounts) == 1 and previous.get('account') == accounts[0]['account'] and previous.get('confirmed_at'):
        token = previous['account']
    if not token:
        emit(stage='confirm_account', candidates=accounts)
        token = ask('确认账号（输入完整账号 ID）: ', accounts[0]['account'] if len(accounts) == 1 else None)
    hits = [a for a in accounts if a['account'] == token]
    if not hits:
        raise SetupFailure('ACCOUNT_SELECTION_REQUIRED', 'confirm_account_in_workbuddy', candidates=accounts)
    account = hits[0]
    if not Path(account['db_dir']).is_dir():
        raise SetupFailure('ACCOUNT_NOT_FOUND', 'locate_wechat_account_in_workbuddy')
    if previous.get('account') and (previous['account'] != account['account'] or
                                   os.path.realpath(previous.get('db_dir', '')) != os.path.realpath(account['db_dir'])):
        raise SetupFailure('ACCOUNT_BINDING_CONFLICT', 'use_separate_configuration_for_other_account')
    return account


def decrypt_candidate(candidate, account, old):
    keys = Path(settings.keys_file(candidate))
    keys.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if old and (old.get('wechat') or {}).get('account') == account['account']:
        previous = Path(settings.keys_file(old))
        if previous.is_file() and not keys.exists():
            shutil.copy2(previous, keys)
    if not keys.is_file():
        extracted = subprocess.run([sys.executable, '-B', str(BASE / 'tools/wcdb_key_tool_windows.py'),
                                    'extract', '--db-dir', account['db_dir'], '--output', str(keys)],
                                   capture_output=True, text=True, timeout=180)
        if extracted.returncode or not keys.is_file():
            raise SetupFailure('KEY_EXTRACTION_FAILED', 'login_confirm_account_and_retry', retryable=True)
    keys.chmod(0o600)
    decrypted = subprocess.run([sys.executable, '-B', str(BASE / 'tools/safe_decrypt.py'),
                                '--db-dir', account['db_dir'], '--keys', str(keys),
                                '--output', settings.decrypted_dir(candidate)],
                               capture_output=True, text=True, timeout=600)
    if decrypted.returncode or not guard.coverage(settings.decrypted_dir(candidate))['complete']:
        raise SetupFailure('DECRYPTION_INCOMPLETE', 'decrypt_and_retry_in_workbuddy', retryable=True)


def groups_from(candidate, tokens):
    resolver = ChatResolver(settings.decrypted_dir(candidate))
    groups = resolver.groups()
    if not tokens:
        raise SetupFailure('GROUP_SELECTION_REQUIRED', 'select_group_ids_in_workbuddy',
                           candidates=[{'username': c.username, 'name': c.name} for c in groups])
    picked = {}
    for token in tokens.replace('，', ',').split(','):
        token = token.strip()
        exact_id = [c for c in groups if c.username == token]
        exact_name = [c for c in groups if c.name == token]
        hits = exact_id or exact_name or resolver.search(token, kind='group')
        if len(hits) != 1:
            raise SetupFailure('AMBIGUOUS_GROUP' if hits else 'GROUP_NOT_FOUND',
                               'select_group_ids_in_workbuddy',
                               candidates=[{'username': c.username, 'name': c.name} for c in hits])
        picked[hits[0].username] = hits[0]
    return list(picked.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auto', action='store_true', help='Accept external default root; account/groups still require explicit selection')
    for name in ('db-dir', 'groups', 'account', 'root', 'timezone', 'effective-from', 'time', 'resume', 'migrate-from'):
        parser.add_argument('--' + name)
    parser.add_argument('--list-accounts', action='store_true')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    session = None
    try:
        if args.list_accounts:
            emit(stage='confirm_account', candidates=detect_accounts())
            return 0
        settings.external_path(settings.CONFIG_PATH)
        if args.status:
            progress = archive.collection.read_record(progress_path())
            emit(stage=progress.get('stage', 'not_started'), code=progress.get('last_error'), resume_token=progress.get('token'))
            return 0
        old = settings.load() if settings.exists() else None
        if args.resume:
            session = archive.collection.read_record(progress_path())
            if session.get('token') != args.resume:
                raise SetupFailure('RESUME_NOT_FOUND', 'restart_setup_in_workbuddy')
            expected_hash = session.get('committed_hash') if session.get('stage') == 'configuration_saved' else session.get('old_hash')
            if digest_config() != expected_hash:
                raise SetupFailure('CONFIGURATION_CHANGED', 'review_configuration_before_resuming')
            if session.get('stage') == 'configuration_saved':
                emit(stage='configuration_saved', resume_token=session['token'], first_report='not_observed',
                     schedule='not_observed', desktop_shortcut=desktop.install_shortcut(settings.CONFIG_PATH))
                return 0
            candidate, account = session['candidate'], session['account']
        else:
            legacy = None
            if args.migrate_from:
                with open(args.migrate_from, encoding='utf-8') as source:
                    legacy = json.load(source)
                if not isinstance(legacy, dict):
                    raise SetupFailure('MIGRATION_SOURCE_INVALID', 'select_valid_legacy_configuration')
            account = select_account(args, old)
            candidate = copy.deepcopy(old) if old else settings.default_config()
            zone_name = args.timezone or (candidate.get('compose') or {}).get('timezone')
            if not zone_name:
                zone_name = ask('确认 IANA 时区（例如 Asia/Shanghai）: ')
            caps = capabilities.probe(zone_name)
            if not capabilities.required_ready(caps):
                emit(stage='environment', code='ENVIRONMENT_NOT_READY', capabilities=caps,
                     retryable=False, next_action='repair_environment_in_workbuddy')
                return 10
            root = args.root or ((old or {}).get('paths') or {}).get('root')
            if not root:
                default = settings.default_data_root()
                root = default if args.auto else ask(f'数据总目录（回车={default}）: ', default)
            root = settings.external_path(os.path.abspath(root)) if root else None
            if not root:
                raise SetupFailure('DATA_ROOT_REQUIRED', 'confirm_external_data_root')
            source_root = os.path.realpath(account['db_dir'])
            if os.path.commonpath((source_root, os.path.realpath(root))) == source_root:
                raise SetupFailure('UNSAFE_DATA_ROOT', 'select_directory_outside_wechat_databases')
            token = uuid.uuid4().hex
            stage = Path(root) / '.onboarding' / token
            candidate['paths'] = {'root': root, 'data': str(Path(root) / 'data'),
                                  'reports': str(Path(root) / 'reports'), 'logs': str(Path(root) / 'logs'),
                                  'decrypted': str(stage / 'decrypted'), 'secrets': str(stage / 'secrets')}
            candidate['wechat'] = {'account': account['account'], 'db_dir': account['db_dir'], 'data_root': account['root'], 'confirmed_at': datetime.now(timezone.utc).isoformat()}
            candidate['compose']['timezone'] = zone_name
            if args.time:
                if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', args.time):
                    raise SetupFailure('INVALID_TRIGGER_TIME', 'confirm_trigger_time')
                candidate['compose']['time'] = args.time
            session = {'token': token, 'stage': 'decrypting', 'candidate': candidate, 'account': account,
                       'old_hash': digest_config(), 'effective_from': args.effective_from}
            stage.mkdir(parents=True, exist_ok=True, mode=0o700)
            if legacy is not None:
                if (legacy.get('wechat') or {}).get('account') != account['account']:
                    raise SetupFailure('MIGRATION_ACCOUNT_CONFLICT', 'confirm_matching_legacy_account')
                shutil.copy2(args.migrate_from, stage / 'legacy-config.backup.json')
                for key in ('data', 'reports'):
                    previous = (legacy.get('paths') or {}).get(key)
                    if previous and Path(previous).is_dir():
                        target = stage / ('imported-' + key)
                        shutil.copytree(previous, target)
                        candidate['paths'][key] = str(target)
            archive._atomic_write(progress_path(), session)
        caps = capabilities.probe(candidate['compose']['timezone'])
        if not capabilities.required_ready(caps):
            raise SetupFailure('ENVIRONMENT_NOT_READY', 'repair_environment_in_workbuddy')
        if session['stage'] not in ('selecting_groups', 'configuration_saved'):
            decrypt_candidate(candidate, account, old)
            session['stage'] = 'selecting_groups'
            archive._atomic_write(progress_path(), session)
        if not guard.coverage(settings.decrypted_dir(candidate))['complete']:
            raise SetupFailure('DECRYPTION_INCOMPLETE', 'decrypt_and_retry_in_workbuddy', retryable=True)
        picked = groups_from(candidate, args.groups)
        previous = {c['username']: c for c in (old or {}).get('chats', [])}
        zone = timezone.utc if candidate['compose']['timezone'] == 'UTC' else ZoneInfo(candidate['compose']['timezone'])
        yesterday = (datetime.now(zone).date() - timedelta(days=1)).isoformat()
        effective = args.effective_from or session.get('effective_from')
        if any(c.username not in previous or not previous[c.username].get('daily', True) for c in picked) and not effective:
            effective = ask(f'确认关注生效日（回车={yesterday}）: ', yesterday)
            if not effective:
                raise SetupFailure('EFFECTIVE_DATE_REQUIRED', 'confirm_follow_effective_date')
        if effective and date.fromisoformat(effective).isoformat() != effective:
            raise SetupFailure('INVALID_EFFECTIVE_DATE', 'confirm_follow_effective_date')
        selected = []
        for chat in picked:
            item = dict(previous.get(chat.username) or {}, username=chat.username, name=chat.name, kind='group', daily=True)
            if effective and (chat.username not in previous or not previous[chat.username].get('daily', True) or args.effective_from):
                item['effective_from'] = effective
            selected.append(item)
        candidate['chats'] = selected
        lock_path = settings.CONFIG_PATH + '.setup.lock'
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise SetupFailure('SETUP_COMMIT_BUSY', 'retry_setup_commit_in_workbuddy', retryable=True)
        try:
            os.close(descriptor)
            if digest_config() != session['old_hash']:
                raise SetupFailure('CONFIGURATION_CHANGED', 'review_configuration_before_resuming')
            settings.ensure_dirs(candidate)
            settings.save(candidate)
        finally:
            os.remove(lock_path)
        session.update(stage='configuration_saved', committed_hash=digest_config())
        archive._atomic_write(progress_path(), session)
        emit(stage='configuration_saved', resume_token=session['token'], first_report='not_observed',
             schedule='not_observed', desktop_shortcut=desktop.install_shortcut(settings.CONFIG_PATH),
             diagnostics=guard.wal_diagnostics(settings.decrypted_dir(candidate)),
             next_action='write_check_render_and_open_sample_in_workbuddy')
        return 0
    except SetupFailure as error:
        if session and session.get('stage') != 'configuration_saved':
            session['last_error'] = error.code
            archive._atomic_write(progress_path(), session)
        emit(stage=(session or {}).get('stage', 'confirmation'), code=error.code, retryable=error.retryable,
             next_action=error.action, candidates=error.candidates, resume_token=(session or {}).get('token'))
        return 5 if error.code == 'DECRYPTION_INCOMPLETE' else 2
    except (settings.ConfigurationError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        emit(stage=(session or {}).get('stage', 'configuration'), code='CONFIG_INVALID' if session is None else 'SETUP_FAILED',
             retryable=False, next_action='repair_configuration_or_resume_in_workbuddy',
             resume_token=(session or {}).get('token'))
        return 6


if __name__ == '__main__':
    sys.exit(main())
