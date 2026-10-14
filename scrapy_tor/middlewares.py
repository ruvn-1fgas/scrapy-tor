import logging
import threading
import time
from threading import Lock, local

import requests
from scrapy.exceptions import IgnoreRequest
from scrapy.http import Headers, Response
from scrapy.responsetypes import responsetypes
from scrapy.utils.defer import deferred_to_future
from twisted.internet.threads import deferToThread

logger = logging.getLogger(__name__)


class RequestsTorDownloaderMiddleware:
    """
    Download Scrapy requests through Tor with multiple isolated
    SOCKS authentication groups

    Different SOCKS username/password pairs are used for each group
    With Tor's IsolateSOCKSAuth this causes streams from different
    groups to use separate circuit isolation contexts

    Blocking requests are executed in Twisted's thread pool
    """

    def __init__(
        self,
        socks_host: str,
        socks_port: int,
        connect_timeout: float,
        read_timeout: float,
        circuit_groups: int,
        retries: int,
        log_requests: bool,
    ) -> None:
        if circuit_groups < 1:
            raise ValueError("TOR_CIRCUIT_GROUPS must be >= 1")

        if retries < 0:
            raise ValueError("TOR_RETRIES must be >= 0")

        self.socks_host = socks_host
        self.socks_port = socks_port

        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

        self.circuit_groups = circuit_groups
        self.retries = retries

        self.log_requests = log_requests

        # Each Twisted worker thread has its own Sessions
        #
        # {
        #     group_id: requests.Session
        # }
        self._thread_local = local()

        # Round-robin assignment of requests to Tor isolation groups
        self._group_counter = 0
        self._group_counter_lock = Lock()

        # Runtime statistics
        self._stats_lock = Lock()

        self._active_requests = 0
        self._max_active_requests = 0

        self._completed_requests = 0
        self._failed_requests = 0

        self._group_active = [0 for _ in range(self.circuit_groups)]

        self._group_max_active = [0 for _ in range(self.circuit_groups)]

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        legacy_timeout = settings.getfloat(
            "TOR_REQUEST_TIMEOUT",
            60,
        )

        return cls(
            socks_host=settings.get("TOR_SOCKS_HOST", "127.0.0.1"),
            socks_port=settings.getint("TOR_SOCKS_PORT", 9150),
            connect_timeout=settings.getfloat(
                "TOR_CONNECT_TIMEOUT", min(20.0, legacy_timeout)
            ),
            read_timeout=settings.getfloat("TOR_READ_TIMEOUT", legacy_timeout),
            circuit_groups=settings.getint("TOR_CIRCUIT_GROUPS", 4),
            retries=settings.getint("TOR_RETRIES", 1),
            log_requests=settings.getbool("TOR_LOG_REQUESTS", True),
        )

    # ------------------------------------------------------------------
    # Circuit group management
    # ------------------------------------------------------------------

    def _next_group(self) -> int:
        """
        Assign requests to Tor isolation groups round-robin

        Example with 4 groups:
            0, 1, 2, 3, 0, 1, 2, 3, ...
        """

        with self._group_counter_lock:
            group_id = self._group_counter

            self._group_counter = (self._group_counter + 1) % self.circuit_groups

        return group_id

    # ------------------------------------------------------------------
    # requests.Session management
    # ------------------------------------------------------------------

    def _client(
        self,
        group_id: int,
    ) -> requests.Session:
        """
        Return a Session bound to a specific Tor isolation group

        Sessions are local to each worker thread because
        requests.Session should not be concurrently shared between
        multiple threads
        """

        if not hasattr(self._thread_local, "clients"):
            self._thread_local.clients = {}

        clients = self._thread_local.clients

        if group_id not in clients:
            session = requests.Session()

            username = f"scrapy-group-{group_id}"
            password = f"scrapy-group-{group_id}"

            proxy = (
                f"socks5h://"
                f"{username}:{password}@"
                f"{self.socks_host}:{self.socks_port}"
            )

            session.proxies = {
                "http": proxy,
                "https": proxy,
            }

            # Ignore HTTP_PROXY / HTTPS_PROXY / ALL_PROXY inherited
            # from the operating system
            session.trust_env = False

            clients[group_id] = session

        return clients[group_id]

    def _drop_client(
        self,
        group_id: int,
    ) -> None:
        """
        Close the Session after a network error

        This prevents a broken/stale connection pool from being reused
        on the next request
        """

        clients = getattr(
            self._thread_local,
            "clients",
            None,
        )

        if not clients:
            return

        session = clients.pop(
            group_id,
            None,
        )

        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def _request_started(self) -> None:
        with self._stats_lock:
            self._active_requests += 1

            self._max_active_requests = max(
                self._max_active_requests,
                self._active_requests,
            )

    def _request_finished(self) -> None:
        with self._stats_lock:
            self._active_requests -= 1

    def _group_started(
        self,
        group_id: int,
    ) -> None:
        with self._stats_lock:
            self._group_active[group_id] += 1

            self._group_max_active[group_id] = max(
                self._group_max_active[group_id],
                self._group_active[group_id],
            )

    def _group_finished(
        self,
        group_id: int,
    ) -> None:
        with self._stats_lock:
            self._group_active[group_id] -= 1

    def _success_stats(
        self,
        group_id: int,
    ):
        with self._stats_lock:
            self._completed_requests += 1

            return (
                self._active_requests,
                self._max_active_requests,
                self._group_active[group_id],
                self._group_max_active[group_id],
                self._completed_requests,
                self._failed_requests,
            )

    def _failure_stats(
        self,
        group_id: int,
        final: bool,
    ):
        with self._stats_lock:
            if final:
                self._failed_requests += 1

            return (
                self._active_requests,
                self._max_active_requests,
                self._group_active[group_id],
                self._group_max_active[group_id],
                self._completed_requests,
                self._failed_requests,
            )

    # ------------------------------------------------------------------
    # Scrapy middleware
    # ------------------------------------------------------------------

    async def process_request(
        self,
        request,
        spider=None,
    ):
        del spider

        response = await deferred_to_future(
            deferToThread(
                self._fetch,
                request,
            )
        )

        return self._to_scrapy_response(
            response,
            request,
        )

    # ------------------------------------------------------------------
    # HTTP request
    # ------------------------------------------------------------------

    def _fetch(
        self,
        request,
    ) -> requests.Response:
        headers = request.headers.to_unicode_dict()

        # Avoid compressed image responses
        headers["Accept-Encoding"] = "identity"

        self._request_started()

        request_started = time.monotonic()

        last_error = None

        try:
            # retries=1 means:
            #
            # attempt 1
            # attempt 2
            #
            # The retry gets another circuit group
            for attempt in range(
                1,
                self.retries + 2,
            ):
                group_id = self._next_group()

                self._group_started(group_id)

                attempt_started = time.monotonic()

                try:
                    response = self._client(group_id).request(
                        method=request.method,
                        url=request.url,
                        headers=headers,
                        data=request.body or None,
                        # Separate connect/read timeout
                        timeout=(
                            self.connect_timeout,
                            self.read_timeout,
                        ),
                        allow_redirects=False,
                    )

                    elapsed = time.monotonic() - attempt_started

                    (
                        active,
                        max_active,
                        group_active,
                        group_max,
                        completed,
                        failed,
                    ) = self._success_stats(group_id)

                    if self.log_requests:
                        logger.info(
                            "TOR %.2fs | "
                            "group=%d | "
                            "group_active=%d | "
                            "group_max=%d | "
                            "active=%d | "
                            "max=%d | "
                            "done=%d | "
                            "failed=%d | "
                            "attempt=%d/%d | "
                            "%.1f KB | "
                            "status=%d | "
                            "thread=%d | "
                            "%s",
                            elapsed,
                            group_id,
                            group_active,
                            group_max,
                            active,
                            max_active,
                            completed,
                            failed,
                            attempt,
                            self.retries + 1,
                            len(response.content) / 1024,
                            response.status_code,
                            threading.get_ident(),
                            request.url,
                        )

                    return response

                except requests.RequestException as error:
                    last_error = error

                    elapsed = time.monotonic() - attempt_started

                    final = attempt > self.retries

                    (
                        active,
                        max_active,
                        group_active,
                        group_max,
                        completed,
                        failed,
                    ) = self._failure_stats(
                        group_id,
                        final=final,
                    )

                    logger.warning(
                        "TOR ERROR %.2fs | "
                        "group=%d | "
                        "group_active=%d | "
                        "group_max=%d | "
                        "active=%d | "
                        "max=%d | "
                        "done=%d | "
                        "failed=%d | "
                        "attempt=%d/%d | "
                        "thread=%d | "
                        "%s | "
                        "%s",
                        elapsed,
                        group_id,
                        group_active,
                        group_max,
                        active,
                        max_active,
                        completed,
                        failed,
                        attempt,
                        self.retries + 1,
                        threading.get_ident(),
                        request.url,
                        error,
                    )

                    # Throw away this connection pool
                    self._drop_client(group_id)

                    if final:
                        total_elapsed = time.monotonic() - request_started

                        raise IgnoreRequest(
                            "Tor request failed after "
                            f"{attempt} attempts "
                            f"({total_elapsed:.2f}s): "
                            f"{request.url}: "
                            f"{error}"
                        ) from error

                    logger.info(
                        "TOR RETRY | "
                        "previous_group=%d | "
                        "next attempt will use another "
                        "circuit group | "
                        "%s",
                        group_id,
                        request.url,
                    )

                finally:
                    self._group_finished(group_id)

            # Defensive fallback. Normally unreachable
            raise IgnoreRequest(
                f"Tor request failed: " f"{request.url}: " f"{last_error}"
            )

        finally:
            self._request_finished()

    # ------------------------------------------------------------------
    # requests.Response -> Scrapy Response
    # ------------------------------------------------------------------

    @staticmethod
    def _to_scrapy_response(
        response: requests.Response,
        request,
    ) -> Response:
        headers = Headers(response.headers)

        # response.content is already decoded by requests
        headers.pop(
            b"Content-Encoding",
            None,
        )

        headers.pop(
            b"Content-Length",
            None,
        )

        # Let Scrapy choose the right response class:
        #
        # text/html -> HtmlResponse
        # image/jpeg -> Response
        # image/png  -> Response
        # etc
        response_class = responsetypes.from_args(
            headers=headers,
            url=response.url,
            body=response.content,
        )

        return response_class(
            url=response.url,
            status=response.status_code,
            headers=headers,
            body=response.content,
            request=request,
        )
