# Соответствие функций исходной версии и v2

Сравнение выполнено с `main@51f9a79`. Основой реестра служит фактическая таблица маршрутизации Flask после инициализации приложения на временной SQLite. Каждая строка ниже соответствует одному именованному правилу. Проверялись URL, метод, имя конечной точки и реальные результаты ответов. Один URL может поддерживать несколько пользовательских действий или редактируемых сущностей.

## Рабочие сценарии и проверки результата

| Возможность | Вход v1 → вход v2 | Проверенный результат, ограничения и профильные тесты |
|---|---|---|
| Выбрать/создать объект, изменить карточку, архивировать и восстановить | Объекты и объёмы → Администрирование, переключатель объекта | Смена рабочего пространства сохраняется в сессии. Форма предыдущего объекта получила 403 в двух вкладках Chromium, количество фактов осталось прежним. Создание и ограничения чужой области проверяет `test_project_web.py`. |
| Корпуса, этажи, кодификатор, нормы | Объекты и объёмы → Администрирование | Сохранены добавление и редактирование корпуса, сортировка этажей, удаление пустого с явной отметкой, просмотр зависимостей и архивирование занятого, создание кода и редакции норм. Chromium проверил безопасное удаление временного корпуса. См. `test_building_management.py`, `test_web.py`. |
| Позиции ведомости, исторические версии и утверждение | Объекты и объёмы → Производство → Ведомости | Направление, корпус и этаж определяют позицию. Доступны черновик от источника, ввод плана/нормы в строке, удаление из черновика, утверждение версии, выбор предшествующей версии и среза. См. `test_versions.py`, `test_historical.py`, `test_web.py`. |
| Факт и подтверждение, документ, корректировка, просмотр среза | Производство → быстрые действия или Производство | Chromium создал два независимых события по 5 единиц без наряда, проверил объём по SQLite и доступность исторического журнала только для чтения. Серверные тесты проверяют отрицательные и повторные записи, дату, доступный остаток и связь корректировки с источником. См. `test_events.py`, `test_event_flow.py`, `test_work_order_flow_web.py`. |
| Черновик и выдача наряда | Реестр нарядов → Главная → Создать наряд, либо реестр | Выбраны работа и объём из утверждённого плана, подрядчик, ответственные и постоянная бригада. После отдельной выдачи статус в SQLite стал `issued`. Числа событий факта, подтверждения и записей табеля до/после выдачи совпали. Ключи/ревизии и неизменяемые реквизиты проверяют `test_work_order_web.py`, `test_work_orders.py`. |
| Исполнение, сдача, приёмка, закрытие и история наряда | Производство → Производство | Доступна регистрация связанного события, частичное исполнение, построчная проверка, повторная проверка, закрытие, отмена, исторический документ и печать. Решение принимается только для допустимого статуса, принятие наряда самостоятельно не создаёт подтверждённый объём. См. `test_work_order_flow.py`, `test_work_order_flow_web.py`, `test_work_order_control_review.py`. |
| Перенос/списание остатка, сопоставление записей, контроль | Контроль нарядов → Производство → Контроль нарядов и карточка | Существуют предпросмотр и создание нового черновика переноса, отмена безопасного переноса, явное списание с причиной и его отзыв, связь с записью без исходного наряда, реестр цепочек и XLSX. См. `test_work_order_transfers.py`, `test_work_order_control_projection.py`, `test_work_order_control_registry.py`, `test_work_order_control_web.py`. |
| Подрядчики, работники, специальности, бригады, доступность | Персонал и бригады + Справочники → Люди и время + Администрирование | Сохранены редактирование, статус, общая специальность, доступность подрядчика для другого объекта, привязка работника, назначения в бригаду, истории и состав на дату. В Chromium повторно открыто длинное кириллическое ФИО, штатными формами изменены назначение и доступность работника. См. `test_personnel_web.py`, `test_personnel.py`. |
| Импорт реестра персонала | Персонал и бригады → Люди и время | Шаблон XLSX, загрузка, сопоставление, просмотр, повторное применение, отмена и история используют существующую сессию импорта. См. `test_personnel_import.py`, `test_personnel_web.py`. |
| Табель, массовый ввод, версии, импорт/экспорт | Рабочее время → Главная или Люди и время | Браузер записал 6 часов явки в выбранную ячейку, открыл редактируемый черновик и создал отдельный табель из отбора. Профильные тесты проверяют отсутствие/ноль, отклонения, состав по дате, копирование диапазона, комментарий/примечание, предпросмотр и согласие, передачу, утверждение, возврат, отмену, корректирующую версию и прошлую версию. См. `test_timesheet_web.py`, `test_timesheets.py`, `test_timesheet_xlsx_integration.py`. |
| Распределение труда, атрибуция и выработка | Производительность → Главная или Эффективность | Отдельные формы для единичного и массового назначения часов, подтверждения предпросмотра, отзыва и атрибуции объёмов. Доступны нормы, фактические/распределённые часы, работа, бригада, подрядчик, неполные данные, конфликт, история и Excel. Chromium сменил фактический журнал на подтверждённый с сохранением отбора подрядчика. См. `test_labor_allocations.py`, `test_labor_productivity_analytics.py`, `test_labor_productivity_web.py`, `test_labor_concurrency.py`. |
| Условия оплаты, тарифы, операции и расценки | Начисления → Начисления, быстрый вход из Главной | Сохранены версии условий и расценок, валюта/единица, действие в периоде, надбавки и премии; технологическая операция привязана к коду работы. См. `test_payroll_rules.py`, `test_payroll_web.py`. |
| Сдельное распределение и начисления, расчётные периоды | Начисления → Начисления | Сохраняются связь с подтверждённым объёмом, выбранный метод распределения, проверка долей, стадия предпросмотра, отдельное применение или отмена партии. Chromium создал период с явной нормой 160 часов. Проверены настройки периода, расчёт, ручные корректировки/премии, передача/возврат, утверждение, закрытие, коррекция, неизменяемые снимки, Excel. См. `test_payroll_piece.py`, `test_payroll_calculator.py`, `test_payroll_periods.py`, `test_payroll_review.py`, `test_payroll_web.py`. |
| Отчёты и экспорт | Аналитика → Аналитика | Сводка физической готовности, натуральные объёмы, группы, динамика, отклонения и экспорт. Даты и версии групп влияют на срез. Chromium получил настоящий XLSX; профильный набор проверяет содержимое листов и значения. См. `test_analytics.py`, `test_analytics_web.py`. |
| Настройки, локальный сервер, резервирование | Настройки и нижняя панель → Администрирование / локальное завершение | Сохраняются режим локального запуска, диагностические параметры и защищённый POST завершения. Portable контролирует собственный служебный маршрут. Резервная копия SQLite хранит снимок транзакций. См. `test_launch.py`, `test_windows_server.py`, `test_windows_storage.py`. Порядок облачного резервирования и допусков приведён в [руководстве](v2_yandex_cloud_deployment.md). |
| Пользователи и роли | Этап 4.6 отсутствует в v1 и v2 | В проверенном графе маршрутов и миграциях 001–013 отсутствуют учётные записи, экран входа и ролевая защита табелей/начислений. Область объекта, CSRF и локальные проверки HTTP сохранены. Для публичного контура с персональными данными требуется отдельная реализация и проверка доступа. |

## Сопоставление HTTP

Канонический путь в таблице одинаков в обеих версиях. Значения в колонках — коды ответов, полученные при выполнении профильных тестов Flask и браузерных проверок. 200 — успешное представление, JSON или файл, 303 — возврат после изменения, 400/403/404 и другие отказы — результаты включённых отрицательных проверок. Наличие позитивного ответа подтверждает доступность конкретной пары URL и метода. Варианты переданных полей и проверяемые бизнес-инварианты раскрыты в таблице сценариев выше. Служебные HEAD и OPTIONS Flask добавляет автоматически.

| Flask endpoint | Путь v1 и v2 | Метод | Ответ v1 | Ответ v2 |
|---|---|---|---|---|
| `dashboard.index` | `/` | GET | 200, 403 | 200, 403 |
| `analytics.index` | `/analytics` | GET | 200, 400 | 200, 400 |
| `analytics.index` | `/analytics/<tab>` | GET | 200 | 200 |
| `analytics.download` | `/analytics/export.xlsx` | GET | 200 | 200 |
| `analytics.group_form` | `/analytics/groups/<int:group_id>` | GET | 200, 400 | 200, 400 |
| `analytics.group_form` | `/analytics/groups/<int:group_id>` | POST | 303, 400 | 303, 400 |
| `analytics.group_action` | `/analytics/groups/<int:group_id>/actions` | POST | 303 | 303 |
| `analytics.group_form` | `/analytics/groups/new` | GET | 200 | 200 |
| `analytics.group_form` | `/analytics/groups/new` | POST | 303, 403 | 303, 403 |
| `buildings.listing` | `/api/buildings` | GET | 200 | 200 |
| `buildings.index` | `/buildings` | GET | 200, 500 | 200, 500 |
| `buildings.change_floor` | `/buildings/floors` | POST | 303, 400, 403 | 303, 400, 403 |
| `catalog.index` | `/catalog` | GET | 200 | 200 |
| `catalog.save` | `/catalog` | POST | 303, 400 | 303, 400 |
| `catalog.save_norm` | `/catalog/norm` | POST | 303, 400 | 303, 400 |
| `events.confirmations` | `/confirmations` | GET | 200, 400 | 200, 400, 500 |
| `events.confirmations` | `/confirmations` | POST | 303, 400 | 303, 400, 500 |
| `events.facts` | `/facts` | GET | 200, 400 | 200, 400 |
| `events.facts` | `/facts` | POST | 303, 400, 403 | 303, 400, 403 |
| `labor.overview` | `/labor` | GET | 200, 400 | 200, 400 |
| `labor.allocations` | `/labor/allocations` | GET | 200 | 200 |
| `labor.allocations` | `/labor/allocations` | POST | 200, 303, 400, 403 | 200, 303, 400, 403 |
| `labor.attributions` | `/labor/attributions` | GET | 200 | 200 |
| `labor.attributions` | `/labor/attributions` | POST | 303, 400 | 303, 400 |
| `labor.brigades` | `/labor/brigades` | GET | 200 | 200 |
| `labor.contractors` | `/labor/contractors` | GET | 200 | 200 |
| `labor.export` | `/labor/export.xlsx` | GET | 200 | 200 |
| `labor.history` | `/labor/history` | GET | 200 | 200 |
| `labor.works` | `/labor/works` | GET | 200 | 200 |
| `navigation.state` | `/navigation/state` | POST | 200, 400, 403 | 200, 400, 403 |
| `payroll.overview` | `/payroll` | GET | 200 | 200 |
| `payroll.claims` | `/payroll/claims` | GET | 200 | 200 |
| `payroll.claims` | `/payroll/claims` | POST | 303, 400 | 303, 400 |
| `payroll.operations` | `/payroll/operations` | GET | 200 | 200 |
| `payroll.operations` | `/payroll/operations` | POST | 303 | 303 |
| `payroll.periods` | `/payroll/periods` | GET | 200 | 200 |
| `payroll.detail` | `/payroll/periods/<int:period_id>` | GET | 200, 400 | 200, 400 |
| `payroll.export` | `/payroll/periods/<int:period_id>/export.xlsx` | GET | 200, 400 | 200, 400 |
| `payroll.create` | `/payroll/periods/new` | GET | 200 | 200 |
| `payroll.create` | `/payroll/periods/new` | POST | 303, 400 | 303, 400 |
| `payroll.rates` | `/payroll/rates` | GET | 200 | 200 |
| `payroll.rates` | `/payroll/rates` | POST | 303 | 303 |
| `payroll.terms` | `/payroll/terms` | GET | 200 | 200 |
| `payroll.terms` | `/payroll/terms` | POST | 303, 400, 403 | 303, 400, 403 |
| `payroll.action` | `/payroll/versions/<int:version_id>/action` | POST | 303, 400, 403 | 303, 400, 403 |
| `payroll.piece_confirm` | `/payroll/versions/<int:version_id>/piece-confirm` | POST | 303, 400 | 303, 400 |
| `payroll.piece_preview` | `/payroll/versions/<int:version_id>/piece-preview` | POST | 200 | 200 |
| `personnel.index` | `/personnel` | GET | 200, 400 | 200, 400 |
| `personnel.edit` | `/personnel/<kind>/<int:record_id>/edit` | GET | 200, 400 | 200, 400 |
| `personnel.edit` | `/personnel/<kind>/<int:record_id>/edit` | POST | 303 | 303 |
| `personnel.status` | `/personnel/<kind>/<int:record_id>/status` | POST | 303, 400 | 303, 400 |
| `personnel.edit` | `/personnel/<kind>/new` | GET | 200 | 200 |
| `personnel.edit` | `/personnel/<kind>/new` | POST | 303, 400 | 303, 400 |
| `personnel_management.availability` | `/personnel/availability` | GET | 200 | 200 |
| `personnel_management.availability` | `/personnel/availability` | POST | 303 | 303 |
| `personnel_management.available_workers` | `/personnel/available-workers.json` | GET | 200 | 200 |
| `personnel_management.brigades` | `/personnel/brigades` | GET | 200 | 200 |
| `personnel_management.brigades` | `/personnel/brigades` | POST | 303 | 303 |
| `personnel_management.brigade_detail` | `/personnel/brigades/<int:brigade_id>` | GET | 200, 400 | 200, 400 |
| `personnel_management.brigade_detail` | `/personnel/brigades/<int:brigade_id>` | POST | 303, 400 | 303, 400 |
| `personnel_management.brigade_members` | `/personnel/brigades/<int:brigade_id>/members.json` | GET | 200, 400 | 200, 400 |
| `personnel_management.share` | `/personnel/contractors/<int:contractor_id>/share` | POST | 303 | 303 |
| `personnel_import.start` | `/personnel/import` | GET | 200 | 200 |
| `personnel_import.start` | `/personnel/import` | POST | 303, 403 | 303, 403 |
| `personnel_import.history` | `/personnel/import-history` | GET | 200 | 200 |
| `personnel_import.wizard` | `/personnel/import/<session_id>` | GET | 200, 400 | 200, 400 |
| `personnel_import.wizard` | `/personnel/import/<session_id>` | POST | 303, 400 | 303, 400 |
| `personnel_import.template` | `/personnel/import/template.xlsx` | GET | 200 | 200 |
| `personnel_management.workers` | `/personnel/workers` | GET | 200 | 200 |
| `personnel_management.worker_detail` | `/personnel/workers/<int:employee_id>` | GET | 200, 400 | 200, 400 |
| `personnel_management.assign` | `/personnel/workers/<int:employee_id>/assignment` | POST | 303, 400 | 303, 400 |
| `personnel_management.project_end` | `/personnel/workers/<int:employee_id>/project-end` | POST | 303 | 303 |
| `progress.index` | `/progress` | GET | 200, 400 | 200, 400 |
| `projects.index` | `/projects` | GET | 200 | 200 |
| `projects.detail` | `/projects/<int:project_id>` | GET | 200, 403 | 200, 403 |
| `projects.detail` | `/projects/<int:project_id>` | POST | 303, 403 | 303, 403 |
| `projects.buildings` | `/projects/<int:project_id>/buildings` | POST | 303, 400 | 303, 400 |
| `projects.delete_building` | `/projects/<int:project_id>/buildings/<int:building_id>/delete` | GET | 200 | 200 |
| `projects.delete_building` | `/projects/<int:project_id>/buildings/<int:building_id>/delete` | POST | 303 | 303 |
| `projects.create` | `/projects/new` | GET | 200 | 200 |
| `projects.create` | `/projects/new` | POST | 303, 400 | 303, 400 |
| `projects.select` | `/projects/select` | POST | 303 | 303 |
| `navigation.settings` | `/settings` | GET | 200 | 200 |
| `shutdown` | `/shutdown` | POST | 200, 403 | 200, 403 |
| `static` | `/static/<path:filename>` | GET | 200 | 200 |
| `timesheets.index` | `/timesheets` | GET | 200 | 200 |
| `timesheets.detail` | `/timesheets/<int:timesheet_id>` | GET | 200, 400 | 200, 400 |
| `timesheets.detail` | `/timesheets/<int:timesheet_id>` | POST | 303, 400, 403 | 303, 400, 403 |
| `timesheets.export` | `/timesheets/<int:timesheet_id>/export.xlsx` | GET | 200, 400 | 200, 400 |
| `timesheets.import_data` | `/timesheets/<int:timesheet_id>/import` | GET | 200, 400 | 200, 400 |
| `timesheets.import_data` | `/timesheets/<int:timesheet_id>/import` | POST | 303, 400 | 303, 400 |
| `timesheets.preview` | `/timesheets/<int:timesheet_id>/preview/<preview_id>` | GET | 200, 400 | 200, 400 |
| `timesheets.preview` | `/timesheets/<int:timesheet_id>/preview/<preview_id>` | POST | 303, 400 | 303, 400 |
| `timesheets.create` | `/timesheets/new` | GET | 200 | 200 |
| `timesheets.create` | `/timesheets/new` | POST | 303, 400 | 303, 400 |
| `timesheets.template` | `/timesheets/template.xlsx` | GET | 200 | 200 |
| `volumes.index` | `/volumes` | GET | 200, 400 | 200, 400 |
| `volumes.create_item` | `/volumes/items` | POST | 303, 400 | 303, 400 |
| `volumes.save_line` | `/volumes/lines` | POST | 303, 400 | 303, 400 |
| `volumes.remove_line` | `/volumes/lines/remove` | POST | 303 | 303 |
| `volumes.create_plan` | `/volumes/plans` | POST | 303, 400, 403 | 303, 400, 403 |
| `volumes.approve` | `/volumes/plans/<int:version_id>/approve` | POST | 303, 400 | 303, 400 |
| `work_orders.index` | `/work-orders` | GET | 200 | 200 |
| `work_orders.detail` | `/work-orders/<int:order_id>` | GET | 200, 400 | 200, 400 |
| `work_orders.cancel` | `/work-orders/<int:order_id>/cancel` | POST | 303, 400 | 303, 400 |
| `work_orders.edit` | `/work-orders/<int:order_id>/edit` | GET | 200, 400 | 200, 400 |
| `work_orders.edit` | `/work-orders/<int:order_id>/edit` | POST | 303, 400 | 303, 400 |
| `work_orders.issue` | `/work-orders/<int:order_id>/issue` | POST | 303, 400, 403 | 303, 400, 403 |
| `work_orders.register_event` | `/work-orders/<int:order_id>/lines/<int:line_id>/events/<kind>` | GET | 200, 400 | 200, 400 |
| `work_orders.register_event` | `/work-orders/<int:order_id>/lines/<int:line_id>/events/<kind>` | POST | 303 | 303 |
| `work_orders.match` | `/work-orders/<int:order_id>/lines/<int:line_id>/match` | GET | 200, 400 | 200, 400 |
| `work_orders.match` | `/work-orders/<int:order_id>/lines/<int:line_id>/match` | POST | 303, 400 | 303, 400 |
| `work_orders.writeoff` | `/work-orders/<int:order_id>/lines/<int:line_id>/writeoff` | POST | 303, 400 | 303, 400 |
| `work_orders.printing` | `/work-orders/<int:order_id>/print` | GET | 200, 400 | 200, 400 |
| `work_orders.transfer` | `/work-orders/<int:order_id>/transfer` | GET | 200, 400 | 200, 400 |
| `work_orders.transfer` | `/work-orders/<int:order_id>/transfer` | POST | 303, 400, 403 | 303, 400, 403 |
| `work_orders.workflow` | `/work-orders/<int:order_id>/workflow/<action>` | POST | 303, 400 | 303, 400 |
| `work_orders.control` | `/work-orders/control` | GET | 200, 400 | 200, 400 |
| `work_orders.control_export` | `/work-orders/control/export.xlsx` | GET | 200 | 200 |
| `work_orders.edit` | `/work-orders/new` | GET | 200 | 200 |
| `work_orders.edit` | `/work-orders/new` | POST | 303, 400 | 303, 400 |
| `work_orders.revoke_writeoff` | `/work-orders/resolutions/<int:resolution_id>/revoke` | POST | 303, 400 | 303, 400 |
| `work_orders.cancel_transfer` | `/work-orders/transfers/<int:transfer_id>/cancel` | POST | 303, 400 | 303, 400 |

Совпадают 93 правил и 123 пар правила и метода.
Для URL с несколькими именованными правилами коды агрегированы по пути и методу.
Тире означает, что соответствующий вызов отсутствовал в собранном HTTP-протоколе.

## Режимные маршруты

- Windows Portable дополнительно регистрирует `GET /_portable/health` в `app/portable/server.py`. Сохранён прежний протокол подтверждения локального экземпляра. Запрос без токена и корректное доказательство проверяют `tests/test_windows_server.py` и `tests/test_windows_instance.py`.
- Облачная фабрика `deploy/cloud.py` дополнительно регистрирует `GET /healthz` и ограничивает локальное завершение сервера. Параметры reverse proxy, доступ и фактическая глубина проверки вынесены в [инструкцию поставки](v2_yandex_cloud_deployment.md) и [итоговый отчёт](v2_results.md). Клиентские адреса основного продукта не перенаправляются на другой HTTP-метод.

## Воспроизведение

Запустите из каталога нужной версии в окружении с зависимостями приложения, Playwright и Chromium. Для исходной версии параметр `--source` указывает на распакованный `git archive 51f9a79`; каталог `--output` должен быть отдельным для каждого прогона.

```bash
python tests/browser_v2_ux.py --output /tmp/plankton-ux-after
PYTHONPATH=tests UX_ROUTE_REPORT=/tmp/routes-after.json python -m pytest -q -p ux_route_probe tests/*web*.py tests/test_event_flow.py tests/test_navigation.py tests/test_personnel_import.py tests/test_rebranding.py
```

Тестовая фикстура этапа 4.2 содержит датированные учебные события октября 2026. Для воспроизведения сценариев текущего журнала календарные часы стенда должны показывать дату после 20 октября 2026 года. Коды ответов для матрицы объединяют результаты наблюдателя `tests/ux_route_probe.py` и браузерного драйвера. Файлы запросов и количественный UX-протокол размещены в [каталоге доказательств](v2_ux_evidence/).
