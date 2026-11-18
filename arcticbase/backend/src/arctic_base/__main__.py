"""Entry point: `python -m arctic_base` or the `arctic-base` console script.

Reads host/port from settings (env-driven) so the default is auto-lan:7673.
"""

from __future__ import annotations

import uvicorn

from arctic_base.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "arctic_base.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,  # use our JSON formatter installed by configure_logging()
    )


if __name__ == "__main__":
    main()
