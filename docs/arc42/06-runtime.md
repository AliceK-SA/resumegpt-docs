# 6. Работа в динамике

Главный процесс системы — продвинутый анализ резюме. Это **сага**: цепочка локальных транзакций в трёх сервисах (analysis, billing, ai-worker) и вызовы двух внешних систем (hh.ru, Groq). Общего `COMMIT` на всех нет, поэтому для каждого шага заранее решено, что делать при сбое и как отменить уже сделанное. Командует процессом `analysis-service` ([ADR-0001](../adr/0001-saga-with-credit-reservation.md)).

Базовый анализ проходит тот же путь, только без шагов с кредитом.

## 6.1. Жизненный цикл заявки

Это «память» оркестратора: по статусу заявки видно, на каком шаге процесс и что делать дальше.

```mermaid
stateDiagram-v2
    [*] --> CREATED: POST /analyses<br/>файл сохранён в MinIO

    CREATED --> QUEUED: кредит зарезервирован<br/>(для BASIC сразу)
    CREATED --> FAILED: billing не ответил за 10 мин<br/>(вернуть кредит, если резерв всё же прошёл)

    QUEUED --> PROCESSING: воркер арендовал задачу
    PROCESSING --> COMPLETED: analysis.completed<br/>(списать кредит)
    PROCESSING --> QUEUED: временная ошибка или истекла аренда<br/>(попытка меньше 3)
    PROCESSING --> FAILED: постоянная ошибка или 3 попытки<br/>(компенсация: вернуть кредит)

    COMPLETED --> [*]
    FAILED --> [*]
```

**Правило переходов.** Каждый переход — это условный `UPDATE analyses SET status = :new WHERE id = :id AND status = :expected`. Если строка не обновилась, значит кто-то (другой воркер, watchdog, дубль события) уже перевёл заявку. Тогда мы ничего не делаем повторно. Так гонки решает база, а не удача.

**Кредит меняет судьбу ровно один раз.** Команда «списать» отправляется только при переходе в `COMPLETED`, команда «вернуть» — только при переходе в `FAILED`. Оба перехода финальные, поэтому для одного анализа отправится ровно одна из двух команд.

## 6.2. Основные гарантии

| Что нельзя | Чем обеспечено |
|---|---|
| Создать два анализа одним нажатием | `Idempotency-Key` на `POST /analyses` |
| Зарезервировать два кредита на один анализ | Первичный ключ `reservations(analysis_id)` в billing_db |
| Уйти в минус по кредитам | `CHECK (balance >= 0)` в `credit_accounts` |
| И списать, и вернуть кредит (или вернуть дважды) | Условные переходы `RESERVED → COMMITTED` / `RESERVED → RELEASED` |
| Потерять кредит при сбое анализа | Каждый путь в `FAILED` отправляет команду возврата; команды идут через outbox |
| Принять два результата или устаревший результат | Токен текущей аренды, `attempt`, `workerId` и условная фиксация (`ADR-0007`); повторный внешний вызов Groq при сбое возможен |
| Потерять задачу, если воркер умер | Watchdog возвращает задачи с истёкшей арендой в очередь |
| Зафиксировать сообщение дважды | Таблица `inbox(event_id)` у получателей с базой; результат воркера дополнительно сверяется с токеном аренды |
| Потерять сообщение | Таблица `outbox` в той же транзакции, что и изменение данных |
| Зачислить оплату дважды | Уникальность `ledger(reason, ref_id)` по `purchaseId` + условный переход покупки `PENDING → PAID` |

## 6.3. Успешный сценарий: продвинутый анализ

Сценарий разделён на два рисунка, чтобы подписи оставались читаемыми и в отчёте, и на сайте.

**Шаги 1–2: создание заявки, резерв и выполнение анализа.**

```mermaid
sequenceDiagram
    autonumber
    actor U as Пользователь
    participant A as analysis-service
    participant BL as billing-service
    participant MQ as RabbitMQ
    participant W as ai-worker
    U->>A: POST /analyses через Gateway, Idempotency-Key
    Note over A: Файл сохранён в MinIO, заявка CREATED
    A->>BL: POST /internal/reservations (analysisId, userId)
    Note over BL: Атомарный резерв и списание баланса, только при новом резерве
    BL-->>A: 201 Reservation
    Note over A: QUEUED + outbox analysis.requested (одна транзакция)
    A-->>U: 202 Accepted, analysisId
    A-)MQ: analysis.requested
    MQ-)W: сообщение из ai.jobs
    W->>A: POST /internal/analyses/{id}/lease (attempt 1)
    Note over A: PROCESSING, новый leaseToken, leaseUntil = now + 240 с
    A-->>W: LeaseGrant (leaseToken)
    W-)MQ: ack
    Note over W: MinIO/Tika → hh.ru → Groq, контроль дедлайна
    opt Длительная обработка
        W->>A: POST /internal/analyses/{id}/lease/renew
        A-->>W: продлённая аренда либо 409
    end
```

**Шаг 3: проверка попытки, сохранение результата и списание кредита.**

```mermaid
sequenceDiagram
    autonumber
    participant W as ai-worker
    participant MQ as RabbitMQ
    participant A as analysis-service
    participant BL as billing-service
    actor U as Пользователь
    W-)MQ: analysis.completed (attempt, workerId, leaseToken, result)
    MQ-)A: analysis.completed
    Note over A: В транзакции INSERT inbox и UPDATE analyses<br/>WHERE status=PROCESSING AND attempt/workerId/leaseToken совпали<br/>AND lease_until >= now()
    alt Текущая действующая аренда
        Note over A: INSERT analysis_results, outbox credits.commit-requested
        A-)MQ: credits.commit-requested
        MQ-)BL: credits.commit-requested
        Note over BL: RESERVED → COMMITTED один раз
    else Устаревший результат
        Note over A: Запись не изменяется, кредит не списывается повторно
    end
    U->>A: GET /analyses/{id} через Gateway
    A-->>U: COMPLETED и результат
```

**Обозначения:** `->>` — синхронный HTTP-вызов, `-)` — асинхронное сообщение. «Одна транзакция» — локальная транзакция PostgreSQL внутри одного сервиса.

**Ключевые моменты:**

- Пользователь получает ответ сразу после шага 1 (`202`), дальше клиент опрашивает статус. Держать HTTP-соединение минуту, пока думает Groq, мы не стали — оно бы рвалось по таймаутам.
- Кредит **резервируется до** анализа (чтобы нельзя было запустить 100 анализов с одним кредитом), а **списывается после** (чтобы не платить за неудачу).
- Воркер подтверждает сообщение (ack) **сразу после аренды**, а не после анализа. Если воркер умрёт, задачу вернёт в очередь watchdog, а не RabbitMQ (сценарий сбоя 2).
- В сообщениях лежит только путь к файлу в MinIO, а не сам файл: сообщения остаются маленькими ([ADR-0005](../adr/0005-database-per-service-and-object-storage.md)).

## 6.4. Сбой 1: Groq недоступен или упёрся в лимит запросов

**Что ломается.** Groq отвечает `429 Too Many Requests` (бесплатные лимиты), `5xx` или не отвечает 45 секунд. Сюда же относится недоступность hh.ru. Кредит уже зарезервирован, пользователь ждёт.

**Как система справляется — три уровня:**

1. **Внутри попытки.** Воркер повторяет вызов Groq до 2 раз с паузой 2 и 5 с, учитывая заголовок `Retry-After`. Вся цепочка ограничена общим дедлайном попытки; при риске истечения аренды воркер продлевает её до разрешённого максимума или возвращает retryable-ошибку.
2. **Между попытками.** Если не помогло, воркер публикует `analysis.failed` с `retryable = true`. `analysis-service` возвращает задачу в очередь как попытку 2, а потом 3 — с паузой 30 с и 2 мин. Пауза реализована полем `publish_after` в outbox: relay отправляет сообщение не раньше этого времени.
3. **Компенсация.** После третьей неудачи заявка становится `FAILED`, и кредит **возвращается**.

Постоянные ошибки (вакансия удалена — hh.ru вернул `404`, в PDF только картинка без текста) повторять бессмысленно: сразу `FAILED` и возврат кредита.

```mermaid
sequenceDiagram
    autonumber
    participant A as analysis-service
    participant MQ as RabbitMQ
    participant W as ai-worker
    participant G as Groq
    participant BL as billing-service

    Note over A: заявка ADVANCED, кредит RESERVED, попытка 1
    MQ-)W: analysis.requested (attempt 1)
    W->>A: lease (attempt 1)
    A-->>W: 200
    W->>G: chat completion
    G-->>W: 429 Too Many Requests, Retry-After 5
    W->>G: повтор через 5 с
    G-->>W: 429
    W->>G: повтор
    G-->>W: 503
    W-)MQ: analysis.failed (AI_UNAVAILABLE, retryable = true)
    MQ-)A: analysis.failed

    rect rgba(255, 200, 80, 0.12)
    Note over A: Одна транзакция:<br/>UPDATE analyses SET QUEUED, attempt = 2 WHERE status = PROCESSING AND attempt = 1<br/>INSERT outbox (analysis.requested attempt 2, publish_after = now + 30 с)
    Note over A,W: ...попытка 2 — та же ошибка, попытка 3 через 2 мин — та же ошибка...
    end

    MQ-)A: analysis.failed (attempt 3, retryable = true)

    rect rgba(255, 80, 80, 0.10)
    Note over A: Компенсация, одна транзакция:<br/>UPDATE analyses SET FAILED (AI_UNAVAILABLE), creditStatus = RETURNED<br/>WHERE status = PROCESSING AND attempt = 3<br/>INSERT outbox (credits.release-requested)
    A-)MQ: credits.release-requested
    MQ-)BL: credits.release-requested
    Note over BL: Одна транзакция:<br/>INSERT inbox<br/>UPDATE reservations SET RELEASED WHERE status = RESERVED (1 строка)<br/>UPDATE credit_accounts SET balance = balance + 1<br/>INSERT ledger (RELEASE, +1)
    end

    Note over A: Пользователь видит: «Сервис анализа перегружен,<br/>кредит возвращён, попробуйте позже»
```

**А если `credits.release-requested` придёт дважды?** Повтор отсеется в `inbox`. Даже без inbox условие `WHERE status = 'RESERVED'` обновит 0 строк, и баланс второй раз не увеличится.

## 6.5. Сбой 2: воркер упал посреди анализа

**Что ломается.** Воркер арендовал задачу и подтвердил сообщение, начал разбирать PDF на 4 МБ, и у него кончилась память (OOM) — контейнер перезапустился. Сообщения в очереди уже нет, задача висит в `PROCESSING`, пользователь ждёт вечно.

**Как восстанавливаемся.** В `analysis-service` работает **watchdog**: раз в 30 секунд он ищет заявки в `PROCESSING` с истёкшей арендой и возвращает их в очередь новой попыткой. Задачу берёт другой воркер. После третьей такой неудачи — `FAILED (ATTEMPTS_EXHAUSTED)` и возврат кредита, как в сценарии 1: значит, сам файл «роняет» воркеры.

**Почему не положиться на RabbitMQ (ack после окончания работы)?** Тогда при падении воркера RabbitMQ сразу отдал бы сообщение другому воркеру. Но аренда первого ещё действует, второй получил бы `409` и выбросил задачу. Два механизма мешали бы друг другу. Поэтому за «живость» задачи отвечает один механизм — аренда ([ADR-0004](../adr/0004-stateless-worker-with-lease.md)).

```mermaid
sequenceDiagram
    autonumber
    participant A as analysis-service
    participant WD as watchdog (в analysis-service)
    participant MQ as RabbitMQ
    participant W1 as ai-worker-1
    participant W2 as ai-worker-2

    MQ-)W1: analysis.requested (attempt 1)
    W1->>A: lease (attempt 1)
    Note over A: PROCESSING, lease_until = 16:34:00
    A-->>W1: 200
    W1-)MQ: ack
    Note over W1: разбирает PDF... OutOfMemoryError
    W1-xW1: контейнер перезапускается

    rect rgba(80, 200, 120, 0.10)
    Note over WD: 16:34:20 — проверка раз в 30 с
    WD->>A: SELECT … WHERE status = PROCESSING AND lease_until < now()<br/>FOR UPDATE SKIP LOCKED
    Note over A: Одна транзакция:<br/>UPDATE analyses SET QUEUED, attempt = 2<br/>WHERE status = PROCESSING AND attempt = 1<br/>INSERT outbox (analysis.requested attempt 2)
    A-)MQ: analysis.requested (attempt 2)
    MQ-)W2: analysis.requested (attempt 2)
    W2->>A: lease (attempt 2)
    A-->>W2: 200
    Note over W2: анализ проходит успешно
    W2-)MQ: analysis.completed (attempt 2)
    MQ-)A: analysis.completed
    Note over A: COMPLETED, credits.commit-requested — как в успешном сценарии
    end

    opt Если W1 не умер, а просто «завис» и прислал результат позже
        W1-)MQ: analysis.completed (attempt 1)
        MQ-)A: analysis.completed (attempt 1)
        Note over A: заявка уже COMPLETED, UPDATE обновил 0 строк.<br/>Результат игнорируется, кредит второй раз не списывается
    end
```

**Дубль сообщения в очереди** (RabbitMQ доставил `analysis.requested` повторно) обрабатывается так же просто: второй воркер просит аренду, получает `409` (задача уже не `QUEUED`), подтверждает сообщение и берёт следующую задачу. Groq второй раз не вызывается.

## 6.6. Сбой 3: сбой между резервом кредита и постановкой в очередь

**Что ломается.** Самое «узкое» место саги — шаг 1, где участвуют два сервиса синхронно. `analysis-service` вызвал резерв кредита, `billing-service` его выполнил, но:

- ответ потерялся по дороге (таймаут 2 с) — `analysis-service` не знает, зарезервирован ли кредит;
- или `analysis-service` упал сразу после ответа, не успев перевести заявку в `QUEUED`.

Кредит списан с баланса, а задача не в очереди. Если ничего не делать, кредит пропал.

**Как восстанавливаемся.** Заявка остаётся в `CREATED`. Пользователь получает `202`, а клиент показывает «Готовим анализ…». Watchdog раз в 30 секунд берёт заявки в `CREATED` старше 30 секунд и **повторяет резерв**. Резерв идемпотентен по `analysisId`:

- если кредит уже был зарезервирован — billing вернёт существующий резерв (`200`), второй кредит не спишется, заявка уйдёт в очередь;
- если billing так и не ответил за 10 минут — заявка становится `FAILED (RESERVATION_TIMEOUT)` и отправляется команда возврата. Если резерв на самом деле был — кредит вернётся; если не был — команда ничего не изменит.

```mermaid
sequenceDiagram
    autonumber
    actor U as Пользователь
    participant A as analysis-service
    participant WD as watchdog (в analysis-service)
    participant BL as billing-service
    participant MQ as RabbitMQ

    U->>A: POST /analyses (ADVANCED)
    Note over A: INSERT analyses (CREATED)
    A->>BL: POST /internal/reservations (analysisId)
    Note over BL: резерв создан, balance - 1, COMMIT
    BL--xA: ответ не дошёл (таймаут 2 с)
    A-->>U: 202 Accepted, status = CREATED
    Note over U: клиент показывает «Готовим анализ…»

    rect rgba(80, 200, 120, 0.10)
    Note over WD: через 30 с: заявки в CREATED старше 30 с
    WD->>BL: POST /internal/reservations (тот же analysisId)
    Note over BL: INSERT … ON CONFLICT DO NOTHING — строка уже есть,<br/>баланс НЕ меняется
    BL-->>WD: 200 существующий резерв
    Note over A: Одна транзакция:<br/>UPDATE analyses SET QUEUED WHERE status = CREATED<br/>INSERT outbox (analysis.requested)
    A-)MQ: analysis.requested
    Note over A,MQ: дальше — как в успешном сценарии
    end

    alt billing-service недоступен 10 минут подряд
        rect rgba(255, 80, 80, 0.10)
        Note over A: Компенсация, одна транзакция:<br/>UPDATE analyses SET FAILED (RESERVATION_TIMEOUT), creditStatus = RETURNED<br/>WHERE status = CREATED<br/>INSERT outbox (credits.release-requested)
        A-)MQ: credits.release-requested
        Note over MQ: команда ждёт в очереди billing.inbox,<br/>пока billing-service не поднимется
        MQ-)BL: credits.release-requested
        Note over BL: резерв есть → RELEASED, balance + 1<br/>резерва нет → ничего не делаем
        end
    end
```

Если же billing-service ответил **отказом соединения** (точно лежит), заявка удаляется сразу, а пользователь получает `503` с подсказкой «продвинутый анализ временно недоступен, можно запустить базовый». Базовый анализ от billing-service не зависит.

## 6.7. Покупка пакета кредитов

Короткая сага с той же защитой от двойного зачисления.

```mermaid
sequenceDiagram
    autonumber
    actor U as Пользователь
    participant BL as billing-service
    participant P as payment-service
    participant YK as ЮKassa
    participant MQ as RabbitMQ

    U->>BL: POST /purchases (pack-10), Idempotency-Key
    Note over BL: INSERT purchases (PENDING)
    BL->>P: POST /payments (purchaseId, 79 ₽)
    P->>YK: создать платёж, Idempotence-Key = paymentId
    YK-->>P: confirmation_url
    P-->>BL: 201 Payment
    BL-->>U: 201, confirmationUrl
    U->>YK: оплата картой
    YK-)P: вебхук payment.succeeded
    P->>YK: GET платёж (проверяем статус сами)
    Note over P: UPDATE payments SET SUCCEEDED WHERE status = PENDING<br/>INSERT outbox (payment.succeeded)
    P-->>YK: 200
    P-)MQ: payment.succeeded
    MQ-)BL: payment.succeeded
    Note over BL: Одна транзакция:<br/>INSERT inbox<br/>UPDATE purchases SET PAID WHERE status = PENDING<br/>UPDATE credit_accounts SET balance = balance + 10<br/>INSERT ledger (PURCHASE, +10, ref = purchaseId)
    opt ЮKassa прислала вебхук повторно
        YK-)P: вебхук payment.succeeded
        Note over P: UPDATE … WHERE status = PENDING обновил 0 строк — событие не публикуется
        P-->>YK: 200
    end
```

Если `payment-service` был недоступен, когда пришёл вебхук, ЮKassa повторит уведомление сама. Кроме того, `reconciliation-worker` раз в минуту сверяет с ЮKassa платежи, которые висят в `PENDING` дольше 2 минут. Оба пути идут через один условный `UPDATE`, поэтому кредиты зачислятся ровно один раз.

**Контрактная защита поздних событий:** оба результата воркера (`analysis.completed` и `analysis.failed`) несут `leaseToken`; после увеличения attempt старый токен недействителен. Возможность повторного внешнего запроса сохраняется, но результат старого воркера не побеждает.
