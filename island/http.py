"""HTTPS GET through WinRT HttpClient (Schannel + Windows trust store; OpenSSL/urllib misses servers that omit an intermediate)."""
import asyncio

UA = "DynamicIsland/0.1"


def get(url, headers=None, timeout=10):
    """Blocking GET for worker threads -> (status, headers, body). Raises OSError on transport failure or timeout."""
    from winrt.windows.foundation import Uri
    from winrt.windows.web.http import HttpClient, HttpMethod, HttpRequestMessage

    async def run():
        with HttpClient() as client:
            req = HttpRequestMessage(HttpMethod.get, Uri(url))
            for k, v in {"User-Agent": UA, **(headers or {})}.items():
                req.headers.append(k, v)
            resp = await client.send_request_async(req)  # cancelled with the task on timeout
            buf = await resp.content.read_as_buffer_async()
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            hdrs.update({k.lower(): v for k, v in resp.content.headers.items()})  # Expires is a content header
            return int(resp.status_code), hdrs, bytes(buf)
    try:
        return asyncio.run(asyncio.wait_for(run(), timeout))
    except asyncio.TimeoutError as e:
        raise OSError("timeout") from e
    except OSError:
        raise
    except Exception as e:  # COMError and friends
        raise OSError(type(e).__name__) from e
