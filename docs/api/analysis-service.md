<!-- Файл сгенерирован scripts/gen_api_reference.py из docs/api/openapi/analysis-service.yaml. Не редактируйте вручную. -->

# analysis-service

Спецификация: [`analysis-service.yaml`](openapi/analysis-service.yaml) · OpenAPI 3.0.3 · версия API 1.0.0

Заявки на анализ резюме, их статусы и архив результатов. Оркестратор процесса анализа.

**Идемпотентность.** `POST /analyses` требует заголовок `Idempotency-Key` (UUID; клиент
генерирует его один раз на нажатие кнопки «Анализировать»). Повтор с тем же ключом возвращает
ту же заявку — второй анализ не создаётся и второй кредит не резервируется.
Ключи хранятся 24 часа.

**Пользователь.** API Gateway проверяет JWT и передаёт `X-User-Id`.
Заявка видна только своему владельцу.

**Внутренний API** (`/internal/...`) доступен только из сети сервисов, наружу через Gateway не публикуется.

## Адреса

| Адрес | Назначение |
|---|---|
| `http://analysis-service:8080` | Внутренний адрес (docker-compose) |
| `http://localhost:8000/api` | Через API Gateway (только публичные методы) |

## Операции

| Метод и путь | Назначение | Ответы |
|---|---|---|
| `POST /analyses` | Запустить анализ резюме под вакансию | 202, 402, 413, 422, 503, 401, 403, 429 |
| `GET /analyses` | Архив анализов пользователя | 200, 401, 403 |
| `GET /analyses/{analysisId}` | Статус и результат анализа | 200, 404, 401, 403 |
| `POST /internal/analyses/{analysisId}/lease` | Воркер арендует задачу перед началом работы | 200, 409, 401 |
| `POST /internal/analyses/{analysisId}/lease/renew` | Продлить действующую аренду во время обработки | 200, 401, 409 |

### POST /analyses

**Запустить анализ резюме под вакансию**

1. Сохраняет файл в MinIO и создаёт заявку `CREATED`.
2. Для режима `ADVANCED` синхронно резервирует 1 кредит в billing-service
   (ключ резерва = `analysisId`, повтор безопасен).
3. Переводит заявку в `QUEUED` и одной транзакцией пишет в outbox команду
   `analysis.requested` (приоритет 9 для ADVANCED, 1 для BASIC).

Ответ `202 Accepted`: анализ выполняется асинхронно, клиент опрашивает `GET /analyses/{id}`.

Ограничение Gateway: не более 10 новых анализов в минуту на пользователя; `429` и `Retry-After` при превышении.

`operationId`: `createAnalysis` · тег: Analyses

**Параметры**

| Имя | Где | Тип | Обязательный | Описание |
|---|---|---|---|---|
| `Idempotency-Key` | header | string (uuid) | да |  |
| `X-User-Id` | header | string (uuid) | да | Заголовок доверенной идентичности. Браузер не задаёт его: API Gateway удаляет входящий X-User-Id и проставляет идентификатор из проверенного JWT. Внутренний сервис принимает его только от доверенного шлюза. |

**Тело запроса** (`multipart/form-data`)

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `resume` | string (binary) | да | PDF или DOCX, не больше 5 МБ |
| `vacancyUrl` | string (uri) | да |  |
| `mode` | [AnalysisMode](#schema-analysismode) | да |  |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `202` | Заявка принята | `application/json`: [Analysis](#schema-analysis) |
| `402` | Недостаточно кредитов для продвинутого анализа | `application/problem+json`: [Problem](#schema-problem) |
| `413` | Файл больше 5 МБ | `application/problem+json`: [Problem](#schema-problem) |
| `422` | Неподдерживаемый формат файла или ссылка не на hh.ru | `application/problem+json`: [Problem](#schema-problem) |
| `503` | billing-service недоступен — продвинутый анализ сейчас запустить нельзя. Базовый анализ (`mode = BASIC`) от billing-service не зависит и работает. | `application/problem+json`: [Problem](#schema-problem) |
| `401` | Токен отсутствует, недействителен или истёк | `application/problem+json`: [Problem](#schema-problem) |
| `403` | Доступ к ресурсу или операции запрещён | `application/problem+json`: [Problem](#schema-problem) |
| `429` | Шлюз ограничивает запуск до 10 анализов в минуту на пользователя | `application/problem+json`: [Problem](#schema-problem) |

### GET /analyses

**Архив анализов пользователя**

`operationId`: `listAnalyses` · тег: Analyses

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

### GET /analyses/{analysisId}

**Статус и результат анализа**

Клиент опрашивает раз в 2 секунды, пока статус не станет COMPLETED или FAILED.

`operationId`: `getAnalysis` · тег: Analyses

**Параметры**

| Имя | Где | Тип | Обязательный | Описание |
|---|---|---|---|---|
| `analysisId` | path | string (uuid) | да |  |
| `X-User-Id` | header | string (uuid) | да | Заголовок доверенной идентичности. Браузер не задаёт его: API Gateway удаляет входящий X-User-Id и проставляет идентификатор из проверенного JWT. Внутренний сервис принимает его только от доверенного шлюза. |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `200` | OK | `application/json`: [Analysis](#schema-analysis) |
| `404` | Не найдено (или принадлежит другому пользователю) | `application/problem+json`: [Problem](#schema-problem) |
| `401` | Токен отсутствует, недействителен или истёк | `application/problem+json`: [Problem](#schema-problem) |
| `403` | Доступ к ресурсу или операции запрещён | `application/problem+json`: [Problem](#schema-problem) |

### POST /internal/analyses/{analysisId}/lease

**Воркер арендует задачу перед началом работы**

Атомарно выдать одну аренду: условный UPDATE по id, status=QUEUED и attempt.
В ответе выдаётся новый UUID leaseToken, он хранится вместе с lease_owner и lease_until.
Первоначальная длительность аренды: 240 с. Воркер подтверждает сообщение после аренды,
а затем продлевает её отдельным запросом до истечения. По завершении результата событие
должно содержать attempt, workerId и leaseToken: совпадение всех полей и действующая
аренда проверяются перед фиксацией COMPLETED/FAILED. Результат старой попытки отклоняется.
Внешние обращения ограничены общим дедлайном, продление аренды не бесконечно.
Это гарантирует одно окончательное изменение состояния, но не исключает повторный вызов Groq.

`operationId`: `leaseAnalysis` · тег: Internal

**Параметры**

| Имя | Где | Тип | Обязательный | Описание |
|---|---|---|---|---|
| `analysisId` | path | string (uuid) | да |  |

**Тело запроса** (`application/json`)

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `workerId` | string | да |  |
| `attempt` | integer, ≥ 1 | да | Номер попытки из сообщения analysis.requested |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `200` | Аренда выдана (leaseToken и leaseUntil) | `application/json`: [LeaseGrant](#schema-leasegrant) |
| `409` | Задача недоступна (уже в работе, завершена или попытка устарела) | `application/problem+json`: [Problem](#schema-problem) |
| `401` | Токен отсутствует, недействителен или истёк | `application/problem+json`: [Problem](#schema-problem) |

### POST /internal/analyses/{analysisId}/lease/renew

**Продлить действующую аренду во время обработки**

Продление разрешено только владельцу текущей аренды с тем же attempt и leaseToken. Следующее leaseUntil не может превышать общий дедлайн попытки. Неверный/истёкший токен даёт 409.

`operationId`: `renewAnalysisLease` · тег: Internal

**Параметры**

| Имя | Где | Тип | Обязательный | Описание |
|---|---|---|---|---|
| `analysisId` | path | string (uuid) | да |  |

**Тело запроса** (`application/json`)

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `workerId` | string | да |  |
| `attempt` | integer, ≥ 1 | да |  |
| `leaseToken` | string (uuid) | да |  |

**Ответы**

| Код | Описание | Тело |
|---|---|---|
| `200` | Аренда продлена | `application/json`: [LeaseGrant](#schema-leasegrant) |
| `401` | Неавторизованный сервис | `application/problem+json`: [Problem](#schema-problem) |
| `409` | Аренда истекла, уже принадлежит другой попытке или превышен дедлайн | `application/problem+json`: [Problem](#schema-problem) |

## Схемы данных

### AnalysisMode {#schema-analysismode}

- `BASIC` — бесплатно, общая очередь, базовая модель
- `ADVANCED` — 1 кредит, приоритет в очереди, продвинутая модель, сопроводительное письмо

Значения: `BASIC`, `ADVANCED`.

### AnalysisStatus {#schema-analysisstatus}

- `CREATED` — файл сохранён, для ADVANCED резервируется кредит
- `QUEUED` — задача в очереди
- `PROCESSING` — воркер арендовал задачу и работает
- `COMPLETED` — результат готов
- `FAILED` — анализ не удался; для ADVANCED кредит возвращается

Значения: `CREATED`, `QUEUED`, `PROCESSING`, `COMPLETED`, `FAILED`.

### CreditStatus {#schema-creditstatus}

Судьба кредита глазами analysis-service:

- `NOT_REQUIRED` — базовый анализ
- `RESERVED` — кредит заморожен
- `CHARGED` — анализ удался, отправлена команда на списание
- `RETURNED` — анализ не удался, отправлена команда на возврат

Команды доставляются гарантированно (outbox), поэтому `CHARGED` и `RETURNED` — окончательные.

Значения: `NOT_REQUIRED`, `RESERVED`, `CHARGED`, `RETURNED`.

### FailureReason {#schema-failurereason}

- `VACANCY_NOT_FOUND` — вакансия удалена или ссылка неверная
- `RESUME_UNREADABLE` — не удалось извлечь текст (скан без текста, битый файл)
- `AI_UNAVAILABLE` — Groq не ответил за все попытки
- `ATTEMPTS_EXHAUSTED` — воркеры падали на этой задаче 3 раза подряд
- `RESERVATION_TIMEOUT` — не удалось зарезервировать кредит за 10 минут

Значения: `VACANCY_NOT_FOUND`, `RESUME_UNREADABLE`, `AI_UNAVAILABLE`, `ATTEMPTS_EXHAUSTED`, `RESERVATION_TIMEOUT`.

### Analysis {#schema-analysis}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `id` | string (uuid) | да |  |
| `mode` | [AnalysisMode](#schema-analysismode) | да |  |
| `status` | [AnalysisStatus](#schema-analysisstatus) | да |  |
| `creditStatus` | [CreditStatus](#schema-creditstatus) | да |  |
| `vacancyUrl` | string (uri) | да |  |
| `resumeFileName` | string | нет |  |
| `attempt` | integer | нет | Номер текущей попытки (1–3) |
| `failureReason` | [FailureReason](#schema-failurereason) | нет |  |
| `result` | [AnalysisResult](#schema-analysisresult) | нет |  |
| `createdAt` | string (date-time) | да |  |
| `completedAt` | string (date-time) | нет |  |

### AnalysisResult {#schema-analysisresult}

Строгая схема результата. ai-worker проверяет ответ LLM на соответствие ей.

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `atsScore` | integer, ≥ 0, ≤ 100 | да | Оценка совместимости с ATS |
| `matchedSkills` | массив из string | да |  |
| `missingSkills` | массив из string | да |  |
| `issues` | массив из object | да |  |
| `issues[].severity` | string: `HIGH`, `MEDIUM`, `LOW` | да |  |
| `issues[].text` | string | да |  |
| `suggestions` | массив из object | да | Конкретные переформулировки |
| `suggestions[].original` | string | да |  |
| `suggestions[].improved` | string | да |  |
| `coverLetter` | string | нет | Только для ADVANCED |
| `model` | string | нет | Какая модель делала анализ |

### LeaseGrant {#schema-leasegrant}

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `analysisId` | string (uuid) | да |  |
| `attempt` | integer | да |  |
| `leaseUntil` | string (date-time) | да | Если к этому моменту нет результата, watchdog вернёт задачу в очередь |
| `mode` | [AnalysisMode](#schema-analysismode) | да |  |
| `resumeObjectKey` | string | да | Путь к файлу в бакете MinIO resumes |
| `vacancyUrl` | string (uri) | да |  |
| `leaseToken` | string (uuid) | да | Токен текущей аренды (fencing), требуется в событиях результата |

### Problem {#schema-problem}

Ошибка в формате RFC 9457 (Problem Details)

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `type` | string | да |  |
| `title` | string | да |  |
| `status` | integer | да |  |
| `detail` | string | нет |  |
