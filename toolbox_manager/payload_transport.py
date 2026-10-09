"""Bounded local payload transport; file references never relax workflow policy."""
import hashlib
import json

MCP_INLINE_BYTES = 1024 * 1024
RESULT_FILE_BYTES = 16 * 1024 * 1024
WORKER_BYTES = 32 * 1024 * 1024
FILE_HINT = ('Do not retry the same inline payload. Save only the result object as UTF-8 JSON '
             'inside the authorized project, then call rebuild_submit or rebuild_validate_response '
             'with result_file and result_sha256 instead of result. Keep task_id, token and '
             'base_revision unchanged. No geometry simplification is required.')


class PayloadTooLarge(ValueError):
    code = 'payload_too_large'
    hint = FILE_HINT


def read_json_file(path, expected_sha256=None):
    with path.open('rb') as handle:
        raw = handle.read(RESULT_FILE_BYTES + 1)
    if len(raw) > RESULT_FILE_BYTES:
        raise PayloadTooLarge('Response file exceeds the 16 MiB local file limit; not submitted')
    if expected_sha256 and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Result file SHA-256 changed; verify the authored file before submitting')
    result = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(result, dict):
        raise ValueError('Response file must contain a JSON object')
    return result


def encode_worker(envelope):
    raw = json.dumps(envelope, ensure_ascii=False, allow_nan=False)
    if len(raw.encode('utf-8')) > WORKER_BYTES:
        raise PayloadTooLarge('Managed request exceeds the 32 MiB internal limit; not dispatched')
    return raw


def oversized_rpc(line):
    """Return a correlated rejection when possible, without echoing payloads."""
    size = len(line.encode('utf-8'))
    if size <= MCP_INLINE_BYTES:
        return None
    rid = None
    tool = None
    if size <= WORKER_BYTES:
        try:
            request = json.loads(line)
            if isinstance(request, dict) and isinstance(request.get('id'), (str, int)):
                rid = request['id']
            if isinstance(request, dict) and isinstance(request.get('params'), dict):
                tool = request['params'].get('name')
        except ValueError:
            pass
    return {'jsonrpc': '2.0', 'id': rid, 'error': {
        'code': -32003, 'message': 'MCP inline request exceeds 1 MiB; request was not dispatched',
        'data': {'code': 'payload_too_large', 'dispatched': False, 'request_bytes': size,
                 'limit_bytes': MCP_INLINE_BYTES, 'next_action': FILE_HINT if tool in {
                     'rebuild_submit', 'rebuild_validate_response'} else
                 'Do not resend the same payload. Inspect this tool contract for a supported file input '
                 'or its managed CLI request-file entry. Keep project permissions and task identity.'}}}
