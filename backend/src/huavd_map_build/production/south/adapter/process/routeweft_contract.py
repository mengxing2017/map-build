"""Validate the locked CLI capabilities and bounded build audit contract."""
import re
import math
import json
from huavd_map_build.production.south.port.routeweft import RouteWeftError


AUDIT_LIMITS = {'max_restriction_diagnostics': ('max_records', 32768),
                'max_restriction_audit_bytes': ('max_bytes', 16 * 1024**2),
                'max_blockways_attempts': ('max_blockways_attempts', 257)}


def restriction_audit_summary(report, diagnostics):
    """Validate new summaries without trusting their declared resource bounds."""
    summary = report.get('restriction_audit')
    if summary is None:
        # Legacy reports remain readable, within the original bound only.
        if len(diagnostics) > 256:
            raise RouteWeftError('missing restriction audit summary')
        return None
    if not isinstance(summary, dict):
        raise RouteWeftError('invalid restriction audit summary')
    limits = summary.get('limits')
    bounds = {'max_diagnostics': 32768, 'max_audit_bytes': 16 * 1024**2,
              'max_blockways_attempts': 257}
    if not isinstance(limits, dict) or any(
            type(limits.get(k)) is not int or not 0 < limits[k] <= bound
            for k, bound in bounds.items()):
        raise RouteWeftError('invalid restriction audit limits')
    for key in ('attempt', 'attempts_completed', 'records_observed', 'records_retained',
                'retained_bytes', 'retained_memory_bytes'):
        if type(summary.get(key)) is not int or summary[key] < 0:
            raise RouteWeftError('invalid restriction audit counters')
    if (summary.get('scan_complete') is not True or summary.get('truncated') is not False
            or not 0 < summary['attempt'] <= limits['max_blockways_attempts']
            or summary['attempts_completed'] != summary['attempt']
            or summary['records_observed'] != len(diagnostics)
            or summary['records_retained'] != len(diagnostics)
            or len(diagnostics) > limits['max_diagnostics']
            or summary['retained_memory_bytes'] > 64 * 1024**2):
        raise RouteWeftError('incomplete or over-budget restriction audit')
    try:
        size = sum(len(json.dumps(item, ensure_ascii=False, separators=(',', ':'),
                                  allow_nan=False).encode('utf-8')) for item in diagnostics)
    except (TypeError, ValueError, UnicodeError) as error:
        raise RouteWeftError('invalid restriction audit serialization') from error
    if size != summary['retained_bytes'] or size > limits['max_audit_bytes']:
        raise RouteWeftError('restriction audit byte count mismatch')
    return summary


def capabilities(tool):
    value = tool.call('version', ['--json'], 10)
    required = {
        'commands': {'version', 'preflight', 'build', 'verify', 'inspect', 'nearest', 'route'},
        'dataset_formats': {1}, 'profiles': {'driving-v1'},
        'invalid_restriction_policies': {'reject', 'block_ways'},
        'invalid_maxspeed_policies': {'reject', 'use_default'},
    }
    if type(value.get('cli_schema')) is not int or value['cli_schema'] != 1:
        raise RouteWeftError('incompatible RouteWeft CLI capabilities')
    if not isinstance(value.get('version'), str) or not value['version']:
        raise RouteWeftError('missing RouteWeft version')
    for key, expected in required.items():
        actual = value.get(key)
        if (not isinstance(actual, list) or any(type(v) is not type(next(iter(expected))) for v in actual)
                or not expected.issubset(actual)):
            raise RouteWeftError(f'incompatible RouteWeft capability: {key}')
    build = value.get('build')
    if build is None:
        if getattr(tool, 'require_build_identity', False):
            raise RouteWeftError('RouteWeft is missing embedded build identity; reinstall the locked tool')
    else:
        if (not isinstance(build, dict)
                or not isinstance(build.get('git_commit'), str)
                or not re.fullmatch('[0-9a-f]{40}', build['git_commit'])
                or build.get('source_dirty') is not False
                or build.get('release_eligible') is not True
                or build.get('source_identity_kind') not in ('git', 'git-archive', 'provided')
                or any(not isinstance(build.get(key), str) or not build[key]
                       for key in ('target', 'profile', 'rustc'))):
            raise RouteWeftError('RouteWeft embedded build identity is invalid or not release eligible')
        expected_commit = tool.identity.get('commit')
        if expected_commit is not None and build['git_commit'] != expected_commit:
            raise RouteWeftError('RouteWeft embedded commit does not match tool lock/receipt')
    return value


def build_report(value, source_sha256, policy, *, manifest=None, review=None, maxspeed_policy="reject"):
    report = value.get('report')
    if (not isinstance(report, dict) or report.get('valid') is not True
            or report.get('failure_code') is not None or report.get('policy') != policy
            or report.get('source_sha256') != source_sha256):
        raise RouteWeftError('invalid RouteWeft build report identity/status')
    counts = report.get('diagnostics')
    if not isinstance(counts, dict) or any(type(v) is not int or v < 0 for v in counts.values()):
        raise RouteWeftError('invalid report diagnostic counts')
    maxspeed_audit(report, maxspeed_policy)
    for key in ('nodes', 'edges', 'restrictions'):
        if type(report.get(key)) is not int or report[key] < (0 if key == 'restrictions' else 1):
            raise RouteWeftError(f'invalid report {key}')
    if manifest is not None and any(report.get(k) != manifest.get(k) for k in (
            'source_sha256', 'source_snapshot', 'nodes', 'edges', 'restrictions', 'diagnostics')):
        raise RouteWeftError('build report/manifest mismatch')
    blocked, diagnostics = report.get('blocked_way_ids'), report.get('restriction_diagnostics')
    if (not isinstance(blocked, list) or len(blocked) > 2_000_000
            or any(type(v) is not int for v in blocked) or len(set(blocked)) != len(blocked)
            or not isinstance(diagnostics, list) or len(diagnostics) > 32768):
        raise RouteWeftError('invalid restriction audit')
    summary = restriction_audit_summary(report, diagnostics)
    codes = {'MissingVia', 'MissingFromTo', 'MissingReference', 'InvalidMemberType',
             'UnsupportedMultiplicity', 'UnsupportedViaShape', 'UnsupportedRestriction',
             'UnresolvedRestriction', 'RestrictionLimitExceeded'}
    observed = []
    review_attempts = review is not None and any('attempt' in d for d in review['diagnostics'])
    relation_ids, member_ways = set(), set()
    previous = None
    for item in diagnostics:
        if (not isinstance(item, dict) or type(item.get('relation_id')) is not int
                or item.get('code') not in codes or item.get('action') != 'blocked_ways'
                or item.get('members_truncated') is not False
                or not isinstance(item.get('members'), list) or len(item['members']) > 256
                or not isinstance(item.get('tags'), dict)):
            raise RouteWeftError('invalid or incomplete restriction diagnostic')
        identity = item['relation_id']
        if summary is not None:
            attempt = item.get('attempt')
            if type(attempt) is not int or not 0 < attempt <= summary['attempt']:
                raise RouteWeftError('invalid restriction diagnostic attempt')
            identity = (attempt, item['relation_id'])
            if previous is not None and identity <= previous:
                raise RouteWeftError('unordered restriction diagnostics')
            previous = identity
        if identity in relation_ids:
            raise RouteWeftError('duplicate restriction diagnostic')
        relation_ids.add(identity)
        for member in item['members']:
            if (not isinstance(member, dict) or type(member.get('id')) is not int
                    or member.get('kind') not in ('node', 'way', 'relation', 'unknown')
                    or not isinstance(member.get('role'), str)):
                raise RouteWeftError('invalid restriction member')
            if member['kind'] == 'way':
                member_ways.add(member['id'])
        entry = {'relation_id': item['relation_id'], 'code': item['code']}
        if review_attempts:
            entry['attempt'] = item.get('attempt')
        observed.append(entry)
    if (counts.get('invalid_restrictions_blocked', 0) != len(diagnostics)
            or counts.get('invalid_restriction_ways_blocked', 0) != len(blocked)):
        raise RouteWeftError('restriction audit count mismatch')
    # Missing source members need not be blocked, but every exclusion must have evidence.
    if not set(blocked).issubset(member_ways) or (diagnostics and not blocked):
        raise RouteWeftError('restriction exclusions lack member evidence')
    if policy == 'reject' and (blocked or diagnostics):
        raise RouteWeftError('strict build contains blocked restrictions')
    if policy == 'block_ways' and review is not None:
        if (sorted(blocked) != sorted(review['blocked_way_ids'])
                or sorted(observed, key=lambda x: (x.get('attempt', 0), x['relation_id'], x['code'])) != sorted(
                    review['diagnostics'], key=lambda x: (x.get('attempt', 0), x['relation_id'], x['code']))):
            raise RouteWeftError('restriction audit differs from reviewed policy')
    return report


def maxspeed_audit(report, policy):
    """Require complete bounded successful speed audit and matching counters."""
    if policy not in ('reject', 'use_default') or report.get('maxspeed_policy') != policy:
        raise RouteWeftError('maxspeed report policy mismatch')
    entries = report.get('maxspeed_diagnostics')
    counts = report['diagnostics']
    if not isinstance(entries, list) or len(entries) > 256:
        raise RouteWeftError('missing or invalid maxspeed diagnostics')
    if (counts.get('maxspeed_policy_use_default', 0) != (1 if policy == 'use_default' else 0)
            or counts.get('maxspeed_fallback_values', 0) != len(entries)
            or (policy == 'reject' and entries)):
        raise RouteWeftError('maxspeed audit count/policy mismatch')
    seen, size = set(), 0
    for entry in entries:
        if (not isinstance(entry, dict) or type(entry.get('way_id')) is not int
                or entry.get('field') not in ('maxspeed', 'maxspeed:forward', 'maxspeed:backward')
                or not isinstance(entry.get('value'), str) or not entry['value'].strip()
                or entry.get('action') != 'use_default'
                or type(entry.get('effective_kmh')) not in (int, float)
                or not math.isfinite(entry['effective_kmh']) or not 0 < entry['effective_kmh'] <= 300):
            raise RouteWeftError('invalid maxspeed diagnostic')
        identity = (entry['way_id'], entry['field'])
        if identity in seen:
            raise RouteWeftError('duplicate maxspeed diagnostic')
        seen.add(identity)
        size += len(entry['field'].encode('utf-8')) + len(entry['value'].encode('utf-8')) + 128
        if size > 64 * 1024:
            raise RouteWeftError('maxspeed diagnostic byte limit exceeded')
