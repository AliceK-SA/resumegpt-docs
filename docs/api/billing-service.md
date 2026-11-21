<!-- Файл сгенерирован scripts/gen_api_reference.py из docs/api/openapi/billing-service.yaml. Не редактируйте вручную. -->

# billing-service

Спецификация: [`billing-service.yaml`](openapi/billing-service.yaml) · OpenAPI 3.0.3 · версия API 1.0.0

Пакеты кредитов, баланс, покупки, резерв кредитов под анализ.

**Защита кредитов от потери и задвоения:**

- баланс не может стать отрицательным — `CHECK (balance >= 0)` в `credit_accounts`;
- на один анализ — один резерв: первичный ключ `reservations(analysis_id)`;
- списание и возврат — условные переходы `RESERVED → COMMITTED` / `RESERVED → RELEASED`,
  поэтому выполнить оба или одно дважды невозможно;
- за одну покупку кредиты зачисляются один раз — уникальность `ledger(reason, ref_id)`;
- каждое движение кредитов записано в журнал `ledger`, баланс всегда сходится с суммой журнала.

Списание и возврат резерва приходят командами через брокер (см. AsyncAPI),
а не HTTP-вызовами, чтобы не потеряться при недоступности сервиса.

## Адреса

| Адрес | Назначение |
|---|---|
| `http://billing-service:8080` | Внутренний адрес (docker-compose) |
| `http://localhost:8000/api` | Через API Gateway (только публичные методы) |

## Операции

| Метод и путь | Назначение | Ответы |
|---|---|---|
| `GET /credit-packs` | Доступные пакеты кредитов | 200 |
| `GET /credits/balance` | Баланс кредитов пользователя | 200, 401, 403 |
| `GET /credits/history` | История движений кредитов (журнал) | 200, 401, 403 |
| `POST /purchases` | Купить пакет кредитов | 201, 404, 503, 401, 403 |
| `GET /purchases/{purchaseId}` | Статус покупки | 200, 404, 401, 403 |
| `POST /internal/reservations` | Зарезервировать кредит под анализ | 200, 201, 402, 401 |

### GET /credit-packs

**Доступные пакеты кредитов**

`operationId`: `listCreditPacks` · тег: Purchases

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `200` | OK | `application/json`: массив из [CreditPack](#schema-creditpack) |

### GET /credits/balance

**Баланс кредитов пользователя**

`operationId`: `getBalance` · тег: Credits

**Параметры**

| Имя | Где | Тип | Обязательный | Описание |
|---|---|---|---|---|
| `X-User-Id` | header | string (uuid) | да | Заголовок доверенной идентичности. Браузер не задаёт его: API Gateway удаляет входящий X-User-Id и проставляет идентификатор из проверенного JWT. Внутренний сервис принимает его только от доверенного шлюза. |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `200` | OK | `application/json`: [Balance](#schema-balance) |
| `401` | Токен отсутствует, недействителен или истёк | `application/problem+json`: [Problem](#schema-problem) |
| `403` | Доступ к ресурсу или операции запрещён | `application/problem+json`: [Problem](#schema-problem) |

### GET /credits/history

**История движений кредитов (журнал)**

`operationId`: `getCreditHistory` · тег: Credits

**Параметры**

| Имя | Где | Тип | Обязательный | Описание |
|---|---|---|---|---|
| `X-User-Id` | header | string (uuid) | да | Заголовок доверенной идентичности. Браузер не задаёт его: API Gateway удаляет входящий X-User-Id и проставляет идентификатор из проверенного JWT. Внутренний сервис принимает его только от доверенного шлюза. |
| `page` | query | integer, ≥ 0 | нет |  |
| `size` | query | integer, ≥ 1, ≤ 50 | нет |  |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `200` | OK | `application/json`: object |
| `401` | Токен отсутствует, недействителен или истёк | `application/problem+json`: [Problem](#schema-problem) |
| `403` | Доступ к ресурсу или операции запрещён | `application/problem+json`: [Problem](#schema-problem) |

### POST /purchases

**Купить пакет кредитов**

Создаёт покупку `PENDING` и вызывает payment-service (`POST /payments`, ключ — `purchaseId`).
Возвращает ссылку на страницу оплаты ЮKassa. Кредиты зачисляются после события
`payment.succeeded`, не раньше.

`operationId`: `createPurchase` · тег: Purchases

**Параметры**

| Имя | Где | Тип | Обязательный | Описание |
|---|---|---|---|---|
| `X-User-Id` | header | string (uuid) | да | Заголовок доверенной идентичности. Браузер не задаёт его: API Gateway удаляет входящий X-User-Id и проставляет идентификатор из проверенного JWT. Внутренний сервис принимает его только от доверенного шлюза. |
| `Idempotency-Key` | header | string (uuid) | да |  |

**Тело запроса** (`application/json`)

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `packId` | string | да |  |
| `returnUrl` | string (uri) | да |  |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `201` | Покупка создана | `application/json`: [Purchase](#schema-purchase) |
| `404` | Нет такого пакета | `application/problem+json`: [Problem](#schema-problem) |
| `503` | payment-service недоступен, повторите позже | `application/problem+json`: [Problem](#schema-problem) |
| `401` | Токен отсутствует, недействителен или истёк | `application/problem+json`: [Problem](#schema-problem) |
| `403` | Доступ к ресурсу или операции запрещён | `application/problem+json`: [Problem](#schema-problem) |

### GET /purchases/{purchaseId}

**Статус покупки**

`operationId`: `getPurchase` · тег: Purchases

**Параметры**

| Имя | Где | Тип | Обязательный | Описание |
|---|---|---|---|---|
| `purchaseId` | path | string (uuid) | да |  |
| `X-User-Id` | header | string (uuid) | да | Заголовок доверенной идентичности. Браузер не задаёт его: API Gateway удаляет входящий X-User-Id и проставляет идентификатор из проверенного JWT. Внутренний сервис принимает его только от доверенного шлюза. |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `200` | OK | `application/json`: [Purchase](#schema-purchase) |
| `404` | Не найдено | `application/problem+json`: [Problem](#schema-problem) |
| `401` | Токен отсутствует, недействителен или истёк | `application/problem+json`: [Problem](#schema-problem) |
| `403` | Доступ к ресурсу или операции запрещён | `application/problem+json`: [Problem](#schema-problem) |

### POST /internal/reservations

**Зарезервировать кредит под анализ**

Атомарная идемпотентная операция на одну транзакцию. Сначала блокируется строка счёта
`SELECT ... FROM credit_accounts WHERE user_id=:userId FOR UPDATE`. Затем проверяется
`reservations(analysis_id)` с уникальным ключом. Если запись уже есть, операция возвращает
существующий результат без изменения баланса и ledger. Для новой заявки, не отмеченной
ожидающей компенсацией, выполняется условное списание (`UPDATE ... SET balance=balance-1
WHERE user_id=:userId AND balance>=1 RETURNING user_id`), после успешного UPDATE создаётся
`reservations(..., RESERVED)` и единственная запись `ledger(RESERVE,-1)`.
Если для `analysisId` уже зарегистрирована ожидающая компенсация, резерв не создаётся и
баланс не уменьшается: ответ сообщает `RELEASED`. Проверка уникальности, блокировка и
изменение баланса идут строго в одной транзакции. Никакой отдельный UPDATE не выполняется
после `ON CONFLICT DO NOTHING` без проверки результата.

`operationId`: `reserveCredit` · тег: Internal

**Тело запроса** (`application/json`)

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `analysisId` | string (uuid) | да |  |
| `userId` | string (uuid) | да |  |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `200` | Повтор или ранее компенсированная заявка; списания нет | `application/json`: [Reservation](#schema-reservation) |
| `201` | Кредит зарезервирован | `application/json`: [Reservation](#schema-reservation) |
| `402` | Недостаточно кредитов | `application/problem+json`: [Problem](#schema-problem) |
| `401` | Токен отсутствует, недействителен или истёк | `application/problem+json`: [Problem](#schema-problem) |

## Схемы данных

### Money {#schema-money}

Деньги — целое число копеек, без float

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `amountMinor` | integer (int64), ≥ 0 | да |  |
| `currency` | string: `RUB` | да |  |

### CreditPack {#schema-creditpack}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `id` | string | да |  |
| `title` | string | да |  |
| `credits` | integer | да |  |
| `price` | [Money](#schema-money) | да |  |

### Balance {#schema-balance}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `available` | integer | да | Можно потратить прямо сейчас |
| `reserved` | integer | да | Заморожено под анализы, которые ещё идут |

### Purchase {#schema-purchase}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `id` | string (uuid) | да |  |
| `packId` | string | да |  |
| `status` | string: `PENDING`, `PAID`, `FAILED` | да | - `PENDING` — ждём оплату - `PAID` — оплачено, кредиты зачислены - `FAILED` — оплата не прошла |
| `price` | [Money](#schema-money) | да |  |
| `confirmationUrl` | string (uri) | нет | Страница оплаты ЮKassa (для PENDING) |
| `createdAt` | string (date-time) | да |  |

### Reservation {#schema-reservation}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `analysisId` | string (uuid) | да |  |
| `userId` | string (uuid) | да |  |
| `amount` | integer | да |  |
| `status` | string: `RESERVED`, `COMMITTED`, `RELEASED` | да |  |

### LedgerEntry {#schema-ledgerentry}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `id` | string (uuid) | да |  |
| `delta` | integer | да | +10 при покупке, −1 при резерве, +1 при возврате резерва |
| `reason` | string: `PURCHASE`, `RESERVE`, `RELEASE` | да |  |
| `refId` | string (uuid) | да | id покупки или анализа |
| `createdAt` | string (date-time) | да |  |

### Problem {#schema-problem}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `type` | string | да |  |
| `title` | string | да |  |
| `status` | integer | да |  |
| `detail` | string | нет |  |
