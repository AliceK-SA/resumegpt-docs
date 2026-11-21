<!-- Файл сгенерирован scripts/gen_api_reference.py из docs/api/openapi/payment-service.yaml. Не редактируйте вручную. -->

# payment-service

Спецификация: [`payment-service.yaml`](openapi/payment-service.yaml) · OpenAPI 3.0.3 · версия API 1.0.0

Платежи через ЮKassa. Единственный сервис, который знает о провайдере (Anti-Corruption Layer):
наружу отдаёт только наши статусы. О кредитах и резюме ничего не знает — проводит платёж
«по покупке на сумму».

**Защита от двойного списания и потери оплаты:**

1. Один платёж на покупку — уникальный индекс `payments(purchase_id)`. Повторный
   `POST /payments` по той же покупке возвращает существующий платёж.
2. Запрос к ЮKassa отправляется с заголовком `Idempotence-Key = payment.id` — повтор после
   таймаута не создаёт второй платёж у провайдера.
3. Вебхук применяется условным UPDATE (`... WHERE status = 'PENDING'`): повторный вебхук ничего
   не меняет и событие второй раз не публикует.
4. Если вебхук не дошёл, `reconciliation-worker` раз в минуту сам спрашивает ЮKassa о платежах,
   которые висят в `PENDING` дольше 2 минут.

    Восстановление после неопределённого ответа ЮKassa: наличие локального PENDING не означает,
    что внешний платёж создан. Повторное обращение с тем же Idempotence-Key до получения
    providerPaymentId/confirmationUrl безопасно. Reconciliation отдельно обрабатывает
    записи без providerPaymentId: в пределах первых 24 часов со времени исходного
    запроса повторяет создание с тем же ключом, затем сверяет статус по известному
    идентификатору. ЮKassa гарантирует действие ключа лишь 24 часа: по истечении срока
    без providerPaymentId новый запрос создания автоматически не выполняется, запись
    переводится на ручную сверку, чтобы не создать дублирующий внешний платёж.
    Перезапись другого ключа запрещена.

## Адреса

| Адрес | Назначение |
|---|---|
| `http://payment-service:8080` | Внутренний адрес (docker-compose) |

## Операции

| Метод и путь | Назначение | Ответы |
|---|---|---|
| `POST /payments` | Создать платёж по покупке (или вернуть существующий) | 200, 201, 422, 502, 401, 403 |
| `GET /payments/{paymentId}` | Платёж по id | 200, 404, 401, 403 |
| `POST /webhooks/yookassa` | Уведомление ЮKassa о смене статуса платежа | 200, 401 |

### POST /payments

**Создать платёж по покупке (или вернуть существующий)**

Если по purchaseId есть PENDING без confirmationUrl/providerPaymentId, операция
не возвращает его как окончательно созданный платёж. Сервис повторяет запрос к ЮKassa с тем
же `Idempotence-Key=payment.id`, атомарно сохраняет providerPaymentId и confirmationUrl,
а при неизвестном исходе сохраняет PENDING и планирует восстановление.
Для уже созданного платежа возвращается 200 без нового внешнего платежа.

`operationId`: `createPayment` · тег: Payments

**Тело запроса** (`application/json`)

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `purchaseId` | string (uuid) | да |  |
| `userId` | string (uuid) | да |  |
| `amount` | [Money](#schema-money) | да |  |
| `description` | string | нет |  |
| `returnUrl` | string (uri) | да |  |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `200` | Существующий платёж с подтверждённым внешним идентификатором и ссылкой либо с окончательным статусом | `application/json`: [Payment](#schema-payment) |
| `201` | Платёж создан в ЮKassa | `application/json`: [Payment](#schema-payment) |
| `422` | Ошибка валидации | `application/problem+json`: [Problem](#schema-problem) |
| `502` | Ответ провайдера неизвестен; локальный PENDING будет восстановлен тем же ключом, ссылка пока не возвращается | `application/problem+json`: [Problem](#schema-problem) |
| `401` | Токен отсутствует, недействителен или истёк | `application/problem+json`: [Problem](#schema-problem) |
| `403` | Доступ к ресурсу или операции запрещён | `application/problem+json`: [Problem](#schema-problem) |

### GET /payments/{paymentId}

**Платёж по id**

`operationId`: `getPayment` · тег: Payments

**Параметры**

| Имя | Где | Тип | Обязательный | Описание |
|---|---|---|---|---|
| `paymentId` | path | string (uuid) | да |  |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `200` | OK | `application/json`: [Payment](#schema-payment) |
| `404` | Не найдено | `application/problem+json`: [Problem](#schema-problem) |
| `401` | Токен отсутствует, недействителен или истёк | `application/problem+json`: [Problem](#schema-problem) |
| `403` | Доступ к ресурсу или операции запрещён | `application/problem+json`: [Problem](#schema-problem) |

### POST /webhooks/yookassa

**Уведомление ЮKassa о смене статуса платежа**

1. Проверить, что запрос пришёл с IP-адресов ЮKassa. Иначе — `401`.
2. Сохранить уведомление как есть в `provider_notifications`.
3. **Не доверять телу:** запросить актуальный статус платежа у ЮKassa по `object.id`.
4. Одной транзакцией: условно обновить платёж и записать событие в outbox.
5. Ответить `200`. При любом другом ответе ЮKassa повторит уведомление позже —
   это безопасно благодаря пункту 4.

Webhook не использует JWT пользователя; проверка источника и независимое чтение статуса из ЮKassa обязательны.

`operationId`: `handleYookassaWebhook` · тег: Webhooks

**Тело запроса** (`application/json`)

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `type` | string | да |  |
| `event` | string: `payment.succeeded`, `payment.canceled` | да |  |
| `object` | object | да |  |
| `object.id` | string | да | id платежа в ЮKassa |
| `object.status` | string | да |  |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `200` | Принято (в том числе повторное уведомление) | — |
| `401` | Запрос не от ЮKassa | — |

## Схемы данных

### Money {#schema-money}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `amountMinor` | integer (int64), ≥ 1 | да |  |
| `currency` | string: `RUB` | да |  |

### PaymentStatus {#schema-paymentstatus}

- `PENDING` — создан, ждём оплату
- `SUCCEEDED` — деньги получены
- `FAILED` — отклонён банком, отменён или истёк

Значения: `PENDING`, `SUCCEEDED`, `FAILED`.

### CreatePaymentRequest {#schema-createpaymentrequest}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `purchaseId` | string (uuid) | да |  |
| `userId` | string (uuid) | да |  |
| `amount` | [Money](#schema-money) | да |  |
| `description` | string | нет |  |
| `returnUrl` | string (uri) | да |  |

### Payment {#schema-payment}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `id` | string (uuid) | да |  |
| `purchaseId` | string (uuid) | да |  |
| `status` | [PaymentStatus](#schema-paymentstatus) | да |  |
| `amount` | [Money](#schema-money) | да |  |
| `confirmationUrl` | string (uri) | нет | Ссылка на страницу оплаты (для PENDING) |
| `providerPaymentId` | string | нет | id платежа в ЮKassa |
| `createdAt` | string (date-time) | да |  |

### YookassaNotification {#schema-yookassanotification}

Формат уведомления ЮKassa (упрощённо)

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `type` | string | да |  |
| `event` | string: `payment.succeeded`, `payment.canceled` | да |  |
| `object` | object | да |  |
| `object.id` | string | да | id платежа в ЮKassa |
| `object.status` | string | да |  |

### Problem {#schema-problem}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `type` | string | да |  |
| `title` | string | да |  |
| `status` | integer | да |  |
| `detail` | string | нет |  |
