"""Serve protected media files with HTTP Range support, so audio and video can seek (iOS requires it)."""

import mimetypes
import re

from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
CHUNK = 64 * 1024


def _iter_range(handle, start, length):
    handle.seek(start)
    remaining = length
    try:
        while remaining > 0:
            data = handle.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data
    finally:
        handle.close()


def ranged_file_response(request, field_file, download_name=None, as_attachment=False):
    if not field_file:
        raise Http404("No file.")
    try:
        size = field_file.size
        handle = field_file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("The file is missing from storage.")
    content_type = mimetypes.guess_type(field_file.name)[0] or "application/octet-stream"
    name = download_name or field_file.name.rsplit("/", 1)[-1]
    match = RANGE_RE.match(request.META.get("HTTP_RANGE", "").strip())
    if match and (match.group(1) or match.group(2)):
        if match.group(1):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
        else:  # suffix range: last N bytes
            start = max(0, size - int(match.group(2)))
            end = size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            handle.close()
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        length = end - start + 1
        response = StreamingHttpResponse(_iter_range(handle, start, length), status=206, content_type=content_type)
        response["Content-Length"] = str(length)
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    else:
        response = FileResponse(handle, content_type=content_type, as_attachment=as_attachment, filename=name)
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, max-age=3600"
    return response
