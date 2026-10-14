# scrapy-tor

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Scrapy](https://img.shields.io/badge/Scrapy-2.13+-blue.svg)](https://docs.scrapy.org/)

Scrapy downloader middleware that sends requests through a local Tor SOCKS5h proxy.

Several SOCKS authentication groups keep streams on separate circuits when `IsolateSOCKSAuth` is enabled in `torrc`. A retry uses another group. Blocking `requests` calls run in Twisted's thread pool.

## Features

- **Tor SOCKS5h** - every Scrapy request goes through a local Tor proxy
- **Circuit groups** - a distinct SOCKS username and password per group, so `IsolateSOCKSAuth` isolates streams
- **Retries** - a failed attempt is repeated on another circuit group
- **Thread pool** - blocking downloads run in Twisted's thread pool and come back as a Scrapy `Response`

## How It Works

1. **Assigns a circuit group** round-robin (`0, 1, 2, 3, ...`)
2. **Opens a thread-local** `requests.Session` through `socks5h://` with that group's credentials
3. **Lets Tor isolate streams** when the SOCKS port has `IsolateSOCKSAuth`
4. **Drops the session** after a network error and retries on the next group
5. **Returns a Scrapy response** (`HtmlResponse` for HTML, `Response` for images and other bodies)

SOCKS username and password are isolation labels. For group `N` the middleware uses `scrapy-group-N` / `scrapy-group-N`.

The middleware performs the download itself and returns a `Response`, so raise `REACTOR_THREADPOOL_MAXSIZE` to match `CONCURRENT_REQUESTS`. `requests` uses `allow_redirects=False`. Scrapy's `RedirectMiddleware` still handles redirects when the response comes back through the middleware chain.

## Prerequisites

- **Python 3.11 or higher**
- **Scrapy 2.13 or higher** (below 3.0)
- **Tor** listening on a local SOCKS port

## Installation

```bash
pip install scrapy-tor
```

### From source

```bash
git clone https://github.com/ruvn-1fgas/scrapy-tor.git
cd scrapy-tor
pip install .
```

Or:

```bash
pip install git+https://github.com/ruvn-1fgas/scrapy-tor.git
```

## Usage

Add the middleware in `settings.py`:

```python
DOWNLOADER_MIDDLEWARES = {
    "scrapy_tor.middlewares.RequestsTorDownloaderMiddleware": 543,
}

TOR_SOCKS_HOST = "127.0.0.1"
TOR_SOCKS_PORT = 9150  # Tor Browser; system Tor is usually 9050
TOR_CIRCUIT_GROUPS = 4
TOR_RETRIES = 1
TOR_CONNECT_TIMEOUT = 20
TOR_READ_TIMEOUT = 90
TOR_LOG_REQUESTS = True

CONCURRENT_REQUESTS = 32
REACTOR_THREADPOOL_MAXSIZE = 32
```

### Tor

The SOCKS port needs credential isolation. Groups share circuits when `IsolateSOCKSAuth` is absent.

```
SOCKSPort 9150 IsolateSOCKSAuth
```

System Tor usually uses port `9050`:

```
SOCKSPort 9050 IsolateSOCKSAuth
```

## Settings

- `TOR_SOCKS_HOST` - SOCKS host. Default: `127.0.0.1`.
- `TOR_SOCKS_PORT` - SOCKS port. Default: `9150` (Tor Browser).
- `TOR_CIRCUIT_GROUPS` - number of isolation groups. Default: `4`. Must be at least `1`.
- `TOR_RETRIES` - retries after the first attempt. Default: `1` (two attempts, each on its own group). Must be at least `0`.
- `TOR_CONNECT_TIMEOUT` - connect timeout, seconds. Default: `min(20, TOR_REQUEST_TIMEOUT)`.
- `TOR_READ_TIMEOUT` - read timeout, seconds. Default: `TOR_REQUEST_TIMEOUT`.
- `TOR_REQUEST_TIMEOUT` - legacy timeout, seconds. Default: `60`. Used when the newer timeouts are unset.
- `TOR_LOG_REQUESTS` - log every successful request. Default: `True`.

## Dependencies

- Python >= 3.11 - [python.org](https://www.python.org/)
- Scrapy >= 2.13, < 3.0 - [docs.scrapy.org](https://docs.scrapy.org/)
- requests with SOCKS support (`requests[socks]`) - [requests.readthedocs.io](https://requests.readthedocs.io/)

## License

MIT

## Changelog

### v2026.10.14.1

- Initial release: downloader middleware with Tor circuit groups and a retry on another group

---

# scrapy-tor (RU)

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Scrapy](https://img.shields.io/badge/Scrapy-2.13+-blue.svg)](https://docs.scrapy.org/)

Downloader middleware для Scrapy: запросы уходят в локальный Tor через SOCKS5h.

Несколько групп SOCKS-аутентификации разводят потоки по разным цепочкам, если в `torrc` включён `IsolateSOCKSAuth`. Повтор запроса получает другую группу. Блокирующие вызовы `requests` выполняются в пуле потоков Twisted.

## Возможности

- **Tor SOCKS5h** - каждый запрос Scrapy идёт через локальный прокси Tor
- **Группы цепочек** - свой логин и пароль SOCKS на группу, чтобы `IsolateSOCKSAuth` разделял потоки
- **Повторы** - неудачная попытка повторяется в другой группе цепочек
- **Пул потоков** - блокирующая загрузка идёт в пуле потоков Twisted и возвращается как Scrapy `Response`

## Как это работает

1. **Назначает группу цепочек** по кругу (`0, 1, 2, 3, ...`)
2. **Открывает** `requests.Session` в текущем потоке через `socks5h://` с учётными данными этой группы
3. **Отдаёт изоляцию Tor**, если на SOCKS-порте включён `IsolateSOCKSAuth`
4. **Закрывает сессию** после сетевой ошибки и повторяет запрос в следующей группе
5. **Возвращает ответ Scrapy** (`HtmlResponse` для HTML, `Response` для картинок и остальных тел)

Логин и пароль SOCKS - метки изоляции. Для группы `N` middleware подставляет `scrapy-group-N` / `scrapy-group-N`.

Middleware сам выполняет запрос и возвращает `Response`, поэтому `REACTOR_THREADPOOL_MAXSIZE` стоит поднять до уровня `CONCURRENT_REQUESTS`. `requests` ходит с `allow_redirects=False`. Редиректы по-прежнему обрабатывает `RedirectMiddleware` Scrapy, когда ответ возвращается в цепочку middleware.

## Требования

- **Python 3.11 или выше**
- **Scrapy 2.13 или выше** (ниже 3.0)
- **Tor** на локальном SOCKS-порте

## Установка

```bash
pip install scrapy-tor
```

### Из исходников

```bash
git clone https://github.com/ruvn-1fgas/scrapy-tor.git
cd scrapy-tor
pip install .
```

Или:

```bash
pip install git+https://github.com/ruvn-1fgas/scrapy-tor.git
```

## Использование

В `settings.py`:

```python
DOWNLOADER_MIDDLEWARES = {
    "scrapy_tor.middlewares.RequestsTorDownloaderMiddleware": 543,
}

TOR_SOCKS_HOST = "127.0.0.1"
TOR_SOCKS_PORT = 9150  # Tor Browser; системный Tor обычно 9050
TOR_CIRCUIT_GROUPS = 4
TOR_RETRIES = 1
TOR_CONNECT_TIMEOUT = 20
TOR_READ_TIMEOUT = 90
TOR_LOG_REQUESTS = True

CONCURRENT_REQUESTS = 32
REACTOR_THREADPOOL_MAXSIZE = 32
```

### Tor

На SOCKS-порте нужна изоляция по учётным данным. Без `IsolateSOCKSAuth` группы не разделяют цепочки.

```
SOCKSPort 9150 IsolateSOCKSAuth
```

Для системного Tor обычно используют порт `9050`:

```
SOCKSPort 9050 IsolateSOCKSAuth
```

## Настройки

- `TOR_SOCKS_HOST` - хост SOCKS-прокси. По умолчанию `127.0.0.1`.
- `TOR_SOCKS_PORT` - порт SOCKS. По умолчанию `9150` (Tor Browser).
- `TOR_CIRCUIT_GROUPS` - число групп изоляции. По умолчанию `4`. Должно быть не меньше `1`.
- `TOR_RETRIES` - число повторов после первой попытки. По умолчанию `1` (всего две попытки, каждая в своей группе). Должно быть не меньше `0`.
- `TOR_CONNECT_TIMEOUT` - таймаут соединения, секунды. По умолчанию `min(20, TOR_REQUEST_TIMEOUT)`.
- `TOR_READ_TIMEOUT` - таймаут чтения, секунды. По умолчанию значение `TOR_REQUEST_TIMEOUT`.
- `TOR_REQUEST_TIMEOUT` - старая настройка таймаута, секунды. По умолчанию `60`. Используется, если новые таймауты не заданы.
- `TOR_LOG_REQUESTS` - писать в лог каждый успешный запрос. По умолчанию `True`.

## Зависимости

- Python >= 3.11 - [python.org](https://www.python.org/)
- Scrapy >= 2.13, < 3.0 - [docs.scrapy.org](https://docs.scrapy.org/)
- requests с поддержкой SOCKS (`requests[socks]`) - [requests.readthedocs.io](https://requests.readthedocs.io/)

## Лицензия

MIT