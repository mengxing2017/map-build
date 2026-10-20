"""Validate the locked CLI capabilities and bounded build audit contract."""
import re
from huavd_map_build.production.south.port.routeweft import RouteWeftError


def capabilities(tool):
    value = tool.call('version', ['--json'], 10)
    required = {
        'commands': {'version', 'preflight', 'build', 'verify', 'inspect', 'nearest', 'route'},
        'dataset_formats': {1}, 'profiles': {'driving-v1'},
        'invalid_restriction_policies': {'reject', 'block_ways'},
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


def build_report(value, source_sha256, policy, *, manifest=None, review=None):
    report = value.get('report')
    if (not isinstance(report, dict) or report.get('valid') is not True
            or report.get('failure_code') is not None or report.get('policy') != policy
            or report.get('source_sha256') != source_sha256):
        raise RouteWeftError('invalid RouteWeft build report identity/status')
    counts = report.get('diagnostics')
    if not isinstance(counts, dict) or any(type(v) is not int or v < 0 for v in counts.values()):
        raise RouteWeftError('invalid report diagnostic counts')
    for key in ('nodes', 'edges', 'restrictions'):
        if type(report.get(key)) is not int or report[key] < (0 if key == 'restrictions' else 1):
            raise RouteWeftError(f'invalid report {key}')
    if manifest is not None and any(report.get(k) != manifest.get(k) for k in (
            'source_sha256', 'source_snapshot', 'nodes', 'edges', 'restrictions', 'diagnostics')):
        raise RouteWeftError('build report/manifest mismatch')
    blocked, diagnostics = report.get('blocked_way_ids'), report.get('restriction_diagnostics')
    if (not isinstance(blocked, list) or len(blocked) > 2_000_000
            or any(type(v) is not int for v in blocked) or len(set(blocked)) != len(blocked)
            or not isinstance(diagnostics, list) or len(diagnostics) > 256):
        raise RouteWeftError('invalid restriction audit')
    codes = {'MissingVia', 'MissingFromTo', 'MissingReference', 'InvalidMemberType',
             'UnsupportedMultiplicity', 'UnsupportedViaShape', 'UnsupportedRestriction',
             'UnresolvedRestriction', 'RestrictionLimitExceeded'}
    observed = []
    for item in diagnostics:
        if (not isinstance(item, dict) or type(item.get('relation_id')) is not int
                or item.get('code') not in codes or item.get('action') != 'blocked_ways'
                or item.get('members_truncated') is not False
                or not isinstance(item.get('members'), list) or len(item['members']) > 256
                or not isinstance(item.get('tags'), dict)):
            raise RouteWeftError('invalid or incomplete restriction diagnostic')
        observed.append({'relation_id': item['relation_id'], 'code': item['code']})
    if policy == 'reject' and (blocked or diagnostics):
        raise RouteWeftError('strict build contains blocked restrictions')
    if policy == 'block_ways':
        if (not review or sorted(blocked) != sorted(review['blocked_way_ids'])
                or sorted(observed, key=lambda x: (x['relation_id'], x['code'])) != sorted(
                    review['diagnostics'], key=lambda x: (x['relation_id'], x['code']))):
            raise RouteWeftError('restriction audit differs from reviewed policy')
    return report
