"""Read-only environment, configuration and snapshot diagnostics; never installs or extracts."""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'lib'))
sys.path.insert(0, os.path.join(BASE, 'tools'))
from wechat_data import capabilities, guard, readiness, settings


def check_keys(cfg):
    from safe_decrypt import verify_key
    source_dir = settings.get(cfg, 'wechat.db_dir')
    if not source_dir or not os.path.isabs(source_dir) or not os.path.isdir(source_dir):
        return {'available': False, 'count': None, 'valid': None}
    path = settings.keys_file(cfg)
    try:
        with open(path, encoding='utf-8') as source:
            keys = json.load(source)
        expected = guard.required_files(settings.get(cfg, 'wechat.db_dir') or '')
        found = {rel.replace('\\', '/'): info for rel, info in keys.items() if not rel.startswith('_')}
        required = expected | {rel for rel in found if guard.is_core(rel)}
        valid = 0
        for rel in required:
            if os.path.isabs(rel) or '..' in rel.split('/'):
                continue
            with open(os.path.join(settings.get(cfg, 'wechat.db_dir') or '', rel), 'rb') as source:
                if verify_key(bytes.fromhex(found[rel]['enc_key']), source.read(4096)):
                    valid += 1
        return {'available': bool(required) and valid == len(required), 'count': len(required), 'valid': valid}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {'available': False, 'count': None, 'valid': None}


def inspect(timezone=None, browser=None):
    state, cfg = readiness.snapshot()
    configured = state['configuration']['state'] == 'configured'
    if configured:
        try:
            cfg = settings.load()
        except settings.ConfigurationError:
            state['configuration']['state'] = 'needs_repair'
            configured = False
    zone = timezone or ((cfg or {}).get('compose') or {}).get('timezone')
    caps = capabilities.probe(zone, browser)
    report = {'schema_version': 1, 'configuration': state['configuration'],
              'capabilities': caps, 'reading': state['reading'], 'first_report': state['first_report'],
              'keys': None, 'coverage': None, 'diagnostics': [], 'followed_count': len(state['followed_chats'])}
    if configured:
        report['keys'] = check_keys(cfg)
        report['coverage'] = guard.coverage(settings.decrypted_dir(cfg))
        report['diagnostics'] = guard.wal_diagnostics(settings.decrypted_dir(cfg))
    if state['configuration']['state'] == 'needs_repair':
        code, error, action = 12, 'CONFIG_INVALID', 'repair_configuration_in_workbuddy'
    elif not configured:
        code, error, action = 11, 'NOT_CONFIGURED', 'initialize_in_workbuddy'
    elif not (cfg.get('wechat') or {}).get('confirmed_at'):
        code, error, action = 12, 'ACCOUNT_CONFIRMATION_REQUIRED', 'confirm_account_in_workbuddy'
    elif not capabilities.required_ready(caps):
        code, error, action = 10, 'ENVIRONMENT_NOT_READY', 'repair_environment_in_workbuddy'
    elif not report['keys']['available']:
        code, error, action = 14, 'KEYS_UNAVAILABLE', 'confirm_account_and_refresh_keys_in_workbuddy'
    elif not report['coverage']['complete']:
        code, error, action = 15, 'DECRYPTION_INCOMPLETE', 'decrypt_and_retry_in_workbuddy'
    elif not state['followed_chats']:
        code, error, action = 13, 'NO_FOLLOWED_GROUPS', 'select_groups_in_workbuddy'
    else:
        code, error, action = 0, None, 'collect_target_date_in_workbuddy'
    report.update(code=error, next_action=action, retryable=False)
    return code, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--timezone')
    parser.add_argument('--browser', help='Optional browser executable to probe')
    parser.add_argument('--capabilities-only', action='store_true')
    parser.add_argument('--fix', action='store_true', help='Deprecated; only reports explicit next steps')
    args = parser.parse_args()
    if args.capabilities_only:
        caps = capabilities.probe(args.timezone, args.browser)
        code, payload = (0 if capabilities.required_ready(caps) else 10), {'capabilities': caps}
    else:
        code, payload = inspect(args.timezone, args.browser)
    if args.fix:
        payload['repair'] = {'state': 'not_started', 'next_action': 'confirm_each_repair_in_workbuddy'}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print('环境检查（只读；配置、首报、宿主任务与真实触发分别验收）')
        for name, item in payload['capabilities'].items():
            print(f"{name}: {item['available']} {item.get('code') or ''} {item.get('next_action') or ''}")
        print(f"下一步：{payload.get('next_action') or '按能力缺口修复'}；返回码 {code}")
    return code


if __name__ == '__main__':
    sys.exit(main())
