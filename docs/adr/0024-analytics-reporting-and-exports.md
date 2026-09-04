# ADR 0024 — Analítica, reportes y exportaciones P15

- **Estado:** Aceptado
- **Fecha:** 2026-09-03
- **Reemplaza a:** No aplica; complementa ADR 0004, ADR 0009, ADR 0011 y ADR 0015–0023
  sin sustituir sus autoridades
- **Reemplazado por:** No aplica

## Contexto

El Blueprint requiere dashboards por perfil, embudo comercial, agenda, ejecución operativa,
cartera, flujo, rentabilidad, inventario, reportes guardados y exportaciones auditadas. La base
P14 final ya separa las autoridades de personas, oportunidades, cotizaciones, agenda, operación,
documentos, cuentas por cobrar, finanzas, recursos, comunicaciones, portal y organizaciones.
Analítica debe componer esas verdades sin convertirse en otro sistema transaccional ni trasladar
fórmulas normativas fuera de sus dominios.

La inspección previa a esta decisión confirmó que no existe todavía `claridez.analytics`, que los
puertos públicos actuales no ofrecen todas las consultas batch históricas que P15 necesita y que
las exportaciones vigentes de Finance y Scheduling continúan siendo source-owned. También confirmó
que `DocumentJob` y `CommunicationOutbox` son ledgers internos de sus respectivos módulos, no
infraestructura genérica, y que los workers existentes reclaman trabajo por organización bajo RLS.
No se encontró una contradicción objetiva que reabra P14 o ADR 0023.

Este ADR formaliza la arquitectura P15 aprobada. Su aceptación no autoriza implementar P15:
`claridez.analytics`, capabilities, modelos, migraciones, endpoints, workers, dependencias,
almacenamiento y frontend permanecen pendientes hasta una aprobación posterior.

## Decisiones aceptadas

### 1. Una única frontera técnica Analytics

1. P15 creará una sola aplicación Django: `claridez.analytics`.
2. Reporting, catálogo métrico, dashboards, reportes guardados y exportaciones serán subdominios
   internos de Analytics; no existirán aplicaciones Django independientes `reporting` o `exports`.
3. Analytics poseerá exclusivamente:

   - composición analítica transversal;
   - catálogo y versionado de contratos métricos P15;
   - definiciones y revisiones de reportes;
   - ejecuciones explícitas de reportes;
   - `ExportJob`, sus intentos y su auditoría;
   - metadata y artefactos de exportación P15.

4. Analytics no poseerá personas, oportunidades, cotizaciones, ventas, reservas, ocupación,
   ejecución, documentos, obligaciones, pagos, saldos, caja, reconocimiento, costos, gastos,
   rentabilidad, inventario, compras, recursos ni comunicaciones. Sus resultados son proyecciones
   derivadas, nunca nuevos hechos transaccionales.
5. La flecha significa que el consumidor depende del proveedor:

   ```text
   API / frontend P15 ─▶ analytics ─▶ organizations
                                   ├▶ people
                                   ├▶ crm
                                   ├▶ commercial
                                   ├▶ scheduling
                                   ├▶ operations
                                   ├▶ receivables
                                   ├▶ finance
                                   └▶ resources
   ```

   Los dominios fuente no importarán Analytics. Analytics solo consumirá sus puertos públicos y
   ningún puerto fuente devolverá ORM o `QuerySet`; así no se crea un ciclo.
6. Documents, Communications y Portal no aportan una familia métrica a P15 v1. Analytics no lee su
   estado para fabricar indicadores; una necesidad futura deberá entrar por un puerto source-owned,
   minimizado y autorizado del dominio correspondiente, sin trasladar su autoridad.

### 2. Autoridad de fórmulas: source-owned y analytics-owned

1. Una métrica es **source-owned** cuando su significado ya pertenece a un dominio. Ese dominio
   conserva la fórmula normativa, estados, correcciones y evidencia temporal. Analytics solo
   registra su `metric_id` y versión P15, la referencia a `source_metric_id` y
   `source_metric_version`, etiquetas, dimensiones permitidas, modo temporal, capabilities y
   cobertura. La respuesta del puerto identifica siempre la versión de semántica fuente usada.
2. Permanecen source-owned, como mínimo:

   - Commercial: solicitudes, cotizaciones, aceptación, estados e historia comercial;
   - People: identidad canónica, clusters y merges;
   - CRM: interacciones, tareas y métricas cuya verdad sean esos hechos;
   - Scheduling: reservas, ocupación, bloqueos, cancelaciones y reprogramaciones;
   - Operations: preparación, ejecución, fases, incidencias y cierre;
   - Receivables: obligación, calendario, saldo, aging, pagos, aplicaciones, ajustes, reversos y
     devoluciones;
   - Finance: venta confirmada conforme ADR 0020, reconocimiento, costos, gastos, contribuciones y
     movimientos de caja, flujo neto, márgenes, resultado, rentabilidad, periodos y cierres;
   - Resources: movimientos, stock, indisponibilidad, requerimientos y faltantes.

3. `accepted_quote_amount` es source-owned por Commercial. Su hecho gobernante es la aceptación
   comercial autoritativa de la versión exacta de cotización; no es obligación, cobro, caja ni
   ingreso. Su contrato v1 suma, por moneda, el total de cada versión cuya primera aceptación
   autoritativa ocurrió en `[period_start, period_end)` y era visible en `knowledge_cutoff_at`;
   excluye borradores, meras emisiones, versiones retiradas/sustituidas sin aceptación y
   `cutover_state` que no pruebe el hecho.
4. `confirmed_sale_amount` es source-owned por Finance. `finance.public` expondrá el puerto batch
   P15 de `finance.confirmed_sale_amount@1` con la semántica normativa de ADR 0020: total de la
   cotización aceptada que originó la obligación en la primera confirmación de la raíz. Finance
   conserva la fórmula y consume las proyecciones tipadas que ya gobierna ADR 0020; Analytics no la
   reduce a cotización aceptada ni combina por su cuenta Commercial, Scheduling y Receivables para
   recrearla. El agregado v1 suma una sola venta normativa por raíz y moneda en el periodo de esa
   primera confirmación, visible al límite de conocimiento.
5. Una métrica es **analytics-owned** solo si su fórmula es una composición verdaderamente
   transversal de hechos tipados de más de un dominio. Su contrato debe fijar la fórmula completa y
   conservar todas las parejas `source_metric_id + source_metric_version` empleadas.
6. Analytics no reimplementará las ecuaciones de ADR 0019, ADR 0020 ni una fórmula equivalente de
   otro dominio, aunque los datos necesarios sean consultables.

### 3. Contrato y catálogo de métricas

1. El catálogo normativo inicial será code-defined y versionado con el producto. No habrá CRUD de
   fórmulas por organización ni tabla tenant-configurable de métricas.
2. Cada contrato fija de forma verificable:

   - `metric_id`, `metric_version` y versión/hash de catálogo;
   - categoría source-owned o analytics-owned y dominio propietario de la verdad;
   - referencia y versión de cada métrica fuente;
   - fórmula exacta en el propietario normativo;
   - grano y dimensiones cerradas admitidas;
   - modo temporal, instante o fecha económica gobernante e intervalo `[inicio, fin)`;
   - estados incluidos/excluidos y tratamiento de cancelaciones, reversiones,
     reprogramaciones, merges y correcciones;
   - zona IANA, moneda, escala y redondeo aplicables;
   - procedencia, reglas de cobertura y capabilities P15/fuente requeridas.

3. No se publicarán métricas genéricas llamadas «ventas», «ingresos», «ocupación» o
   «rentabilidad». Los identificadores y etiquetas deben conservar la distinción normativa.
4. Los reportes persistidos referencian `metric_id + metric_version`. Cambiar fórmula, estados,
   grano, tiempo o tratamiento monetario crea otra versión; una versión publicada no se modifica en
   sitio ni un reporte se actualiza silenciosamente.
5. Cada respuesta analítica, ejecución y exportación conservará, según corresponda:

   - versión y hash del catálogo efectivo;
   - versiones métricas P15 y versiones fuente;
   - parámetros y dimensiones;
   - `period_start` y `period_end`;
   - `as_of_at`, cuando aplique;
   - `knowledge_cutoff_at`;
   - `executed_at`;
   - zona IANA usada;
   - moneda o partición monetaria;
   - `coverage`, procedencia y watermarks/revisiones relevantes.

   No existe un `cutoff_at` único que mezcle periodo económico, estado histórico y límite de
   conocimiento.

### 4. Catálogo métrico P15 v1

Los contratos de esta sección son normativos. Los puertos batch los implementarán, pero no podrán
completar ni redefinir por primera vez el significado de un identificador ya publicado como `@1`.
Una revisión que cambie cualquiera de estas reglas exige otro `metric_version`.

#### 4.1 Convenciones vinculantes del anexo

- `F` significa `fact_in_period`: `period_start` y `period_end` son obligatorios y el instante
  económico indicado debe caer en `[period_start, period_end)`. `as_of_at` no aplica y se rechaza;
  `knowledge_cutoff_at` sigue siendo obligatorio.
- `S` significa `state_at_cutoff`: `as_of_at` es obligatorio y el periodo no aplica, salvo `SI`.
  `SI` proyecta en `[period_start, period_end)` únicamente el estado que era efectivo en
  `as_of_at`; los tres parámetros son obligatorios.
- `C` significa `cohort_as_of_cutoff`: el periodo forma la cohorte, `as_of_at >= period_end`
  gobierna el resultado observado y ambos son obligatorios.
- `FP` significa `financial_period_as_of`: exige `operational_period_id`, su moneda y
  `as_of_at`. Un periodo cerrado usa exclusivamente el snapshot Finance visible al límite de
  conocimiento; uno abierto es provisional. Un rango arbitrario no sustituye el periodo.
- `knowledge_cutoff_at` es obligatorio en todos los modos. Solo se usan filas, eventos, revisiones
  o snapshots cuya evidencia autoritativa de registro sea visible hasta ese instante. Si la fuente
  solo conserva estado mutable o un timestamp económico pero no puede probar cuándo conocía el
  estado, no lo trata como historia: degrada cobertura. `executed_at` nunca sustituye este límite.
- El grano indicado es el elemento individual antes de agregar. El grano de salida es
  `organización + dimensiones seleccionadas`; `time_bucket` admite día, semana ISO o mes en la zona
  IANA de la ejecución. Toda dimensión no enumerada se rechaza y `!` marca una dimensión
  obligatoria.
- Para importes, `currency!` es ISO 4217 y no existe FX: una consulta exige una moneda o devuelve
  particiones separadas; una mezcla nunca se suma. Money conserva escala 2 y `ROUND_HALF_UP` de su
  dominio fuente. Para cantidades Resources, `resource_id!` y `unit_id!` identifican el recurso y
  su unidad base; usan escala 6 y no convierten ni agregan recursos/unidades distintos. Counts son
  enteros. Duraciones se calculan desde intervalos UTC exactos, sin redondeo intermedio, y el valor
  final en segundos/minutos usa escala 3 y `ROUND_HALF_UP`; porcentajes usan puntos porcentuales,
  escala 2 y el mismo redondeo tras dividir.
- Salvo que una fila disponga otra cosa, correcciones append-only se resuelven por la última hoja
  efectiva visible al límite de conocimiento; la corrección no borra el hecho original. Una
  cancelación o reprogramación solo altera métricas de estado desde su instante efectivo y además
  cuenta como hecho en su propia métrica. `cutover_state` y snapshots legacy no fabrican hechos.
- En todas las filas, `complete` exige evidencia autoritativa para todo el alcance y ambos ejes
  temporales; un cero solo es válido con esa evidencia. `partial` exige `coverage_from` cuando sea
  determinable y un motivo; `unavailable` se usa cuando falta el hecho, la revisión, el timestamp,
  la dimensión, la moneda/unidad o la reconstrucción mínima. Una composición toma la peor
  cobertura de sus fuentes y nunca estima lo faltante.

Las capabilities existentes usadas literalmente son `sales:read`, `operation:read`,
`operation_incident:read`, `receivables:read`, `finance:read` y `resource:read`. P15 deberá añadir,
como capabilities **source-owned** estrechas, `interaction:read_analytics` en CRM,
`task:read_analytics` en CRM, `schedule:read_analytics` en Scheduling y
`person:resolve_analytics` en People. No conceden acceso a PII ni a comandos y no son capabilities
de Analytics. No se reutilizan `task:manage`, `person:read`, `schedule:export` ni
`availability:read` como sustitutos por proximidad semántica.

En cada fila source-owned, el namespace del primer `source_metric_id` identifica al propietario
normativo; referencias adicionales son inputs públicos versionados y no transfieren la fórmula a
Analytics. Solo las dos composiciones marcadas expresamente como Analytics-owned tienen fórmula
P15 propia y conservan todas sus versiones fuente.

#### 4.2 Commercial, CRM y composiciones

| `metric_id@1` y fuente | Fórmula y grano | Dimensiones permitidas | Tiempo, estados y unidad | Capability y cobertura específica |
| --- | --- | --- | --- | --- |
| `request_created_count@1` → `commercial.request_created_count@1` | `count(distinct EventRequest)` por su único `EventRequestHistory(kind=created)`; grano solicitud | `time_bucket`, `origin`, `responsible_membership_id` | `F`; gobierna `occurred_at`; cuenta cualquier estado posterior y excluye `cutover_state`; unidad count | `sales:read`; sin `created` autoritativo es `partial/unavailable`, nunca se infiere desde la fila vigente |
| `quote_issued_count@1` → `commercial.quote_issued_count@1` | `count(QuotationVersion)` con emisión autoritativa; grano versión emitida, **no** solicitud distinta | `time_bucket`, `currency`, `event_type_id`, `venue_id`, `space_id` | `F`; gobierna `issued_at`, que también prueba conocimiento de la emisión; una versión luego aceptada, sustituida o retirada sigue contando; draft nunca emitido se excluye; unidad count | `sales:read`; versiones legacy sin `issued_at` fiable degradan cobertura |
| `quote_accepted_count@1` → `commercial.quote_accepted_count@1` | `count(distinct QuotationVersion)` por su primera aceptación autoritativa; grano versión aceptada, no solicitud | `time_bucket`, `currency`, `event_type_id`, `venue_id`, `space_id`, `acceptance_channel` | `F`; gobierna `accepted_at`, que prueba conocimiento de aceptación; estados posteriores de solicitud/reserva no lo revierten; unidad count | `sales:read`; ausencia de `accepted_at` fiable degrada cobertura |
| `closed_lost_request_count@1` → `commercial.closed_lost_request_count@1` | `count(distinct EventRequest)` cuya transición autoritativa entra en `closed_lost`; grano solicitud | `time_bucket`, `origin`, `responsible_membership_id` | `F`; gobierna `EventRequestHistory.occurred_at`; solo `status_changed`, no estado terminal de cutover; unidad count | `sales:read`; transición sin hecho/tiempo fiable degrada cobertura |
| `closed_lost_latest_issued_quote_amount@1` → `commercial.closed_lost_latest_issued_quote_amount@1` | Para cada solicitud del contrato anterior, suma el `total` de la versión de mayor `version` emitida no después del cierre perdido y visible al límite de conocimiento; solicitudes sin tal versión no aportan importe | `time_bucket`, `currency!`, `origin`, `event_type_id`, `venue_id`, `space_id` | `F`; gobierna el `occurred_at` del cierre perdido; emisión posterior no se retrotrae; unidad money | `sales:read`; si no puede probarse la versión vigente en el cierre, la partición es `partial/unavailable` |
| `accepted_quote_amount@1` → `commercial.accepted_quote_amount@1` | Suma `QuotationVersion.total` de cada versión aceptada del contrato de aceptación; grano versión aceptada | `time_bucket`, `currency!`, `event_type_id`, `venue_id`, `space_id`, `acceptance_channel` | `F`; gobierna `accepted_at`; confirmación, cancelación o reprogramación posterior no cambia el hecho; unidad money | `sales:read`; misma cobertura que `quote_accepted_count@1` |
| `open_issued_quote_amount@1` → `commercial.open_issued_quote_amount@1` | Suma la versión emitida de mayor `version` por solicitud cuyo estado Commercial as-of es `quoted` y cuyo `valid_until > as_of_at`; grano solicitud | `currency!`, `origin`, `event_type_id`, `venue_id`, `space_id` | `S`; borradores, expiradas, aceptadas, sustituidas, retiradas y solicitudes `accepted`, `confirmed`, `closed_lost` o `cancelled` quedan fuera; unidad money | `sales:read`; una retirada/mutación sin historia suficiente para el corte vuelve la partición `partial/unavailable` |
| `first_outbound_response_elapsed_seconds@1` → `crm.first_outbound_response_elapsed_seconds@1` + `commercial.request_created_cohort@1` | Media aritmética de `primer Interaction outbound efectivo.occurred_at - solicitud.created.occurred_at`, en segundos, por solicitud de cohorte; interacciones anteriores a la creación y solicitudes sin respuesta se excluyen del numerador y del promedio; devuelve `eligible_count` y `sample_size` | `time_bucket` de cohorte, `origin`, `channel` de la interacción ganadora | `C`; correcciones de Interaction visibles sustituyen su raíz; `as_of_at` limita respuestas elegibles; unidad seconds | `interaction:read_analytics ∧ sales:read`; `complete` exige historia de creación e interacción para toda la cohorte, aunque `sample_size=0` |
| `open_request_without_next_action_count@1` → `crm.open_request_without_next_action_count@1` + `commercial.request_state_as_of@1` | Cuenta solicitudes distintas en `new`, `quoted` o `accepted` as-of sin ninguna `FollowUpTask` efectiva `open` vinculada; grano solicitud | `origin`, `responsible_membership_id` | `S`; tareas `completed` o `cancelled` no cubren la solicitud; historia de tarea y solicitud se resuelve al corte; unidad count | `task:read_analytics ∧ sales:read`; estado mutable sin revisión histórica suficiente degrada cobertura |
| `confirmed_sale_count@1` → `finance.confirmed_sale_count@1` | Cuenta raíces distintas que adquieren su única venta confirmada por la primera confirmación, conforme ADR 0020 §3; grano raíz | `time_bucket`, `currency`, `venue_id` | `F`; gobierna el instante de primera confirmación que originó la obligación; cancelación/reprogramación posterior no elimina el hecho; unidad count | `finance:read`; exige la procedencia Finance/Receivables de la raíz y snapshot económico; falta legacy explícita degrada cobertura |
| `confirmed_sale_amount@1` → `finance.confirmed_sale_amount@1` | Importe de venta confirmada exactamente conforme ADR 0020 §3: total de la cotización aceptada que originó la obligación de la primera confirmación; grano raíz | `time_bucket`, `currency!`, `venue_id` | `F`; mismo hecho gobernante que el count; no es cotización aceptada genérica, cobro ni ingreso; unidad money | `finance:read`; misma cobertura que `confirmed_sale_count@1` |
| `request_to_confirmed_sale_conversion_rate@1` (Analytics-owned) → `commercial.request_created_cohort@1` + `finance.confirmed_sale_cohort@1` | Analytics divide solicitudes distintas creadas en la cohorte que alcanzaron primera venta confirmada visible al corte entre solicitudes distintas elegibles de la cohorte y multiplica por 100; denominador cero = `not_calculable`; grano solicitud | `time_bucket` de cohorte, `origin` | `C`; estados posteriores no eliminan creación/confirmación; unidad percentage_points; conserva ambas versiones fuente | `sales:read ∧ finance:read`; peor cobertura fuente, y no calcula si numerador/cohorte no son reconciliables |
| `distinct_canonical_request_person_count@1` (Analytics-owned) → `commercial.request_person_cohort@1` + `people.canonical_cluster_as_of@1` | Analytics cuenta clusters People distintos as-of con al menos una solicitud de la cohorte; grano cluster histórico, sin nombres/contactos | `time_bucket` de cohorte, `origin` | `C`; merges solo afectan desde su evidencia visible a `as_of_at` y `knowledge_cutoff_at`; unidad count; conserva ambas versiones fuente | `sales:read ∧ person:resolve_analytics`; historia de merge insuficiente produce `partial/unavailable`, nunca canonicalización vigente retroactiva |

#### 4.3 Scheduling y Operations

| `metric_id@1` y fuente | Fórmula y grano | Dimensiones permitidas | Tiempo, estados y unidad | Capability y cobertura específica |
| --- | --- | --- | --- | --- |
| `confirmed_event_minutes@1` → `scheduling.confirmed_event_minutes@1` | Suma minutos de intersección entre `[period_start, period_end)` y `event_interval` de la única reserva efectiva `confirmed` por raíz as-of; grano raíz | `time_bucket`, `venue_id`, `space_id` | `SI`; canceladas dejan de aportar y una reprogramación aporta solo la sucesora efectiva; unidad minutes | `schedule:read_analytics`; exige cadena, `ScheduleEvent` y snapshot de intervalo completos |
| `confirmed_occupied_minutes@1` → `scheduling.confirmed_occupied_minutes@1` | Igual que la anterior, pero usa `occupied_interval` autoritativo con snapshots de setup, teardown y buffers; grano raíz | `time_bucket`, `venue_id`, `space_id` | `SI`; no sustituye evento por ocupación ni reconstruye buffers vigentes; unidad minutes | `schedule:read_analytics`; falta de snapshot histórico de ocupación degrada cobertura |
| `confirmed_reservation_count@1` → `scheduling.confirmed_reservation_count@1` | Cuenta raíces distintas con una reserva efectiva `confirmed` as-of cuyo `event_interval` intersecta el periodo; grano raíz | `time_bucket`, `venue_id`, `space_id` | `SI`; no cuenta transiciones de confirmación ni miembros previos de una cadena; unidad count | `schedule:read_analytics`; misma evidencia histórica de cadena/estado que la métrica de minutos |
| `blocked_minutes@1` → `scheduling.blocked_minutes@1` | Suma minutos de intersección del periodo con allocations de bloque efectivas as-of para el `space_id` seleccionado; grano bloque/espacio | `time_bucket`, `venue_id`, `space_id!` | `SI`; bloques liberados/cancelados antes del corte se excluyen; unidad minutes | `schedule:read_analytics`; solo `complete` donde eventos/snapshots prueban creación y liberación; de otro modo `partial/unavailable` |
| `reservation_cancelled_count@1` → `scheduling.reservation_cancelled_count@1` | Cuenta `ScheduleEvent` autoritativos de cancelación de reserva; grano evento de cancelación | `time_bucket`, `venue_id`, `space_id` del snapshot previo | `F`; gobierna `occurred_at`, limitado por `recorded_at <= knowledge_cutoff_at`; no se borra por una acción posterior; unidad count | `schedule:read_analytics`; snapshots/cutover sin evento no cuentan y degradan cobertura histórica |
| `reservation_rescheduled_count@1` → `scheduling.reservation_rescheduled_count@1` | Cuenta `ScheduleEvent` autoritativos de reprogramación; grano evento de reprogramación, no raíz | `time_bucket`, `from_venue_id`, `from_space_id`, `to_venue_id`, `to_space_id` | `F`; gobierna `occurred_at`, limitado por `recorded_at`; una raíz puede contribuir más de una vez si fue reprogramada varias veces; unidad count | `schedule:read_analytics`; requiere snapshots previo/nuevo y cadena coherente |
| `preparation_open_count@1` → `operations.preparation_open_count@1` | Cuenta preparaciones distintas cuyo estado as-of es `preparing`, `ready` o `in_progress`; grano preparación | `status`, `responsible_membership_id` | `S`; excluye `completed`, `cancelled` y `rescheduled`; usa transiciones, no el estado vigente aislado; unidad count | `operation:read`; transiciones legacy sin evidencia de conocimiento suficiente degradan cobertura |
| `pending_required_verification_count@1` → `operations.pending_required_verification_count@1` | Cuenta `OperationalVerification` requeridas cuyo estado efectivo as-of es `pending`; grano verificación | `phase`, `role_key` | `S`; excluye no requeridas, `completed` y `not_applicable`; correcciones visibles de eventos prevalecen; unidad count | `operation:read`; snapshot sin historial de estado suficiente degrada cobertura |
| `execution_completed_count@1` → `operations.execution_completed_count@1` | Cuenta preparaciones distintas por `PreparationTransition(cause=execution_completed)`; grano preparación | `time_bucket` | `F`; gobierna `occurred_at`; cancelación, reprogramación o cierre posterior no elimina el hecho; unidad count | `operation:read`; cutover/estado `completed` sin transición no cuenta y degrada cobertura |
| `phase_duration_seconds@1` → `operations.phase_duration_seconds@1` | Media aritmética de duraciones no negativas `completed.observed_at - started.observed_at` por preparación y fase usando hojas de corrección efectivas; el periodo selecciona el hecho `completed`; devuelve `sample_size`; grano preparación+fase | `time_bucket`, `phase!` (`setup` o `teardown`) | `F`; gobierna `completed.observed_at`; pares incompletos/negativos se excluyen y vuelven cobertura parcial, no cero; unidad seconds | `operation:read`; `complete` exige ambos hechos y sus correcciones para todos los completados elegibles |
| `incident_opened_count@1` → `operations.incident_opened_count@1` | Cuenta incidentes distintos por su evento raíz `opened` efectivo; grano incidente | `time_bucket`, `incident_type`, `severity` registrada en el evento efectivo | `F`; gobierna `occurred_at`; contención/resolución posterior no elimina apertura; una corrección sustituye campos, no duplica; unidad count | `operation_incident:read`; incidente vigente sin evento de apertura fiable degrada cobertura |
| `post_event_close_elapsed_seconds@1` → `operations.post_event_close_elapsed_seconds@1` | Media aritmética de `PostEventClose.closed_at - PreparationTransition(execution_completed).occurred_at` por preparación cerrada; el periodo selecciona `closed_at`; devuelve `sample_size`; grano preparación | `time_bucket` | `F`; solo diferencias no negativas y cierres consumados; correcciones de contenido del cierre no cambian esos dos instantes; unidad seconds | `operation:read`; falta de transición/cierre autoritativo degrada cobertura y el caso se excluye del promedio |

#### 4.4 Receivables

Todas las fórmulas de esta tabla permanecen en Receivables y remiten normativamente a ADR 0019
§§7–8. Analytics no las reproduce.

| `metric_id@1` y fuente | Fórmula y grano | Dimensiones permitidas | Tiempo, estados y unidad | Capability y cobertura específica |
| --- | --- | --- | --- | --- |
| `obligation_original_amount@1` → `receivables.obligation_original_amount@1` | Suma `original_total` de obligaciones creadas por primera confirmación; grano obligación/raíz | `time_bucket`, `currency!` | `F`; gobierna `confirmed_at`; ajustes, aplicaciones, reversos y refunds no alteran el original; money | `receivables:read`; obligación legacy sin hecho/snapshot económico fiable degrada cobertura |
| `payment_received_amount@1` → `receivables.payment_received_amount@1` | Suma bruta de pagos externos declarados; grano pago | `time_bucket`, `currency!`, `method`, `provenance` | `F`; gobierna `reported_at`; reverso/refund posterior no borra el hecho y se informa por sus métricas; money | `receivables:read`; requiere pago y moneda autoritativos visibles |
| `payment_unapplied_amount@1` → `receivables.payment_unapplied_amount@1` | Para pagos cuyo `reported_at` cae en la cohorte, suma su no aplicado as-of según la ecuación exacta ADR 0019 §7, incluidos efectos de aplicaciones, reversos y refunds; grano pago | `time_bucket` de cohorte, `currency!`, `method`, `provenance` | `C`; `as_of_at` limita todos los movimientos efectivos; money | `receivables:read`; falta de cualquier movimiento de la cadena vuelve la partición `partial/unavailable` |
| `application_net_amount@1` → `receivables.application_net_amount@1` | Suma los efectos netos de aplicación ocurridos en el periodo conforme ADR 0019 §7: aplicaciones, reversos de aplicación, asignaciones de refund que reabren saldo y reversos de refund; grano efecto financiero tipado | `time_bucket`, `currency!`, `effect_kind` | `F`; gobierna `applied_at`, `reversed_at` o `refunded_at` según el efecto; no es caja; money | `receivables:read`; cadena o asignación incompleta degrada cobertura |
| `adjustment_net_amount@1` → `receivables.adjustment_net_amount@1` | Suma el signo normativo de ajustes de obligación y sus reversos conforme ADR 0019 §7; grano efecto de ajuste | `time_bucket`, `currency!`, `direction` | `F`; gobierna `occurred_at` del ajuste o `reversed_at`; money | `receivables:read`; objetivo/reverso ausente o incoherente degrada cobertura |
| `movement_reversal_amount_by_target@1` → `receivables.movement_reversal_amount_by_target@1` | Suma bruta positiva de reversos; grano `FinancialMovementReversal`; no aplica signo neto entre tipos | `time_bucket`, `currency!`, `target_kind!` (`payment`, `application`, `adjustment` o `refund`) | `F`; gobierna `reversed_at`; el objetivo es obligatorio; money | `receivables:read`; target o moneda no reconciliable = `partial/unavailable` |
| `refund_recorded_amount@1` → `receivables.refund_recorded_amount@1` | Suma bruta de devoluciones registradas; grano refund | `time_bucket`, `currency!` | `F`; gobierna `refunded_at`; su reverso posterior no borra el hecho; no es aplicación ni ejecución bancaria; money | `receivables:read`; requiere refund visible y asignaciones coherentes cuando correspondan |
| `open_balance_amount@1` → `receivables.open_balance_amount@1` | Saldo abierto exacto por obligación conforme ADR 0019 §7 y suma por partición; grano obligación | `currency!` | `S`; usa solo movimientos efectivos hasta `as_of_at` y visibles al límite de conocimiento; money | `receivables:read`; cadena incompleta, moneda mezclada o cutoff no reconstruible degrada cobertura |
| `aging_open_balance_amount@1` → `receivables.aging_open_balance_amount@1` | Distribuye el saldo abierto conforme ADR 0019 §8 usando la `CollectionScheduleRevision` aplicable, aplicaciones dirigidas y asignación determinista; grano obligación+vencimiento/bucket | `currency!`, `aging_bucket!` (`current`, `1_30`, `31_60`, `61_90`, `over_90`, `unscheduled`) | `S`; edad por fecha local organizacional en `as_of_at`; nunca usa el calendario vigente para un corte previo; money | `receivables:read`; revisión/calendario/movimientos insuficientes degradan la partición, sin reclasificación estimada |
| `expected_collection_amount@1` → `receivables.expected_collection_amount@1` | Suma el residual abierto de vencimientos de la revisión aplicable cuyo `due_on` local cae en `[period_start, period_end)`; es monto **calendarizado**, no probabilidad ni forecast; saldo sin vencimiento se excluye | `time_bucket` de `due_on`, `currency!` | `SI`; `as_of_at` fija saldo y revisión; aplicaciones/reversos/refunds hasta el corte modifican residual según ADR 0019; money | `receivables:read`; calendario no reconstruible = `partial/unavailable`; obligaciones `unscheduled` se declaran como exclusión, no como cero esperado |

#### 4.5 Finance

Las fórmulas Finance son exactamente las de ADR 0020 §§3, 5–7, 9 y 11. Todos los importes tienen
`currency!`, usan `finance:read`, preservan correcciones y ajustes de periodos anteriores y aplican
la regla `FP`, salvo `baseline_direct_cost_amount@1`, que usa `S`. Una exportación source-specific
exige además `finance:export`; esa capability no cambia la lectura del KPI.

| `metric_id@1` y fuente | Fórmula/grano y dimensiones adicionales | Estado, unidad y cobertura específica |
| --- | --- | --- |
| `recognized_revenue_amount@1` → `finance.recognized_revenue_amount@1` | ADR 0020 §§4, 9 y 11; grano periodo+raíz; `venue_id`, `root_reservation_id` | `FP`; money; cerrado = snapshot, abierto = provisional; falta de snapshot/registro visible degrada cobertura |
| `baseline_direct_cost_amount@1` → `finance.baseline_direct_cost_amount@1` | ADR 0020 §5; suma baseline inmutable; grano raíz+línea; `root_reservation_id!`, `category_id` | `S`; money; antes de existir baseline devuelve `not_applicable`, no cero; baseline/revisiones no visibles degradan cobertura |
| `actual_direct_cost_amount@1` → `finance.actual_direct_cost_amount@1` | ADR 0020 §§5, 9 y 11; grano costo real/corrección; `venue_id`, `root_reservation_id`, `category_id` | `FP`; money neto de correcciones Finance; snapshot cerrado manda |
| `variable_expense_amount@1` → `finance.variable_expense_amount@1` | ADR 0020 §§6, 9 y 11; grano porción de ocurrencia/corrección variable; `venue_id`, `root_reservation_id`, `category_id` | `FP`; money; solo hechos materializados, no reglas futuras |
| `recurring_expense_amount@1` → `finance.recurring_expense_amount@1` | ADR 0020 §§6, 9 y 11; grano porción de ocurrencia/corrección recurrente; `venue_id`, `category_id` | `FP`; money; no proyecta recurrencias aún no materializadas |
| `cash_inflow_amount@1` → `finance.cash_inflow_amount@1` | ADR 0020 §§7, 9 y 11; grano contribución P10/movimiento o corrección P11 con dirección de entrada; `venue_id`, `root_reservation_id`, `source_kind` | `FP`; money; aplicación no aporta caja y snapshot cerrado manda |
| `cash_outflow_amount@1` → `finance.cash_outflow_amount@1` | ADR 0020 §§7, 9 y 11; grano contribución P10/movimiento o corrección P11 con dirección de salida; `venue_id`, `root_reservation_id`, `source_kind` | `FP`; money; refund y reverso conservan sus signos normativos |
| `net_cash_flow_amount@1` → `finance.net_cash_flow_amount@1` | Fórmula exacta ADR 0020 §11; grano `OperationalPeriod`+scope seleccionado; no resta P10 nuevamente en Analytics; `venue_id`, `root_reservation_id` | `FP`; money; depende solo de la proyección/snapshot Finance autoritativa |
| `gross_margin_amount@1` → `finance.gross_margin_amount@1` | Fórmula exacta ADR 0020 §11; grano `OperationalPeriod`+scope seleccionado; `venue_id`, `root_reservation_id` | `FP`; money; snapshot cerrado o provisional abierto |
| `contribution_margin_amount@1` → `finance.contribution_margin_amount@1` | Fórmula exacta ADR 0020 §11; grano `OperationalPeriod`+scope seleccionado; `venue_id`, `root_reservation_id` | `FP`; money; no incluye gastos recurrentes fuera de su fórmula fuente |
| `operating_result_amount@1` → `finance.operating_result_amount@1` | Fórmula exacta ADR 0020 §11; grano `OperationalPeriod`+scope seleccionado; `venue_id`, `root_reservation_id` | `FP`; money; conserva ajustes prior-period del snapshot |
| `profitability_rate@1` → `finance.profitability_rate@1` | Fórmula exacta ADR 0020 §11; grano `OperationalPeriod`+scope seleccionado; `venue_id`, `root_reservation_id` | `FP`; percentage_points; ingreso reconocido cero = `not_calculable`, nunca cero; misma cobertura Finance |

#### 4.6 Resources

Todas usan `resource:read`, cantidades Decimal en unidad base y evidencia de ledger/eventos
Resources conforme ADR 0021. `resource_id!` y `unit_id!` son obligatorios; `unit_id` debe ser la
unidad base histórica del recurso. Analytics no ejecuta conversiones.

| `metric_id@1` y fuente | Fórmula y grano; dimensiones adicionales | Tiempo, estados y cobertura específica |
| --- | --- | --- |
| `stock_on_hand_quantity@1` → `resources.stock_on_hand_quantity@1` | Suma `StockMovement.effect` hasta el corte; grano recurso+ubicación; `location_id` | `S`; correcciones son movimientos nuevos con su propio signo; no usa `StockBalance` vigente como historia; ledger incompleto = `partial/unavailable` |
| `stock_movement_quantity@1` → `resources.stock_movement_quantity@1` | Suma `quantity` positiva; grano movimiento; `time_bucket`, `location_id`, `kind`, `direction!` | `F` por `occurred_at`; `created_at` limita conocimiento; no netea direcciones ni suma unidades/recursos distintos; transferencia conserva sus dos hechos tipados |
| `event_required_quantity@1` → `resources.event_required_quantity@1` | Suma requisitos efectivos no cancelados/sustituidos que intersectan el periodo; grano requisito; `root_reservation_id`, `temporal_source` | `SI`; estados `open`, `shortage` y `satisfied` incluidos, `cancelled` excluido; cadena/eventos insuficientes degradan cobertura |
| `event_allocated_quantity@1` → `resources.event_allocated_quantity@1` | Suma asignaciones efectivas que intersectan el periodo; grano asignación; `root_reservation_id`, `source_location_id`, `assignment_status` | `SI`; incluye `reserved`, `issued`, `custody` y `fulfilled`; excluye `returned`, `released`, `cancelled` y predecesoras sustituidas; historia insuficiente degrada cobertura |
| `event_shortage_quantity@1` → `resources.event_shortage_quantity@1` | Por requisito efectivo `open` o `shortage`, `max(required - asignado efectivo al mismo requisito, 0)` según ADR 0021, luego suma; grano requisito; `root_reservation_id`, `temporal_source` | `SI`; `satisfied` y `cancelled` aportan cero; asignado usa los estados de la fila anterior; falta de cadena requerida/asignada = `partial/unavailable` |
| `resource_unavailability_quantity@1` → `resources.resource_unavailability_quantity@1` | Suma cantidades de indisponibilidades efectivas cuyo intervalo contiene `as_of_at`; grano indisponibilidad; `location_id` | `S`; activas y correcciones hoja visibles incluidas, cerradas/sustituidas excluidas; no multiplica cantidad por duración; historia de cierre/corrección insuficiente degrada cobertura |

El catálogo v1 retira los identificadores ambiguos `readiness_blocker_count`,
`overdue_operational_item_count`, `incident_count` y `planned_direct_cost_amount`: el primero se
reemplaza por `pending_required_verification_count@1`, el tercero por
`incident_opened_count@1` y el cuarto por `baseline_direct_cost_amount@1`. El significado amplio de
«bloqueador», el vencimiento histórico de ítems y un total mutable de plan previo al baseline
quedan diferidos; no se reservan como `@1` incompletos.

### 5. Dashboards mínimos por perfil

| Perfil | Superficie mínima P15 | Autoridad fuente adicional |
| --- | --- | --- |
| Propietario/administrador | Visión integral: embudo, Agenda, ejecución, cartera, periodos Finance y recursos/inventario | Todas las capabilities fuente exactas de las métricas/dimensiones; la matriz de rol no evita la comprobación conjuntiva |
| Comercial | Solicitudes, respuesta, cotizaciones, aceptación, pipeline y Agenda contextual de sus eventos | `sales:read`, las capacidades CRM aplicables y una lectura analítica estrecha de Scheduling si las vigentes no expresan esa semántica; no recibe rentabilidad ni cartera detallada |
| Operaciones | Agenda, preparación/readiness, fases, incidencias, cierre y recursos/faltantes | Capacidades de Scheduling, Operations y Resources correspondientes; no recibe pipeline monetario, cartera ni Finance por poseer P15 |
| Finanzas | Venta confirmada source-owned por Finance, cartera, cobros/aplicaciones separados, periodos, reconocimiento, costos, gastos, flujo, márgenes y rentabilidad | `receivables:read`, `finance:read` y `finance:export` cuando la exportación conserve esa semántica; recursos solo con capability fuente expresa |

Las métricas de Agenda pueden compartirse entre propietario/administrador, comercial y operaciones;
`confirmed_sale_amount`, reconocimiento y rentabilidad requieren Finance; cartera requiere
Receivables; inventario global requiere Resources. Ningún perfil ve todos los indicadores por una
mera capability Analytics.

### 6. Tiempo de negocio, tiempo de conocimiento e identidad histórica

1. Día, semana, mes y rango arbitrario se convierten desde la zona IANA capturada para la ejecución
   a instantes UTC y usan intervalos `[inicio, fin)`. Día es el día civil local, semana es la semana
   ISO iniciada en lunes y mes es el mes civil; el manifest conserva la zona exacta usada.
2. Cada métrica declara uno de estos modos, o una extensión explícitamente versionada:

   - `fact_in_period`: hecho ocurrido en el intervalo económico;
   - `state_at_cutoff`: estado autoritativo en `as_of_at`;
   - `cohort_as_of_cutoff`: cohorte definida por periodo observada hasta `as_of_at`.

3. Se separan obligatoriamente:

   - tiempo de negocio/económico, que determina periodo o instante del hecho;
   - tiempo de conocimiento, cuyo `knowledge_cutoff_at` limita los hechos ya registrados,
     confirmados o visibles para la ejecución.

   Un hecho registrado después de `knowledge_cutoff_at` no aparece retroactivamente aunque declare
   `occurred_at` o fecha económica anterior.
4. Cada puerto fuente declara qué `created_at`, `recorded_at`, revisión, watermark o snapshot
   inmutable usa. No se reconstruye historia desde estado vigente:

   - Commercial usa `EventRequestHistory`; `cutover_state` no se convierte en un hecho `created`;
   - Scheduling usa `ScheduleEvent`, `recorded_at`/`occurred_at`, snapshots y cadena de reservas;
   - Operations usa su historia append-only de preparación, fases, incidencias y cierre;
   - Receivables usa movimientos, revisiones de calendario y timestamps normativos;
   - Finance usa periodos, registros y snapshots de cierre;
   - People resuelve merges según evidencia histórica visible al corte.

5. Una reprogramación cuenta el hecho de reprogramación en su periodo y, para estado al corte,
   resuelve la reserva vigente de la cadena sin reatribuir hechos previos. Una cancelación cuenta el
   hecho en su periodo y deja de aportar ocupación activa conforme al estado histórico conocido; no
   borra la historia. La aceptación comercial cuenta la transición exacta, no un estado vigente
   inferido. Pagos, aplicaciones, reversos y devoluciones conservan sus propios hechos y fechas.
   Preparación, ejecución y cierre operativo usan sus transiciones observadas; reconocimiento y
   cierre financiero obedecen Finance.
6. Los snapshots Finance cerrados siguen siendo autoridad inmutable. Analytics no recalcula un
   cierre ni lo corta arbitrariamente para simular otro rango.
7. People añadirá un puerto batch que resuelva identidad/cluster canónico as-of desde su historia de
   merges y respete `knowledge_cutoff_at`. Analytics no usará el `canonical_person_id()` vigente
   para reescribir una ejecución histórica. La evidencia legacy insuficiente produce cobertura
   parcial/no disponible.
8. Si la zona histórica necesaria no puede probarse desde una autoridad, la ejecución no asume que
   el setting actual siempre rigió: conserva la zona explícita aplicada o devuelve cobertura
   insuficiente para una semántica que exija la configuración histórica.

### 7. Agenda v1 sin un denominador ficticio

1. No se aprueba `confirmed_space_occupancy_pct = minutos reservados / minutos habilitados`.
   Scheduling no conserva historia normativa suficiente de horas operativas habilitadas para ese
   denominador.
2. P15 no creará horarios ni una política de capacidad para fabricar el porcentaje. No usará 24
   horas del día ni la mera existencia de un espacio como denominador implícito.
3. Agenda v1 usa las seis métricas Scheduling del catálogo. Toda ausencia de evidencia se expresa
   con `coverage=partial|unavailable`, `coverage_from` cuando proceda y un motivo; no se estima.
4. Si una etapa futura otorga a Scheduling autoridad explícita e histórica sobre ventanas de
   capacidad operativa disponible, un porcentaje de utilización requerirá una nueva versión y la
   decisión correspondiente.

### 8. Semántica de Receivables, Finance y moneda

1. Se mantienen separados: cotización aceptada, venta confirmada, obligación, cobro, aplicación,
   contribución de caja P10, movimiento de caja P11, ingreso reconocido, costos, gastos, flujo neto,
   márgenes, resultado y rentabilidad.
2. Receivables conserva y expone por puertos batch sus ecuaciones de obligación, saldo, aging,
   pagos, aplicaciones, ajustes, reversos y devoluciones. Saldo y aging as-of usan la
   `CollectionScheduleRevision` aplicable y solo hechos efectivos visibles hasta
   `knowledge_cutoff_at`; nunca el calendario vigente para reinterpretar un corte anterior.
3. Aplicación no equivale a caja, pago no equivale a ingreso y devolución no equivale a reverso.
   No existe `receivables_cash_net_amount` P15. Las contribuciones P10 siguen siendo hechos tipados
   que Finance combina con movimientos P11 para `net_cash_flow_amount` conforme ADR 0020.
4. Los KPIs financieros cerrados se consultan por `OperationalPeriod` y/o snapshot Finance. Los
   periodos abiertos pueden marcarse provisionales. Un rango parcial o multi-periodo solo es
   admisible cuando `finance.public` expone una semántica explícita que preserve cierres y ajustes
   de periodos anteriores; de otro modo la métrica declara `not_applicable` o exige un periodo.
5. El selector UI puede aceptar rangos generales, pero no obliga a una métrica Finance a producir
   un valor incompatible con su periodo normativo.
6. Ninguna métrica monetaria toma `OrganizationSettings.currency` vigente para reinterpretar el
   pasado. Cada hecho conserva moneda ISO según su fuente y no hay FX. Una métrica debe:

   - exigir una moneda concreta;
   - particionar por moneda; o
   - responder `mixed_currency/not_aggregable`.

7. Ejecuciones, manifests y exports guardan la moneda/partición aplicada. El dominio fuente conserva
   escala y redondeo; para P10/P11 siguen vigentes `Decimal`, `numeric(18,2)`, cuantización `0.01` y
   `ROUND_HALF_UP`. Analytics no redondea de nuevo para alterar la reconciliación.

### 9. Puertos batch, consultas y rendimiento de datos

1. Cada dominio puede añadir puertos agregados P15 propios. Estos aceptarán
   `TenantAuthorization`, exigirán la capability fuente exacta, recibirán solo rangos,
   `as_of_at`, `knowledge_cutoff_at` y dimensiones cerradas que su contrato admita, y devolverán
   DTO inmutables con valor, coverage, procedencia y versión fuente.
2. People expondrá además la resolución batch histórica de clusters. Los restantes puertos se
   agruparán por familia y evitarán llamadas por fila; un dashboard no compondrá cientos de puertos
   individuales ni consultas N+1.
3. Analytics no importará ORM privado ni ejecutará SQL cross-domain. P15 v1 no crea views o
   materialized views cross-domain, tabla de hechos, read model persistido, snapshot analítico ni
   caché de métricas.
4. Una capability próxima por nombre no concede autoridad. Las cuatro capabilities source-owned
   nuevas y las capabilities existentes exactas son las fijadas en §4.1; en particular,
   `schedule:export` no es permiso genérico para analítica Scheduling.
5. Un índice requerido por benchmark pertenece al módulo fuente y se justifica con la consulta
   medida. Analytics no toma propiedad de tablas o índices ajenos.
6. Si el fan-in síncrono incumple el presupuesto con volumen representativo, se detendrá esa
   decisión y se presentará un ADR específico sobre read models, caché o materialización, con
   autoridad, refresh, invalidación, reconciliación y staleness. No se adopta preventivamente un
   data warehouse.

### 10. Reportes guardados, ejecución y reproducibilidad

1. Un reporte guardado es una definición con métricas/versiones, filtros, dimensiones, orden y
   formato preferido. Tiene propietario usuario/membresía, visibilidad privada o compartida con la
   organización y revisiones append-only. Editar crea revisión; duplicar crea otra definición con
   procedencia; compartir o cambiar visibilidad queda auditado.
2. Compartir no concede autoridad. Un actor solo lista o ejecuta una definición compartida si
   conserva todas las capabilities requeridas por las métricas y dimensiones visibles.
   Propietario/administrador gestionan compartidos; comercial, operaciones y finanzas gestionan sus
   definiciones privadas dentro de su ámbito.
3. Se distinguen tres operaciones:

   - **dashboard/query interactiva:** no crea `ReportExecution` por refresh; devuelve manifest de
     cálculo y solo registra observabilidad técnica sin PII;
   - **ejecución explícita:** persiste revisión, versiones, parámetros, tiempos, límite de
     conocimiento, autorización relevante, versiones fuente, coverage y procedencia, aunque no
     materialice todas las filas;
   - **exportación:** siempre parte de una ejecución persistida y materializa un snapshot exacto,
     auditable e inmutable del resultado exportado.

4. La misma `ReportExecution` produce resultados equivalentes aunque el worker corra después. Cada
   familia debe poder reconsultarse honestamente as-of `knowledge_cutoff_at` o materializar durante
   la ejecución la información mínima necesaria para congelar el resultado. Si una fuente no puede
   garantizarlo, la exportación no se encola como reproducible: la ejecución falla explícitamente o
   exige materialización síncrona acotada; nunca recalcula contra estado nuevo bajo el mismo ID.
5. Un reporte guardado no congela silenciosamente datos. Solo una ejecución/exportación identificada
   como snapshot conserva un resultado concreto.
6. Esa materialización pertenece únicamente a la ejecución/exportación inmutable; no es una tabla
   de hechos reutilizable, un read model transversal ni una segunda verdad para consultas futuras.

### 11. Exportaciones, artefactos y retención

1. CSV se usa para datasets tabulares planos o voluminosos; XLSX para tablas tipadas o varias hojas
   cuando aporten utilidad; PDF solo para reportes de lectura/presentación, no para extractos
   masivos. No toda definición ofrece los tres formatos.
2. Toda exportación registra organización, solicitante usuario/membresía, definición/revisión o
   métricas/versiones, parámetros, periodo, `as_of_at`, `knowledge_cutoff_at`, `executed_at`, estado,
   formato, moneda/partición, coverage, hash, tamaño, filas, creación, expiración nullable, resultado
   o error normalizado y procedencia del artefacto.
3. El contenido se limita al ámbito que el actor podía consultar. Se aplican minimización, nombres
   seguros, MIME exacto, límites de filas/bytes, descarga privada y hash verificable.
4. La protección contra formula injection es type-aware: números legítimos, incluidos negativos,
   siguen siendo numéricos; solo strings interpretables como fórmula se neutralizan. XLSX escribe
   tipos correctos y no habilita fórmulas derivadas de contenido del usuario, macros ni enlaces
   externos activos.
5. Analytics posee el estado y los artefactos de sus exports mediante un puerto privado de
   almacenamiento y un adaptador determinista/local para desarrollo y tests. Puede compartir
   librerías o primitivas stateless neutrales, pero no usa `DocumentJob`, `GeneratedArtifact`,
   estados, grants ni retención P9. Documents no se convierte en repositorio P15.
6. Un object key P15 **publicado** es opaco, inmutable y nunca se sobrescribe. El puerto privado de
   almacenamiento exige creación condicional/write-once (`put_if_absent`) o una primitiva
   equivalente con exclusión atómica. Antes de publicar, el worker obtiene el SHA-256, tamaño y
   formato esperados de los bytes de esa exportación exacta.
7. Si un retry encuentra la key ya creada, lee o inspecciona el objeto existente y compara su
   SHA-256 y tamaño con los esperados. Si coinciden, reutiliza la publicación idempotentemente. Si
   difieren, registra un fallo terminal de integridad, no sobrescribe el objeto ni publica el
   resultado rival. Una key temporal no publicada, si se usa, tendrá identidad separada y nunca
   podrá reemplazar una key consumada.
8. La metadata consumada referencia de forma única la `ReportExecution` y exportación exactas y
   conserva key opaca, SHA-256, tamaño y formato. Una regeneración deliberadamente distinta crea
   otra identidad de exportación/artefacto y otra key; jamás reemplaza los bytes históricos.
9. No se extrae todavía una plataforma general de archivos. Hacerlo requerirá necesidad demostrada
   y ADR específico.
10. P15 no inventa un plazo legal ni purga automáticamente. Puede conservar metadata nullable de
   expiración si aparece una necesidad técnica concreta; mientras no exista política aprobada no
   se afirma retención legal ni se borra físicamente. Perder autorización revoca la descarga aunque
   los bytes permanezcan.
11. Las exportaciones source-owned existentes —incluidos CSV Finance e iCalendar Scheduling— no se
   eliminan, redirigen ni deprecian implícitamente. P15 añade reporting transversal.

### 12. `ExportJob` y worker tenant-aware

1. Analytics tendrá `ExportJob` y ledger de intentos PostgreSQL propios. No reutilizará
   `DocumentJob` ni `CommunicationOutbox`, y no introduce Redis, Celery, broker o worker global con
   `BYPASSRLS`.
2. El ledger conserva organización explícita, orden determinista, claim concurrente con
   `SKIP LOCKED`, lease/reclaim, at-least-once, idempotencia, key determinista de artefacto,
   retry/backoff, fallo terminal y auditoría.
3. Bajo `FORCE RLS` no existe claim global cross-tenant. El worker:

   1. enumera organizaciones mediante una autoridad técnica permitida;
   2. entra en el scope de una organización concreta;
   3. reclama jobs solo de esa organización;
   4. persiste claim/lease y hace commit antes de I/O externo costoso;
   5. procesa sin `BYPASSRLS`;
   6. finaliza o reintenta dentro del mismo tenant scope.

4. El job conserva requester user/membership. Antes de calcular o escribir bytes revalida usuario,
   organización y Membership activos, capabilities P15 y todas las capabilities fuente. Si el
   actor perdió autoridad, no genera el artefacto. La descarga vuelve a revalidar autoridad vigente.
5. At-least-once no promete exactly-once. La seguridad de publicación proviene de la creación
   condicional write-once del §11 y de la verificación del objeto ya publicado; una key determinista
   y un hash guardado, por sí solos, no impiden una sobrescritura ni una carrera con bytes rivales.

### 13. Capabilities, tenancy, RLS y privacidad

1. Las capabilities P15 iniciales, siguiendo `recurso:acción`, son:

   - `analytics:read_dashboard`;
   - `analytics:execute_report`;
   - `analytics:manage_own_report`;
   - `analytics:manage_shared_report`;
   - `analytics:create_export`;
   - `analytics:download_export`.

2. Propietario y administrador reciben el conjunto P15 completo conforme a la política vigente.
   Comercial, Operaciones y Finanzas reciben lectura, ejecución, administración propia y
   crear/descargar exports dentro de su ámbito; no administran compartidos globales sin otra
   decisión.
3. La autorización efectiva es siempre:

   ```text
   capability P15
   ∧ capabilities fuente
   ∧ tenant scope
   ∧ dimensiones permitidas
   ```

   Para exports source-specific se conservan además capabilities de exportación existentes cuando
   su semántica lo exija. `analytics:read_dashboard` nunca sustituye `finance:read`.
4. Toda tabla privada Analytics tendrá `organization_id`, relaciones/unicidades tenant-aware,
   `ENABLE` + `FORCE RLS`, privilegios mínimos y pruebas ORM/SQL directo con `claridez_app`, dos
   tenants y UUID conocido.
5. Definiciones/revisiones, ejecuciones, jobs, intentos y auditoría consumada no tendrán
   `DELETE/TRUNCATE` libre para `claridez_app`. Una futura disposición física requerirá comando y
   política propios sin borrar metadata histórica mediante CRUD.
6. Dashboards y métricas son agregados por defecto. P15 base no exporta teléfonos, correos,
   contenido documental, notas privadas, cuerpos de mensajes, contactos individuales ni detalle
   personal identificable.
7. Cuando un cálculo necesite identidad, usa claves minimizadas y la resolución People as-of sin
   exponer PII. Una exportación nominal futura exige capability fuente explícita, política de
   privacidad, política de retención y decisión posterior.
8. Lecturas detalladas financieras u operativas exigen su autorización explícita y auditoría. Logs
   no contienen contenido exportado, PII, parámetros sensibles, nombres de artefactos aportados por
   usuarios ni storage keys; usan IDs, hashes, contadores, códigos y latencia.

### 14. Migración, frontend y compatibilidad histórica

1. P15 será aditiva sobre P14 final. No existe backfill funcional de métricas y no se fabrican
   ejecuciones, reportes, exports, artefactos ni hechos históricos. Las definiciones code-defined no
   son historia transaccional.
2. Todo puerto histórico devuelve `coverage=complete|partial|unavailable`, `coverage_from` cuando
   proceda y motivo. Un `cutover_state`, snapshot legacy o estado vigente no se transforma en un
   hecho anterior inexistente.
3. El frontend mínimo tendrá dashboard por perfil, selector coherente de periodo, filtros y
   dimensiones autorizados, tablas y gráficos accesibles, estados loading/empty/error/stale,
   reportes guardados, historial de exportaciones y descarga reautorizada.
4. Cada gráfico tendrá alternativa tabular, nombres/leyendas comprensibles y operación por teclado y
   lector de pantalla. En 320 px se priorizan indicadores y tablas refluibles; no se comprime el
   dashboard desktop hasta volverlo ilegible.
5. React no calcula fórmulas de negocio. Presenta valores, manifest, moneda, coverage y staleness
   devueltos por backend.

### 15. Presupuestos verificables de rendimiento

1. P15 hereda del Blueprint API interactiva ordinaria p95 menor a 500 ms, excluyendo proveedores
   externos según la fuente maestra, y LCP de pantallas clave menor a 2,5 s en móvil moderno. No son
   objetivos inventados por este ADR.
2. Antes de cerrar P15 se documentarán un dataset reproducible y, por ruta, Qmax o presupuesto
   equivalente, payload máximo, límites de exportación, concurrencia y tiempo máximo. Las consultas
   críticas conservarán medición SQL y `EXPLAIN (ANALYZE, BUFFERS)`; habrá evidencia p95 y LCP P15.
3. Los tamaños exactos del dataset, filas/bytes y concurrencia son criterios de implementación que
   deben fijarse antes del cierre, pero no cambian esta arquitectura ni bloquean aceptar el ADR.

## Aspectos provisionales

- Los nombres físicos de definiciones, revisiones, ejecuciones, manifests, jobs, intentos,
  auditoría y metadata de artefactos podrán ajustarse durante implementación si preservan estas
  autoridades e invariantes.
- El agrupamiento físico de los puertos batch y DTO puede optimizarse después del benchmark; no
  podrá importar ORM ajeno, omitir versiones ni relajar autorización.
- La presentación y los presets exactos de cada dashboard podrán refinarse sin cambiar el catálogo
  normativo, el ámbito por perfil o la fórmula fuente.

## Asuntos diferidos

- Porcentaje de ocupación/utilización por sede o espacio hasta que Scheduling posea ventanas
  históricas normativas de capacidad disponible; no se acepta denominador sustituto.
- `readiness_blocker_count`: «bloqueador» no corresponde a un único hecho tipado; P15 v1 usa el
  contrato más estrecho `pending_required_verification_count@1`.
- `overdue_operational_item_count`: `PreparationItem` no conserva historia append-only suficiente
  de estado, vencimiento y tiempo de conocimiento para reconstruir cortes anteriores honestamente.
- Un `planned_direct_cost_amount` mutable anterior al baseline: P15 v1 publica únicamente
  `baseline_direct_cost_amount@1`; una futura métrica de plan vigente necesitará historia y
  semántica source-owned inequívocas.
- Métrica de merma de inventario hasta que Resources posea una clasificación normativa, tipada e
  histórica que no dependa de interpretar texto libre.
- Exportaciones nominales o con PII, pendientes de capability fuente, política de privacidad,
  retención y decisión explícitas.
- Plazo legal/operativo, expiración obligatoria, disposición física y purge de artefactos P15.
- Librerías concretas para XLSX/PDF y adaptador de almacenamiento productivo; son decisiones
  técnicas reversibles que se evaluarán antes de añadir dependencias.
- Plataforma neutral de archivos o de jobs, broker/Redis/Celery, data warehouse, read models,
  materialized views y caché; requieren necesidad medida y, si alteran arquitectura, ADR propio.
- Conversión FX y agregación entre monedas; quedan fuera de P15 base y requieren decisión separada.
- Dataset, filas/bytes, concurrencia y tiempos máximos exactos de exportación; se fijan antes del
  cierre P15 sin cambiar por sí solos este ADR.

No se asigna anticipadamente ninguno de estos asuntos a una etapa posterior concreta.

## Validación pendiente

Antes de cerrar la implementación P15 se deberá demostrar, como mínimo:

- reconciliación de cada KPI con casos fuente conocidos y su versión normativa;
- bordes de día/semana/mes/rangos, DST y zona IANA con intervalos `[)`;
- cancelaciones, reprogramaciones, setup/teardown/buffers y ausencia de denominador de ocupación;
- pagos, aplicaciones, ajustes, reversos, devoluciones, schedules históricos y aging as-of;
- reconocimiento, costos, gastos, contribuciones/movimientos de caja, cierres y ajustes de periodos
  anteriores;
- inventario, movimientos, correcciones, indisponibilidades, requerimientos y faltantes;
- merges People antes/después de los cortes sin doble conteo ni reescritura retroactiva;
- cobertura complete/partial/unavailable y ausencia de backfill funcional ficticio;
- dos tenants, `ENABLE` + `FORCE RLS`, `claridez_app`, ORM, SQL directo y UUID conocido;
- perfiles, capabilities P15 y fuente, dimensiones y pérdida de autoridad entre enqueue/worker y
  descarga;
- equivalencia dashboard/ejecución/export y reproducibilidad al ejecutar el worker después;
- privacidad, minimización y ausencia de PII/contenido en logs;
- doble claim, idempotencia, leases, reclaim, retry/backoff, crash y fallo terminal; creación
  condicional sin overwrite, retry que reutiliza bytes con SHA-256 coincidente y rechazo terminal
  ante una key existente con hash/tamaño rival;
- CSV/XLSX formula injection type-aware, tipos numéricos negativos, MIME, nombres, límites de
  filas/bytes y errores de exportación;
- presupuesto Qmax/payload por ruta, volumen/concurrencia representativos,
  `EXPLAIN (ANALYZE, BUFFERS)`, p95 y tiempo máximo de exportación;
- alternativa tabular, teclado, lector de pantalla, estados UI, 320 px y LCP P15.

## Alternativas consideradas

### Crear `analytics` y `reporting` como aplicaciones separadas

Se rechaza porque dividiría un único límite P15, duplicaría autorización y persistencia y haría
ambiguo quién posee reportes y exportaciones.

### Copiar fórmulas fuente en Analytics

Se rechaza porque crea una segunda verdad. En especial, Finance y Receivables conservan todas las
ecuaciones de ADR 0019/0020 y Scheduling conserva la ocupación.

### Calcular ocupación contra 24 horas o existencia del espacio

Se rechaza porque ninguno representa capacidad operativa habilitada. Una métrica no disponible es
más veraz que un porcentaje con denominador inventado.

### Consultar ORM o SQL cross-domain

Se rechaza porque rompe límites, RLS y versionado semántico. Los puertos batch source-owned son la
unidad de integración.

### Crear tabla de hechos, materialized views o warehouse desde v1

Se rechaza sin evidencia de rendimiento. Si el fan-in medido falla, una decisión posterior deberá
explicar autoridad, refresh, invalidación, reconciliación y staleness.

### Reutilizar Documents o Communications para exports

Se rechaza. Sus jobs, outbox, artefactos y políticas son estado de dominio P9/P14. Analytics posee
su ledger y almacenamiento privado sin convertirlos en infraestructura transversal.

### Instalar broker, Redis o Celery

Se rechaza para P15 base. PostgreSQL ya demuestra claim tenant-aware y satisface la arquitectura
conocida; una nueva dependencia operativa exige necesidad medida.

## Consecuencias

### Positivas

- Las métricas son explicables y versionadas sin desplazar la autoridad de los dominios fuente.
- Tiempo económico, estado as-of y conocimiento dejan de confundirse.
- Finance/Receivables, monedas y cierres preservan sus distinciones normativas.
- Reportes y exports son reproducibles y auditables dentro de autorización conjuntiva.
- El primer diseño evita warehouse, caché, plataforma de jobs y almacenamiento genérico prematuros.

### Costes y riesgos

- Los dominios fuente deberán añadir puertos batch, versiones semánticas e índices medidos.
- La reproducibilidad exige historia suficiente o materialización acotada en la ejecución; algunos
  rangos legacy seguirán parciales/no disponibles.
- El fan-in síncrono debe probarse con volumen y puede requerir una decisión posterior si no cumple
  el presupuesto.
- ExportJob añade otro ledger especializado y exige reautorización en enqueue, ejecución y descarga.

## Evidencia

- [Blueprint maestro](../product/PRODUCT_BLUEPRINT.md)
- [Roadmap de entrega](../product/PRODUCT_DELIVERY_ROADMAP.md)
- [Handoff vigente](../PROJECT_HANDOFF.md)
- [ADR 0004 — Diferir infraestructura asíncrona](0004-defer-asynchronous-infrastructure.md)
- [ADR 0009 — Aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)
- [ADR 0015 — People, CRM y autoridad comercial](0015-people-crm-boundaries-and-commercial-authority.md)
- [ADR 0016 — Scheduling e integridad temporal](0016-scheduling-ownership-and-temporal-integrity.md)
- [ADR 0019 — Receivables e integridad financiera](0019-receivables-authority-and-financial-movement-integrity.md)
- [ADR 0020 — Finance, reconocimiento y cierres](0020-finance-authority-recognition-and-operational-close-integrity.md)
- [ADR 0021 — Resources, inventario y procedencia](0021-resources-supply-inventory-and-financial-provenance-integrity.md)
- [ADR 0022 — Operación avanzada](0022-advanced-operations-plans-and-execution-integrity.md)
- [ADR 0023 — Experiencia externa, comunicaciones y portal](0023-external-client-experience-communications-and-portal-integrity.md)
- Puertos públicos, modelos, migraciones, capabilities, OpenAPI, frontend y workers vigentes de los
  dominios fuente, inspeccionados antes de aceptar este ADR.
