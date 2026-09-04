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

Todos los identificadores de esta tabla son `metric_id@1` del catálogo P15. Las referencias fuente
son también versionadas; las fórmulas completas source-owned se publicarán en el contrato del
puerto propietario antes de abrir el endpoint.

| Familia | Métricas P15 v1 | Propietario y modo temporal |
| --- | --- | --- |
| Embudo comercial | `request_created_count`, `quote_issued_count`, `quote_accepted_count`, `closed_lost_request_count`, `closed_lost_latest_issued_quote_amount`, `accepted_quote_amount`, `open_issued_quote_amount` | Commercial; hechos de creación/emisión/aceptación/cierre perdido en periodo o estado abierto al corte según el identificador |
| Actividad comercial | `first_outbound_response_elapsed_seconds`, `open_request_without_next_action_count` | CRM; primera interacción saliente respecto del hecho de creación y estado/tarea al corte |
| Venta confirmada | `confirmed_sale_count`, `confirmed_sale_amount` | Finance mediante `finance.public`; hecho económico de primera confirmación de raíz conforme ADR 0020 |
| Conversión transversal | `request_to_confirmed_sale_conversion_rate`, `distinct_canonical_request_person_count` | Analytics; cohorte Commercial contrastada con confirmación fuente y clusters People históricos |
| Agenda | `confirmed_event_minutes`, `confirmed_occupied_minutes`, `confirmed_reservation_count`, `blocked_minutes`, `reservation_cancelled_count`, `reservation_rescheduled_count` | Scheduling; intervalo/estado al corte o hecho de cancelación/reprogramación en periodo |
| Ejecución operativa | `preparation_open_count`, `readiness_blocker_count`, `overdue_operational_item_count`, `execution_completed_count`, `phase_duration_seconds`, `incident_count`, `post_event_close_elapsed_seconds` | Operations; estado al corte o hechos append-only de fase, incidencia, ejecución y cierre |
| Cartera | `obligation_original_amount`, `payment_received_amount`, `payment_unapplied_amount`, `application_net_amount`, `adjustment_net_amount`, `movement_reversal_amount_by_target`, `refund_recorded_amount`, `open_balance_amount`, `aging_open_balance_amount`, `expected_collection_amount` | Receivables; hechos en periodo o estado/aging al corte con revisión de calendario aplicable |
| Finanzas | `recognized_revenue_amount`, `planned_direct_cost_amount`, `actual_direct_cost_amount`, `variable_expense_amount`, `recurring_expense_amount`, `cash_inflow_amount`, `cash_outflow_amount`, `net_cash_flow_amount`, `gross_margin_amount`, `contribution_margin_amount`, `operating_result_amount`, `profitability_rate` | Finance; `OperationalPeriod` y snapshot de cierre, o semántica provisional explícita para periodo abierto |
| Recursos e inventario | `stock_on_hand_quantity`, `stock_movement_quantity`, `event_required_quantity`, `event_allocated_quantity`, `event_shortage_quantity`, `resource_unavailability_quantity` | Resources; saldo al corte, movimiento ocurrido en periodo o necesidad/indisponibilidad sobre intervalo |

Reglas adicionales del catálogo:

1. Por convención, una métrica source-owned referencia `<dominio>.<metric_id>@1`; el puerto fuente
   devuelve esa pareja exacta. Las composiciones `request_to_confirmed_sale_conversion_rate@1` y
   `distinct_canonical_request_person_count@1` fijan respectivamente
   `commercial.request_created_cohort@1 + finance.confirmed_sale_cohort@1` y
   `commercial.request_person_cohort@1 + people.canonical_cluster_as_of@1` como contratos fuente.
2. `closed_lost_request_count` cuenta la transición autoritativa de `EventRequest` a
   `closed_lost`; `closed_lost_latest_issued_quote_amount` usa la última versión emitida de esa
   solicitud visible en esa transición. Un `cutover_state` terminal no fabrica el hecho.
3. `open_issued_quote_amount` incluye solo la versión emitida vigente de solicitudes abiertas en el
   corte definido por Commercial; excluye borradores, versiones sustituidas/retiradas y estados
   terminales. Commercial fija y prueba la transición exacta, sin que Analytics lea su ORM.
4. `request_to_confirmed_sale_conversion_rate` es
   `solicitudes distintas de la cohorte que alcanzaron primera confirmación visible al as_of_at /
   solicitudes distintas elegibles creadas en la cohorte * 100`; devuelve no calculable si el
   denominador es cero y conserva las versiones Commercial y de la confirmación fuente.
5. `distinct_canonical_request_person_count` cuenta clusters People distintos, resueltos as-of el
   corte histórico y de conocimiento, con al menos una solicitud elegible en la cohorte. No expone
   nombres ni contactos.
6. `confirmed_event_minutes` usa el intervalo del evento. `confirmed_occupied_minutes` usa la
   ocupación real de Scheduling y sus snapshots de setup, teardown y buffers; no son sinónimos.
7. `blocked_minutes` solo devuelve un valor cuando Scheduling acredita historia autoritativa
   suficiente. En otro caso conserva el identificador y responde `partial` o `unavailable` con
   motivo, nunca cero inventado.
8. `movement_reversal_amount_by_target` exige la dimensión cerrada de tipo de objetivo; las demás
   métricas de movimiento conservan dirección. Ninguna se presenta como «neto de caja». Resources
   conserva kind/dirección/unidad y no suma unidades incompatibles.
9. `profitability_rate` conserva el caso no calculable de ADR 0020 cuando el ingreso reconocido es
   cero; no lo transforma en cero por presentación.

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
4. Una capability próxima por nombre no concede autoridad. `schedule:export`, por ejemplo, no es
   permiso genérico para analítica Scheduling. Cada puerto declara la capacidad fuente exacta; si
   ninguna vigente representa esa lectura, se añadirá una capability estrecha propiedad del
   dominio fuente antes de exponerla.
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
6. No se extrae todavía una plataforma general de archivos. Hacerlo requerirá necesidad demostrada
   y ADR específico.
7. P15 no inventa un plazo legal ni purga automáticamente. Puede conservar metadata nullable de
   expiración si aparece una necesidad técnica concreta; mientras no exista política aprobada no
   se afirma retención legal ni se borra físicamente. Perder autorización revoca la descarga aunque
   los bytes permanezcan.
8. Las exportaciones source-owned existentes —incluidos CSV Finance e iCalendar Scheduling— no se
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
5. At-least-once no promete exactly-once: la combinación de ejecución inmutable, idempotencia, key
   determinista y hash impide publicar dos resultados distintos para el mismo intento lógico.

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
- doble claim, idempotencia, leases, reclaim, retry/backoff, crash, fallo terminal y key/hash de
  artefacto deterministas;
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
