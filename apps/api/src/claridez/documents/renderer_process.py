from __future__ import annotations

import resource
import sys

from .assets import DOCUMENT_CSS, WORDMARK


def _fetcher(url: str, *_args: object, **_kwargs: object) -> dict[str, object]:
    from weasyprint.urls import FatalURLFetchingError  # type: ignore[import-untyped]

    if url == "claridez-asset:wordmark":
        return {"string": WORDMARK, "mime_type": "image/svg+xml", "redirected_url": url}
    raise FatalURLFetchingError(f"blocked renderer resource: {url}")


def main() -> int:
    resource_api = vars(resource)
    set_limit = resource_api.get("setrlimit")
    address_space_limit = resource_api.get("RLIMIT_AS")
    cpu_limit = resource_api.get("RLIMIT_CPU")
    if (
        not callable(set_limit)
        or not isinstance(address_space_limit, int)
        or not isinstance(cpu_limit, int)
    ):
        raise RuntimeError("the canonical renderer requires POSIX resource limits")
    set_limit(
        address_space_limit,
        (512 * 1024 * 1024, 512 * 1024 * 1024),
    )
    set_limit(
        cpu_limit,
        (20, 20),
    )
    source = sys.stdin.buffer.read(2_000_001)
    if len(source) > 2_000_000:
        raise ValueError("render input too large")
    html = source.decode("utf-8")
    if any(marker in html.lower() for marker in ("<script", "<style", "@import", "javascript:")):
        raise ValueError("unsafe render input")
    from weasyprint import CSS, HTML  # type: ignore[import-untyped]

    document = HTML(string=html, base_url=None, url_fetcher=_fetcher)
    stylesheet = CSS(string=DOCUMENT_CSS, base_url=None, url_fetcher=_fetcher)
    pdf = document.write_pdf(
        stylesheets=[stylesheet],
        pdf_variant="pdf/a-3u",
        full_fonts=True,
        custom_metadata=False,
    )
    sys.stdout.buffer.write(pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
