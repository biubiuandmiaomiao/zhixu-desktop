"""Bounded verified HTTP ranges for large immutable public media resources."""
import http.client
import math
import re
import time


class _RangeBudgetExpired(ValueError):
    pass


class _RepresentationChanged(ValueError):
    pass


def download_budget(size):
    # Give large files a bounded budget at a 64 KiB/s target, never unlimited.
    return min(1800, max(600, 120 + math.ceil(size / 65536))) if size > 0 else 600


def download_ranges(urls, expected, partial, target, deadline, budget, chunk_bytes,
                    check, progress, open_stream, emit, transient_error):
    requests = retries = 0
    last_reason = 'connection'
    # The caller may add at most three full GETs when Range is unsupported.
    request_limit = 3 * math.ceil(expected / chunk_bytes)
    details = {'attempt': 0, 'expected_bytes': expected, 'received_bytes': 0, 'status': 0}

    def remaining():
        left = deadline - time.monotonic()
        if left <= 0:
            emit('download_failed', {**details, 'reason': 'deadline',
                 'budget_seconds': budget, 'elapsed_seconds': budget - left,
                 'request_count': requests, 'retry_count': retries})
            raise _RangeBudgetExpired('B站公开视频下载超时，可重试')
        return left

    # Never mix bytes between CDN representations. A new candidate starts at zero;
    # retries on the same exact URL retain only fully verified committed ranges.
    for candidate_attempt in range(3):
        check(); remaining()
        url = urls[candidate_attempt % len(urls)]
        offset, validator, chunks = 0, None, 0
        details = {'attempt': candidate_attempt + 1, 'expected_bytes': expected,
                   'received_bytes': 0, 'status': 0, 'budget_seconds': budget}
        emit('download_attempt', dict(details))
        progress(0)
        exhausted = False
        with partial.open('wb') as writer:
            while offset < expected:
                end = min(expected - 1, offset + chunk_bytes - 1)
                length = end - offset + 1
                for segment_attempt in range(3):
                    check(); remaining()
                    if requests >= request_limit:
                        emit('download_failed', {**details, 'reason': 'request_limit',
                             'request_count': requests, 'retry_count': retries})
                        raise ValueError('B站分段下载达到请求上限，可重试')
                    requests += 1
                    headers = {'Range': f'bytes={offset}-{end}'}
                    if validator and re.fullmatch(r'"[\x21\x23-\x7e]*"', validator):
                        headers['If-Range'] = validator
                    details.update(range_start=offset, range_end=end, committed_bytes=offset,
                                   received_bytes=offset, status=0, segment_attempt=segment_attempt + 1)
                    details.pop('header_bytes', None)
                    reason = 'connection'
                    try:
                        with open_stream(url, 'media', timeout=min(20, max(1, remaining())), headers=headers) as response:
                            status = getattr(response, 'status', 200)
                            details['status'] = status
                            if status == 200:
                                # Ignored Range or changed If-Range representation:
                                # discard this prefix, then use a new full-body GET.
                                progress(0)
                                return False
                            content_range = response.headers.get('Content-Range', '')
                            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', content_range) if isinstance(content_range, str) and len(content_range) < 128 else None
                            if status != 206 or not match or tuple(map(int, match.groups())) != (offset, end, expected):
                                raise ValueError('B站分段响应范围或完整大小不符，已停止下载')
                            if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                                raise ValueError('B站分段响应编码无效，已停止下载')
                            header = response.headers.get('Content-Length')
                            if header is not None:
                                if not re.fullmatch(r'[0-9]{1,20}', str(header)) or int(header) != length:
                                    raise ValueError('B站分段响应长度不符，已停止下载')
                                details['header_bytes'] = int(header)
                            etag = response.headers.get('ETag')
                            if etag is not None and (not isinstance(etag, str) or len(etag) > 512 or '\r' in etag or '\n' in etag):
                                raise ValueError('B站分段响应标识无效，已停止下载')
                            if offset and etag != validator:
                                if etag is None and 'If-Range' in headers:
                                    # RFC 9110 permits omitting redundant representation
                                    # headers after a matching strong If-Range condition.
                                    etag = validator
                                else:
                                    raise _RepresentationChanged('B站媒体版本标识发生变化，未混合不同版本')
                            buffer = bytearray()
                            while True:
                                check()
                                left = remaining()
                                sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                                if sock is not None:
                                    sock.settimeout(min(20, left))
                                try:
                                    data = getattr(response, 'read1', response.read)(min(256 * 1024, length + 1 - len(buffer)))
                                except (OSError, http.client.IncompleteRead):
                                    raise transient_error('B站分段下载连接中断，可重试') from None
                                if not data:
                                    break
                                buffer.extend(data)
                                details['received_bytes'] = offset + len(buffer)
                                if len(buffer) > length:
                                    raise ValueError('B站分段实际长度超过请求范围，已停止下载')
                            remaining(); check()
                            if len(buffer) != length:
                                reason = 'early_eof'
                                raise transient_error('B站分段下载不完整，可重试')
                        # Only this boundary can advance the durable prefix.
                        writer.write(buffer)
                        writer.flush()
                        offset += length
                        validator = etag
                        chunks += 1
                        details.update(received_bytes=offset, committed_bytes=offset)
                        progress(offset / expected)
                        break
                    except transient_error as exc:
                        retries += 1
                        last_reason = reason
                        details['status'] = getattr(exc, 'status', details['status'])
                        emit('download_retry', {**details, 'reason': reason,
                             'request_count': requests, 'retry_count': retries})
                        check(); remaining()
                        if segment_attempt == 2:
                            exhausted = True
                    except _RangeBudgetExpired:
                        raise
                    except _RepresentationChanged:
                        retries += 1
                        last_reason = 'representation_changed'
                        emit('download_retry', {**details, 'reason': last_reason,
                             'request_count': requests, 'retry_count': retries})
                        exhausted = True
                        break
                    except ValueError as exc:
                        emit('download_failed', {**details, 'reason': 'invalid_response',
                             'status': getattr(exc, 'status', details['status']),
                             'request_count': requests, 'retry_count': retries})
                        raise
                if exhausted:
                    break
        if not exhausted and offset == expected:
            check(); remaining()
            if partial.stat().st_size != expected:
                raise ValueError('B站完整媒体大小不符，已停止下载')
            partial.replace(target)
            progress(1)
            emit('download_completed', {**details, 'received_bytes': expected,
                 'committed_bytes': expected, 'range_chunks': chunks,
                 'request_count': requests, 'retry_count': retries})
            return True
    emit('download_failed', {**details, 'reason': last_reason,
         'request_count': requests, 'retry_count': retries})
    if last_reason == 'representation_changed':
        raise ValueError('B站媒体版本标识反复变化，未混合不同版本，请稍后重试')
    raise ValueError('B站分段下载重试后仍不完整，可重试')
