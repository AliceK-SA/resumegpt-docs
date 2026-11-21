<!-- Файл сгенерирован scripts/gen_api_reference.py из docs/api/asyncapi/events.yaml. Не редактируйте вручную. -->

# События и команды (AsyncAPI)

Спецификация: [`events.yaml`](asyncapi/events.yaml) · AsyncAPI 3.0.0 · версия 1.0.0

Все асинхронные сообщения системы в одном файле.

**Транспорт.** RabbitMQ, topic-exchange `resumegpt.events`; адрес канала = routing key.
Очереди: `ai.jobs` (приоритетная, `x-max-priority = 10`), `analysis.inbox`, `billing.inbox`.
Все очереди durable, сообщения persistent, публикация с publisher confirms, получение с ручным ack.

**Гарантии — доставка «как минимум один раз» (at-least-once):**

- сервисы с базой (analysis, billing, payment) публикуют через таблицу `outbox`, которая пишется
  в той же транзакции, что и изменение данных;
- получатели с базой хранят `eventId` обработанных сообщений в таблице `inbox`
  и пропускают повторы;
- ai-worker базы не имеет: от повторной обработки задачи его защищает аренда
  (`POST /internal/analyses/{id}/lease` в analysis-service), а результат публикует напрямую
  с publisher confirms. Повтор его сообщения отсеет inbox в analysis-service.

**Порядок** сообщений не гарантируется и не нужен: получатели опираются на текущий статус
(условные UPDATE), а не на порядок прихода.

**Конверт.** Каждое сообщение — JSON с общими полями (`EventEnvelope`) и полем `data`.
`eventId` дублируется в AMQP-свойство `message_id`, `correlationId` — в `correlation_id`.

**Версионирование.** Новые поля добавляются обратно совместимо; несовместимое изменение —
новый тип сообщения с суффиксом `.v2`.

Операции `send` описывают, кто публикует, операции `receive` — кто слушает (сервис указан в тегах).

## Каналы

| Routing key | Публикует | Слушает | Назначение |
|---|---|---|---|
| `analysis.requested` | analysis-service | ai-worker | **Команда** воркерам: выполнить анализ. Попадает в приоритетную очередь `ai.jobs`. AMQP-свойство `priority`: 9 для ADVANCED, 1 для BASIC. |
| `analysis.completed` | ai-worker | analysis-service | Воркер успешно выполнил анализ. |
| `analysis.failed` | ai-worker | analysis-service | Попытка анализа не удалась. Решение «повторить или сдаться» принимает analysis-service по полю `retryable` и номеру попытки. |
| `credits.commit-requested` | analysis-service | billing-service | **Команда** billing-service: анализ удался — окончательно списать зарезервированный кредит. |
| `credits.release-requested` | analysis-service | billing-service | **Команда** billing-service: анализ не удался — вернуть зарезервированный кредит (компенсация). |
| `payment.succeeded` | payment-service | billing-service | Оплата покупки прошла — пора зачислять кредиты. |
| `payment.failed` | payment-service | billing-service | Оплата покупки не прошла (отказ банка, отмена, истёк срок). |

## Сообщения

### analysis.requested

**Выполнить анализ**

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `eventId` | string (uuid) | да | Уникальный id сообщения — ключ дедупликации в inbox получателя |
| `eventType` | string | да | Совпадает с routing key |
| `occurredAt` | string (date-time) | да |  |
| `correlationId` | string (uuid) | да | analysisId или purchaseId — по нему собираются все логи одного процесса |
| `producer` | string: `analysis-service`, `ai-worker`, `billing-service`, `payment-service` | да |  |
| `data` | object | да |  |
| `data.analysisId` | string (uuid) | да |  |
| `data.attempt` | integer, ≥ 1, ≤ 3 | да |  |
| `data.mode` | [AnalysisMode](#schema-analysismode) | да |  |
| `data.userId` | string (uuid) | да |  |
| `data.resumeObjectKey` | string | да | Путь к файлу в MinIO (в сообщении только ссылка, не сам файл) |
| `data.vacancyUrl` | string (uri) | да |  |

Пример (advanced):

```json
{
  "eventId": "4c1f8a52-0d2e-4b8b-9a3e-7f6d5c4b3a21",
  "eventType": "analysis.requested",
  "occurredAt": "2026-11-20T16:30:00Z",
  "correlationId": "2b7c9e10-5a4d-4f3b-8c2e-1d0f9a8b7c6d",
  "producer": "analysis-service",
  "data": {
    "analysisId": "2b7c9e10-5a4d-4f3b-8c2e-1d0f9a8b7c6d",
    "attempt": 1,
    "mode": "ADVANCED",
    "userId": "9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f",
    "resumeObjectKey": "9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f/2b7c9e10-5a4d-4f3b-8c2e-1d0f9a8b7c6d/Ivanova_CV.pdf",
    "vacancyUrl": "https://hh.ru/vacancy/123456789"
  }
}
```

### analysis.completed

**Анализ выполнен**

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `eventId` | string (uuid) | да | Уникальный id сообщения — ключ дедупликации в inbox получателя |
| `eventType` | string | да | Совпадает с routing key |
| `occurredAt` | string (date-time) | да |  |
| `correlationId` | string (uuid) | да | analysisId или purchaseId — по нему собираются все логи одного процесса |
| `producer` | string: `analysis-service`, `ai-worker`, `billing-service`, `payment-service` | да |  |
| `data` | object | да |  |
| `data.analysisId` | string (uuid) | да |  |
| `data.attempt` | integer | да |  |
| `data.workerId` | string | да |  |
| `data.leaseToken` | string (uuid) | да | Идентификатор конкретной аренды, выданный analysis-service |
| `data.model` | string | да |  |
| `data.tokensUsed` | integer | нет | Для учёта расходов на LLM |
| `data.result` | [AnalysisResult](#schema-analysisresult) | да |  |

### analysis.failed

**Попытка анализа не удалась**

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `eventId` | string (uuid) | да | Уникальный id сообщения — ключ дедупликации в inbox получателя |
| `eventType` | string | да | Совпадает с routing key |
| `occurredAt` | string (date-time) | да |  |
| `correlationId` | string (uuid) | да | analysisId или purchaseId — по нему собираются все логи одного процесса |
| `producer` | string: `analysis-service`, `ai-worker`, `billing-service`, `payment-service` | да |  |
| `data` | object | да |  |
| `data.analysisId` | string (uuid) | да |  |
| `data.attempt` | integer | да |  |
| `data.workerId` | string | да |  |
| `data.leaseToken` | string (uuid) | да | Идентификатор конкретной аренды, выданный analysis-service |
| `data.reason` | string: `VACANCY_NOT_FOUND`, `RESUME_UNREADABLE`, `AI_UNAVAILABLE`, `VACANCY_SOURCE_UNAVAILABLE`, `AI_INVALID_RESPONSE` | да | - `VACANCY_NOT_FOUND` — hh.ru вернул 404 (не повторяем) - `RESUME_UNREADABLE` — текст не извлекается (не повторяем) - `AI_UNAVAILABLE` — Groq: 5xx, 429 или таймаут после внутренних повторов (повторяем) - `VACANCY_SOURCE_UNAVAILABLE` — hh.ru: 5xx или таймаут (повторяем) - `AI_INVALID_RESPONSE` — ответ модели не прошёл проверку схемы (повторяем) |
| `data.retryable` | boolean | да |  |
| `data.detail` | string | нет |  |

Пример (groq-rate-limit):

```json
{
  "eventId": "7d2e1c0b-9a8f-4e7d-8c6b-5a4f3e2d1c0b",
  "eventType": "analysis.failed",
  "occurredAt": "2026-11-20T16:31:40Z",
  "correlationId": "2b7c9e10-5a4d-4f3b-8c2e-1d0f9a8b7c6d",
  "producer": "ai-worker",
  "data": {
    "analysisId": "2b7c9e10-5a4d-4f3b-8c2e-1d0f9a8b7c6d",
    "attempt": 1,
    "workerId": "ai-worker-7c9f",
    "leaseToken": "e1cda31a-310b-4324-8a51-c0a89269d426",
    "reason": "AI_UNAVAILABLE",
    "retryable": true,
    "detail": "Groq 429 Too Many Requests после 3 внутренних повторов"
  }
}
```

### credits.commit-requested

**Списать кредит**

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `eventId` | string (uuid) | да | Уникальный id сообщения — ключ дедупликации в inbox получателя |
| `eventType` | string | да | Совпадает с routing key |
| `occurredAt` | string (date-time) | да |  |
| `correlationId` | string (uuid) | да | analysisId или purchaseId — по нему собираются все логи одного процесса |
| `producer` | string: `analysis-service`, `ai-worker`, `billing-service`, `payment-service` | да |  |
| `data` | object | да |  |
| `data.analysisId` | string (uuid) | да |  |
| `data.userId` | string (uuid) | да |  |

### credits.release-requested

**Вернуть кредит**

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `eventId` | string (uuid) | да | Уникальный id сообщения — ключ дедупликации в inbox получателя |
| `eventType` | string | да | Совпадает с routing key |
| `occurredAt` | string (date-time) | да |  |
| `correlationId` | string (uuid) | да | analysisId или purchaseId — по нему собираются все логи одного процесса |
| `producer` | string: `analysis-service`, `ai-worker`, `billing-service`, `payment-service` | да |  |
| `data` | object | да |  |
| `data.analysisId` | string (uuid) | да |  |
| `data.userId` | string (uuid) | да |  |
| `data.reason` | string: `VACANCY_NOT_FOUND`, `RESUME_UNREADABLE`, `AI_UNAVAILABLE`, `ATTEMPTS_EXHAUSTED`, `RESERVATION_TIMEOUT` | да |  |

### payment.succeeded

**Оплата прошла**

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `eventId` | string (uuid) | да | Уникальный id сообщения — ключ дедупликации в inbox получателя |
| `eventType` | string | да | Совпадает с routing key |
| `occurredAt` | string (date-time) | да |  |
| `correlationId` | string (uuid) | да | analysisId или purchaseId — по нему собираются все логи одного процесса |
| `producer` | string: `analysis-service`, `ai-worker`, `billing-service`, `payment-service` | да |  |
| `data` | object | да |  |
| `data.paymentId` | string (uuid) | да |  |
| `data.purchaseId` | string (uuid) | да |  |
| `data.userId` | string (uuid) | да |  |
| `data.amount` | [Money](#schema-money) | да |  |

Пример (example):

```json
{
  "eventId": "0b8d3c5e-6a43-4c39-9a51-3b7f2f8c1a10",
  "eventType": "payment.succeeded",
  "occurredAt": "2026-11-20T16:20:05Z",
  "correlationId": "6f1c2a9e-1d5b-4f3e-8a7c-2b9d0e4f5a61",
  "producer": "payment-service",
  "data": {
    "paymentId": "3a7e9b21-4c8d-4e6f-9b0a-1c2d3e4f5a6b",
    "purchaseId": "6f1c2a9e-1d5b-4f3e-8a7c-2b9d0e4f5a61",
    "userId": "9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f",
    "amount": {
      "amountMinor": 7900,
      "currency": "RUB"
    }
  }
}
```

### payment.failed

**Оплата не прошла**

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `eventId` | string (uuid) | да | Уникальный id сообщения — ключ дедупликации в inbox получателя |
| `eventType` | string | да | Совпадает с routing key |
| `occurredAt` | string (date-time) | да |  |
| `correlationId` | string (uuid) | да | analysisId или purchaseId — по нему собираются все логи одного процесса |
| `producer` | string: `analysis-service`, `ai-worker`, `billing-service`, `payment-service` | да |  |
| `data` | object | да |  |
| `data.paymentId` | string (uuid) | да |  |
| `data.purchaseId` | string (uuid) | да |  |
| `data.reason` | string: `DECLINED_BY_BANK`, `CANCELED`, `EXPIRED` | да |  |

## Схемы данных

### Uuid {#schema-uuid}

Тип: string (uuid)

### Money {#schema-money}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `amountMinor` | integer (int64), ≥ 0 | да |  |
| `currency` | string: `RUB` | да |  |

### AnalysisMode {#schema-analysismode}

Значения: `BASIC`, `ADVANCED`.

### EventEnvelope {#schema-eventenvelope}

Общие поля любого сообщения

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `eventId` | string (uuid) | да | Уникальный id сообщения — ключ дедупликации в inbox получателя |
| `eventType` | string | да | Совпадает с routing key |
| `occurredAt` | string (date-time) | да |  |
| `correlationId` | string (uuid) | да | analysisId или purchaseId — по нему собираются все логи одного процесса |
| `producer` | string: `analysis-service`, `ai-worker`, `billing-service`, `payment-service` | да |  |

### AnalysisResult {#schema-analysisresult}

Та же схема, что в OpenAPI analysis-service

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `atsScore` | integer, ≥ 0, ≤ 100 | да |  |
| `matchedSkills` | массив из string | да |  |
| `missingSkills` | массив из string | да |  |
| `issues` | массив из object | да |  |
| `issues[].severity` | string: `HIGH`, `MEDIUM`, `LOW` | да |  |
| `issues[].text` | string | да |  |
| `suggestions` | массив из object | да |  |
| `suggestions[].original` | string | да |  |
| `suggestions[].improved` | string | да |  |
| `coverLetter` | string | нет |  |
