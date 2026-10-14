"""Scrapy downloader middleware that sends requests through Tor."""

__version__ = "2026.10.14.1"

from scrapy_tor.middlewares import RequestsTorDownloaderMiddleware

__all__ = ["RequestsTorDownloaderMiddleware", "__version__"]
