# Kronos: необязательный CPU-worker

Настоящий [Kronos](https://github.com/shiyu-coder/Kronos) строит сценарии
следующих шести свечей по последним 60–120 закрытым свечам выбранной биржи.
Работает отдельно от панели с лимитом 96 МБ; панель не импортирует PyTorch.
Пять независимых путей сохраняются отдельно. Полоса показывает их минимум,
медиану и максимум. Совпадение направления сценариев — наблюдение выборки,
не вероятность успеха. Реальных ордеров и связи с торговыми моделями нет.

## Официальные источники и пины

* [Исходники](https://github.com/shiyu-coder/Kronos/tree/67b630e67f6a18c9e9be918d9b4337c960db1e9a):
  `67b630e67f6a18c9e9be918d9b4337c960db1e9a`, MIT; лицензия сохраняется.
* [Kronos-mini](https://huggingface.co/NeoQuasar/Kronos-mini/tree/f4e68697d9d5aed55cef5c96aabc3376bcad9f81):
  4,1 млн параметров, контекст 2048, веса 16,4 МБ;
  ревизия `f4e68697d9d5aed55cef5c96aabc3376bcad9f81`.
* [Tokenizer-2k](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-2k/tree/26966d0035065a0cae0ebad7af8ece35bc1fb51c):
  веса 15,8 МБ; ревизия `26966d0035065a0cae0ebad7af8ece35bc1fb51c`.
* [Статья](https://arxiv.org/html/2508.02739v1): прогнозы генерируются
  авторегрессионно. Здесь `T=0.6`, `top_p=0.9`; качество криптоскринера
  отдельно не измерено. Дневной бэктест статьи на акциях не переносится в
  результаты нашего скринера.

Установка использует Python 3.10–3.12, CPU [PyTorch 2.8.0](https://pypi.org/project/torch/2.8.0/),
и версии библиотеки из `requirements.txt`. Это воспроизводимый начальный
профиль, не заявление о самых новых версиях. Обучение, Qlib и webui не нужны.
Скорость измеряется в каждом результате. Пример лимита RAM — 1 ГБ; фактическую
пиковую память нужно измерить на сервере до массового использования.

## Локальная установка и запуск

Запускается явно оператором. `setup.py` создаёт отдельный venv, скачивает
только фиксированные официальные исходники и `.safetensors`, проверяет
SHA256 весов, сохраняет лицензию и манифест. Службы не запускает. Код модели
исполняется только при отдельном старте worker. Модель затем работает офлайн.
В runtime находится приватный `token`; этот каталог нельзя коммитить.

Linux из корня репозитория:

```sh
python3 integrations/kronos/setup.py --runtime integrations/kronos/runtime
integrations/kronos/runtime/.venv/bin/python -u integrations/kronos/runtime/app/worker.py --runtime integrations/kronos/runtime
```

Windows PowerShell из корня репозитория:

```powershell
& 'C:/Users/ПК/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' integrations/kronos/setup.py --runtime integrations/kronos/runtime
& './integrations/kronos/runtime/.venv/Scripts/python.exe' -u integrations/kronos/runtime/app/worker.py --runtime integrations/kronos/runtime
```

Для панели, запущенной отдельным процессом, установить `KRONOS_RUNTIME_DIR`
в тот же абсолютный каталог runtime. По умолчанию клиент читает
`/opt/trading-kronos/token`. Никаких внешних URL или модельных ID из браузера
worker не принимает.

Явная проверка двух монет на настоящем REST и настоящих весах, пока worker
работает в другом терминале:

```sh
integrations/kronos/runtime/.venv/bin/python integrations/kronos/smoke.py --runtime integrations/kronos/runtime --symbols BTCUSDT,ETHUSDT --exchange bybit --interval 5
```

```powershell
& './integrations/kronos/runtime/.venv/Scripts/python.exe' integrations/kronos/smoke.py --runtime integrations/kronos/runtime --symbols BTCUSDT,ETHUSDT --exchange bybit --interval 5
```

Успех выводит `real_model=true`, `real_exchange_data=true`, версии, источник,
задержку, шесть шагов и пять отдельных конечных цен. Если во время расчёта
закрылась новая свеча или вход изменился, тест не заявляет успех.
`tools/test_kronos.py` использует явно подставной адаптер: это проверка
контракта, очереди и защиты от устаревания, не проверка модели или её точности.

## Отдельная установка на NODE-02

Из корня проверенного checkout выполните от root:

```sh
bash integrations/kronos/install-service.sh
```

Нужен Python 3.10–3.12 с `venv`/`ensurepip` и свободная память для отдельной
службы (пример unit ограничен 1 ГБ). Если системный Python другой версии,
задайте абсолютный путь совместимого интерпретатора через `KRONOS_SETUP_PYTHON` (например, `/usr/bin/python3.11`).

Установщик читает закрытый root checkout от root, переносит только шесть
нужных исходных файлов в отдельный root-controlled каталог с доступом группы
`tradingbot`, а venv/пакеты/официальные веса устанавливает от `tradingbot` в
`/opt/trading-kronos`. Права всего checkout не меняются. Код модели не запускается
от root; worker запускается отдельным unit от `tradingbot`.

Каждый запуск сохраняет приватный журнал `/var/log/trading-kronos-install.*`.
Ошибка Python, venv, зависимости или загрузки останавливает установку и
выводит путь журнала. Unit создаётся только после успешной установки runtime.
Затем установщик запускает/перезапускает только `trading-kronos.service` и
выводит настоящий статус модели. `loading` требует дождаться загрузки;
`active` у systemd само по себе не доказывает, что модель загрузилась.

Рабочий каталог и приватный token принадлежат `tradingbot`; токен не печатается.
При повторной установке worker временно останавливается, token сохраняется.
Скрипт не изменяет состояние, реальные ордера или другие торговые службы.
Обычный `tools/update.sh` не выполняет установку модели: скрипт запускается
отдельно. Без успешно установленного unit интерфейс показывает «не подключён».

## API и привязка источника

Клиент панели: `KronosClient.status()`, `.request(packet)`, `.snapshot(packet)`.
`packet` — текущий проверенный ответ `ExchangeData` с `timestamp_origin=closed_candle`.
Методы status/snapshot не запрашивают свечи и не запускают прогнозы.
Только request отправляет POST. Один вызов транспорта ограничен коротким
loopback timeout; GET-ответы кэшируются на секунду, кэш ограничен 9 записями.

Worker слушает только `127.0.0.1:8790`. Все запросы требуют
`X-Kronos-Token`; Host должен быть локальным, Origin отсутствовать.
HTTPConnection клиента игнорирует настройки HTTP proxy. CORS нет.

* `GET /status`: состояние установленной модели и ёмкость очереди.
* `GET /jobs?job_id=<64 hex>`: только чтение уже существующей задачи;
  неизвестный ID возвращает idle без запуска модели.
* `POST /request`: фиксированный пакет `{source,candles,job_id,seed}`.
  Корректная постановка возвращает queued или существующий loading/ready;
  занятая очередь возвращает error и требует нового явного запроса.

`accepted=true` означает, что задача действительно принята или уже существует.
При старте модели статус loading с `accepted=false`; сначала дождаться idle
в GET /status, затем выполнить новый явный POST. Это исключает путаницу между
загрузкой весов и запущенным прогнозом.

Один процесс инференса, не более двух ожидающих задач и восьми результатов.
Превышение 120 секунд убивает процесс инференса; следующий запуск также
ограничен 120 секундами. GET обрабатывается независимо от расчёта.

Источник связан с биржей, canonical/native символом, периодом, последним
закрытием и SHA256 всех OHLCV/turnover последнего окна. Периоды UTC:
1m/5m/15m/1h/4h/1d. Amount получает фактический turnover, volume — базовый
объём. Будущие timestamps начинаются с времени открытия следующей свечи.
Хэш дополнен версиями исходников/весов, горизонтом и числом сценариев в job ID.
Изменённая свеча не использует результат от прежних данных.

Ответы: unavailable/idle/loading/queued/ready/error/stale. `source.updated`
сохраняет исходное реальное время проверки входа; `current_source_updated`
клиента содержит время текущего REST-подтверждения того же хэша, не время
запроса браузера. `expires_at=candle_end+period+2`. При ready доступны
`forecast=[{time,median,low,high}]`, `end_close_samples` из пяти путей,
`input_last_close`, `lookback`, `seed`, `inference_ms`, `completed_at`.
Клиент скрывает результат при недостаточном текущем подтверждении, смене
периода/биржи/свечи/хэша или несовпадении версий. Котировки и стакан не являются
доказательством свежести входных свечей. Демо-входы отвергаются.

## Отдельный HTTPS-сервис VDS

Если модель отвечает `idle`, но оценка через сайт отклоняется, проверьте маршрут
POST `/api/kronos/forecast`. Подтверждённая служба `trading-lab-https.service`
читает `/etc/trading-lab-https/nginx.conf`; стандартный `nginx -T` читает другой
файл. В исходном `location /` разрешён только GET.

`python3 integrations/kronos/configure-https.py --check` проверяет именно эту
узкую форму без изменений. Отдельный `--apply` от root на Linux добавляет
точный маршрут Kronos с GET/POST, копируя прежние настройки прокси и сохраняя
Basic Auth. Остальные маршруты остаются GET-only. Неизвестные правила,
существующий несовпадающий маршрут или symlink отвергаются. Перед заменой
создаётся приватная резервная копия; Nginx проверяется и получает reload с тем
же `-c`. При отказе исходный файл восстанавливается. Это не часть установки
модели и не запускается автоматически при обновлении сайта.

Существующие `limit_req`, `limit_req_status` и `limit_conn` сохраняются в
точном маршруте с теми же значениями и общими зонами. Помощник не отключает
лимиты и не повышает их. Ошибка о другом неподдерживаемом правиле называет
директиву и строку без её аргументов.

Семантика ограничения методов описана в официальной документации
[Nginx limit_except](https://nginx.org/en/docs/http/ngx_http_core_module.html#limit_except).
Ограничения нагрузки описаны в
[limit_req](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html#limit_req)
и [limit_conn](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html#limit_conn).
Подробная диагностика и проверка результата — в
[docs/kronos.md](../../docs/kronos.md).
