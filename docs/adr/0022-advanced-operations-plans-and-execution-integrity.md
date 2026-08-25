# ADR 0022 — Autoridad de operación avanzada, planes operativos e integridad de ejecución P13

- **Estado:** Aceptado
- **Fecha:** 2026-08-25
- **Reemplaza a:** No aplica; amplía ADR 0013 y refina ADR 0016 y ADR 0021 en los puntos
  expresamente indicados, sin sustituir sus autoridades
- **Reemplazado por:** No aplica

## Contexto

La Iteración 5.2 creó `claridez.operations`, `EventPreparation`, su checklist de readiness, su
historia de revisiones y transiciones, y un guardián PostgreSQL capaz de preservar el contrato ante
ORM bulk y SQL directo. P8 trasladó a `claridez.scheduling` la autoridad temporal. P9 creó la
plataforma documental privada. P11 vinculó el reconocimiento de ingreso operativo al hecho
`execution_completed`. P12 creó `claridez.resources` y dejó para P13 las ventanas de recursos
específicas de montaje y desmontaje.

P13 debe ampliar la coordinación real de montaje, ejecución, desmontaje y cierre postevento sin
reinterpretar el checklist 5.2, crear otra máquina de estados, inventario, agenda, repositorio de
archivos, nómina o gestor genérico de proyectos. También debe permitir que una necesidad temporal
propiedad de Operations sea utilizada por Resources sin degradar la garantía PostgreSQL P12, que
hoy exige igualdad entre `resource_interval` y `Reservation.event_interval`.

El propietario aprobó el plan P13 corregido y las decisiones finales sobre inmutabilidad del
readiness derivado de plantilla y procedencia persistente de ventanas operacionales. Este ADR fija
la arquitectura previa a implementación. No autoriza todavía modelos, migraciones, capabilities
ejecutables, servicios, endpoints, frontend ni lógica funcional P13.

## Decisiones aceptadas

### 1. Autoridad modular

1. `claridez.operations` es la autoridad P13 sobre planes y snapshots operativos, readiness
   derivado de plantilla, verificaciones de fases, responsabilidades operativas por evento,
   incidencias, cambios autorizados, necesidades temporales de recursos y cierre postevento.
2. `claridez.commercial` conserva solicitud, cotización, aceptación y estado comercial.
   Operations consumirá Commercial exclusivamente mediante `claridez.commercial.public`.
3. `claridez.scheduling` conserva en exclusiva raíz y reserva, espacio, `event_interval`,
   `setup_minutes`, `teardown_minutes`, buffers, `occupied_interval`, conflictos e historia
   temporal.
4. `claridez.resources` conserva proveedores, capacidad, reserva y asignación de recursos,
   disponibilidad, faltantes, custodia, movimientos, mantenimiento e indisponibilidad. Operations
   expresa una necesidad y consume asignaciones, faltantes, proveedores y estados mediante DTO
   inmutables de `resources.public`; no importa modelos P12 ni escribe inventario.
5. `claridez.documents` conserva expedientes, artefactos, archivos privados, evidencia, acceso y
   retención. P13 solo almacena referencias tenant-aware a objetos documentales autorizados.
6. `claridez.organizations` conserva organización, membresías, sedes y autorización;
   `claridez.people` conserva identidad de persona; `claridez.catalog` conserva tipos y oferta
   vendible; `claridez.finance` conserva costos, gastos, caja, reconocimiento y rentabilidad.
7. Se crearán o ampliarán puertos públicos estrechos suficientes de Scheduling, Resources,
   Documents, Organizations y Catalog. Una FK física tenant-aware no autoriza importar modelos ni
   asumir autoridad funcional ajena.

### 2. Continuidad de EventPreparation y significado de completed

1. `EventPreparation` sigue siendo el agregado de la operación y conserva exactamente los estados
   `preparing`, `ready`, `in_progress`, `completed`, `cancelled` y `rescheduled`.
2. P13 no introduce `closing`, `closed` ni otro estado en esa máquina.
3. `completed` conserva exclusivamente el hecho `execution_completed`: la ejecución terminó y
   puede activar el reconocimiento de ingreso de ADR 0020. No significa que devoluciones,
   incidencias, evidencia o cierre postevento estén terminados.
4. El cierre postevento es un hecho separado, único por preparación, inmutable y append-only. Sus
   correcciones posteriores son hechos nuevos; no reabren ni reescriben `completed`.
5. Se preservan la historia, las revisiones, la idempotencia y el guardián PostgreSQL de 5.2. P13
   añade invariantes conjuntivas, no sustituye ese contrato.

### 3. Readiness 5.2 y verificaciones P13

1. `PreparationItem` continúa siendo exclusivamente el checklist de preparación/readiness. Llegar
   a `ready` sigue exigiendo que todos los ítems obligatorios existentes estén resueltos y que la
   revisión final baseline esté completada.
2. Todo `PreparationItem` declara exactamente una procedencia cerrada:

   - `baseline_5_2`: una de las siete claves y significados de `operations-5.2-v1`;
   - `manual`: ítem libre creado expresamente durante preparación;
   - `p13_template_readiness`: ítem de readiness materializado desde una definición del snapshot
     P13.

3. Se refina ADR 0016: solo `source_kind=manual` constituye un ítem libre trasladable a una
   preparación sucesora. Que `baseline_key` sea nulo no basta. Un ítem de plantilla no se copia
   como libre; la preparación sucesora lo vuelve a derivar del plan aplicable.
4. Las verificaciones de montaje real, ejecución, desmontaje y postevento usan estructuras P13
   tipadas distintas, vinculadas al mismo `EventPreparation` y snapshot. Sus fases son exactamente
   `setup`, `execution`, `teardown` y `post_event`, y sus estados son `pending`, `completed` y
   `not_applicable` con razón obligatoria para este último.
5. Una definición declara la única fase a la que pertenece. Una verificación `setup` puede
   cumplirse durante preparación y sus obligatorias bloquean el inicio de ejecución, no `ready`.
   Las de `execution` solo se cumplen durante `in_progress` y bloquean `completed`. Las de
   `teardown` y `post_event` solo se cumplen después de `completed` y bloquean el cierre
   postevento.
6. `setup` y `teardown` describen verificaciones del trabajo realmente realizado; nunca redefinen
   los minutos, buffers ni `occupied_interval` que Scheduling usa para autorizar la ocupación.
7. Las fases son un catálogo cerrado. No existen subtareas libres, dependencias arbitrarias,
   grafos, tableros, estimaciones genéricas ni otros elementos de gestión de proyectos.

### 3.1. Cronología operativa observada

1. P13 registra hechos temporales explícitos y append-only para el inicio y la finalización de las
   fases observables que requieren duración operacional.
2. `execution` conserva una única cronología: usa exclusivamente las transiciones 5.2
   `execution_started` y `execution_completed` y sus marcas autoritativas
   `EventPreparation.started_at/completed_at`. P13 no crea hechos paralelos de ejecución.
3. `setup` y `teardown` registran cada uno un hecho de inicio y otro de finalización con
   organización, preparación, fase, actor, instante observado, revisión esperada, clave
   idempotente, procedencia y hash canónico.
4. Esos hechos describen trabajo observado. No modifican ni reinterpretan `setup_minutes`,
   `teardown_minutes`, buffers, `event_interval` u `occupied_interval` de Scheduling.
5. Una corrección temporal es un hecho append-only enlazado al hecho corregido, con valor efectivo,
   razón, actor, revisión e idempotencia. Nunca actualiza ni elimina el hecho original.
6. La cronología efectiva debe ser compatible con EventPreparation y la fase: no puede finalizar
   antes de iniciar, repetir un inicio o finalización ya consumados ni confirmar una secuencia
   imposible. Constraints y guardianes diferidos protegen la regla también ante ORM bulk y SQL
   directo.
7. La duración observada de `setup` y `teardown` se deriva exclusivamente de sus hechos temporales
   efectivos. No se infiere de la primera o última verificación completada. La duración de
   `execution` se deriva exclusivamente de los hechos 5.2 existentes.
8. `post_event` no recibe una duración artificial. Solo podría obtener cronología propia mediante
   una decisión funcional futura que identifique un hecho concreto y requiera otro ADR si altera
   este contrato.
9. Las verificaciones mantienen únicamente `pending`, `completed` y `not_applicable`; no se añade
   un `in_progress` genérico ni otra máquina de estados de EventPreparation.

### 4. Inmutabilidad del readiness derivado de plantilla

1. Un `PreparationItem` `p13_template_readiness` mantiene una referencia tenant-aware a su
   definición inmutable dentro del snapshot del evento.
2. Quedan congelados por esa definición y su procedencia:

   - organización, preparación, `source_kind`, snapshot y definición de origen;
   - clave de definición, identidad idempotente y procedencia de traslado, que debe ser nula;
   - título, sección, obligatoriedad, fecha relativa resuelta, rol operativo requerido y orden
     relativo entre definiciones de plantilla;
   - la ausencia de `baseline_key`, porque un ítem P13 no suplanta una clave 5.2.

3. Durante `preparing` o `ready` pueden cambiar normalmente el responsable concreto —si satisface
   el rol requerido—, `status`, `status_note`, notas operativas y los hechos derivados
   `resolved_at`/`resolved_by`. La posición absoluta puede variar por inserción o reordenamiento de
   ítems manuales, pero no puede invertir el orden relativo de definiciones P13.
4. Las instrucciones canónicas pertenecen a la definición inmutable; las notas editables no las
   reescriben ni forman otra definición.
5. Alterar título, sección, obligatoriedad, fecha resuelta, rol requerido u orden relativo requiere
   una propuesta con `operation:manage` y una autorización con
   `operation_change:authorize`. Solo se admite en `preparing` o `ready`; si deja de cumplirse el
   readiness, la autorización reabre atómicamente a `preparing` conforme a la historia 5.2.
6. Proponer y autorizar son actos distintos, pero no se exige que pertenezcan a dos personas
   distintas cuando una misma membresía posee ambas capabilities.
7. La desviación no modifica la definición. Un ledger `ReadinessDeviation` —nombre físico
   provisional— registra definición, valores anterior y efectivo, razón, proponente, autorizador,
   revisiones esperadas, clave idempotente, hash y tiempo. El ítem es una proyección efectiva de la
   definición más la cadena válida de desviaciones; corregir añade otro hecho.
8. PostgreSQL protegerá la forma cerrada de cada procedencia, las identidades y referencias
   inmutables con FKs/checks y triggers inmediatos. Un guardián diferido comprobará que la
   proyección efectiva coincide con definición más desviaciones autorizadas. Definiciones,
   snapshots y desviaciones carecerán de `UPDATE`, `DELETE` y `TRUNCATE` para el rol de aplicación.
   `QuerySet.update`, `bulk_create`, `bulk_update` y SQL directo incoherentes fallarán con
   `SQLSTATE 23514`.
9. Los ítems `manual` conservan el comportamiento editable 5.2, sujeto a estados, revisión,
   idempotencia y auditoría vigentes. Esta inmutabilidad selectiva no convierte todo
   `PreparationItem` en inmutable.
10. Los siete baseline conservan su versión, claves, significado y guardianes. Se etiquetan
    `baseline_5_2` solo para declarar su procedencia; nunca se reinterpretan como plantilla P13 ni
    como fallback del sistema. P13 no les añade un régimen retroactivo de inmutabilidad ni cambia
    la edición controlada que 5.2 ya permite.

### 5. Plantillas, fallback y snapshot del evento

1. Una plantilla operacional pertenece a una organización y tipo de evento. Sus revisiones son
   borradores hasta publicación; cada versión publicada es inmutable y solo puede retirarse para
   impedir usos futuros.
2. Una versión contiene definiciones cerradas de readiness P13, verificaciones por fase, roles y
   necesidades operativas de recursos. No contiene tareas libres ni reserva capacidad por sí sola.
3. Cada nueva preparación P13 congela un snapshot con fuente `organization` o `system`, identidad y
   versión de plantilla, hash canónico, definiciones materializadas, roles y necesidades. Publicar
   o cambiar una plantilla solo afecta eventos futuros.
4. Si no existe una versión organizacional publicada aplicable, se usa explícitamente
   `operations-p13-system-v1`: versión de sistema identificable, versionada e inmutable que no
   añade requisitos organizacionales y conserva funcionalmente el flujo mínimo 5.2.
5. La ausencia de una plantilla organizacional publicada no bloquea por sí sola la confirmación
   comercial: el fallback se selecciona y registra atómicamente al crear la preparación aplicable.
6. El fallback no transforma las siete baseline en definiciones P13. El snapshot registra la
   versión de sistema, mientras el checklist baseline sigue procediendo de
   `operations-5.2-v1`/`baseline_5_2`.
7. Un evento nunca consulta una plantilla mutable para reconstruir su historia. Todo cambio
   posterior se expresa mediante un nuevo plan para eventos futuros o mediante el flujo autorizado
   de desviación/cambio del evento.

### 6. Responsabilidades operativas

1. P13 reutiliza `EventPreparation.responsible_membership` como coordinación principal y permite
   responsabilidades por evento y fase mediante membresías activas de la misma organización.
2. Los roles operativos pertenecen a la versión/snapshot y forman un vocabulario cerrado por plan;
   una asignación identifica rol, fase, membresía responsable y vigencia dentro del evento.
3. P13 no crea empleados, contratos laborales, disponibilidad personal, horas trabajadas, turnos,
   asistencia, remuneración ni nómina. People conserva identidad y Organizations membresías.

### 7. Incidencias y evidencia

1. Los tipos son `safety`, `schedule_or_space`, `resource`, `supplier`, `service_quality`,
   `customer_scope` y `other_operational`; las severidades son `low`, `medium`, `high` y
   `critical`.
2. Una incidencia nace `open`; las transiciones ordinarias permitidas son `open -> contained`,
   `open -> resolved` y `contained -> resolved`. No hay mutación regresiva: una recurrencia abre una
   incidencia enlazada nueva y una corrección agrega un hecho sin reescribir los anteriores.
3. La identidad, tipo, evento, instante reportado y autor son inmutables. Responsable, impacto,
   contención, resolución y correcciones se registran como eventos append-only con revisión y
   claves idempotentes; no se reescribe la historia.
4. Toda evidencia es una referencia autorizada a Documents. La incidencia no contiene blobs,
   rutas públicas ni un almacenamiento paralelo.

### 8. Cambios autorizados durante ejecución

1. Cambios a verificaciones, responsables, necesidades o ventanas se proponen con
   `operation:manage` y se autorizan con `operation_change:authorize`. Cada propuesta fija alcance,
   antes/después, razón, revisión esperada, impacto, actor y clave idempotente.
2. La autorización crea una decisión append-only y una nueva proyección efectiva; no reescribe el
   snapshot ni hechos ya ejecutados. Repetir la misma clave y payload devuelve el mismo resultado;
   reutilizarla con otro payload falla.
3. Una verificación ya cumplida, una ejecución iniciada o terminada, una incidencia reportada, un
   movimiento/custodia P12, una evidencia emitida y un cierre postevento son hechos inmutables. Un
   error se corrige con un hecho enlazado.
4. Durante `in_progress` solo cambian aspectos pendientes cuya autoridad siga disponible. Cambiar
   espacio o tiempo exige primero un comando autorizado de Scheduling; cambiar asignación,
   capacidad o custodia exige Resources.

### 9. Ventana operacional P13

1. Una ventana operacional expresa el intervalo exacto `[inicio, fin)` durante el cual una
   necesidad P13 requiere que un recurso esté disponible. Operations es autoridad de esa
   necesidad, no de disponibilidad, capacidad, asignación, movimiento ni ocupación del espacio.
2. `OperationalResourceWindow` —nombre físico provisional— tiene identidad persistente e
   inmutable y conserva, como mínimo:

   - organización, `EventPreparation`, raíz y reserva;
   - snapshot del plan y necesidad operacional exacta;
   - `required_interval`, revisión propia y predecesora cuando exista;
   - procedencia `organization_template`, `system_template` o `authorized_change`, versión de
     plantilla o decisión autorizante y hash canónico;
   - identidad y revisión de Reservation, ScheduleAllocation y ScheduleEvent que sustentan la
     proyección temporal.

3. La ventana se deriva de anclas relativas de la misma versión de plan contra la autoridad
   persistida de Scheduling. No es una copia mutable de agenda ni puede editar libremente instantes
   absolutos.
4. Una ventana inicial puede materializarse mientras la preparación sea editable. Después, solo
   una decisión autorizada puede crear una revisión sucesora; nunca se actualiza la ventana
   anterior. Los hechos ya ejecutados no cambian de ventana.
5. Operations entrega a `resources.public` un DTO inmutable con identidad de ventana,
   organización, raíz, reserva, necesidad, intervalo, versión/hash y procedencia Scheduling.
   Resources vuelve a validar bajo lock y no confía en datos del cliente.

### 10. Concordancia estructural con Scheduling

1. `ScheduleEvent.new_snapshot` es evidencia append-only, pero no es por sí solo una fuente
   suficiente para autorizar una ventana. Un JSON, incluso bien formado, no sustituye la
   concordancia estructural con las filas autoritativas.
2. El guardián P13 debe comprobar conjuntamente, mediante relaciones tenant-aware persistentes:

   - misma organización, raíz y reserva entre EventPreparation, Reservation y ventana;
   - ScheduleAllocation correspondiente a esa reserva y su espacio;
   - `source_event`, `source_revision`, identificadores de reserva/predecesora/sucesora y
     `aggregate_revision` coherentes con el tipo de ScheduleEvent;
   - revisión y estado autoritativos de Reservation coherentes con la asignación;
   - `occupied_interval` autoritativo de ScheduleAllocation y
     `required_interval <@ occupied_interval`.

3. Una ventana fuera de `occupied_interval` falla cerradamente. Operations no puede ampliar de
   facto la ocupación por una ventana, un requerimiento P12 ni SQL directo; debe obtener primero un
   cambio autorizado en Scheduling.
4. Las FKs compuestas, checks y triggers diferidos impedirán que una fila ScheduleEvent fabricada
   o un `new_snapshot` manipulado eluda esas comparaciones. La autoridad es la concordancia entre
   Reservation, ScheduleAllocation, ScheduleEvent y sus revisiones, no el JSON aislado.

### 11. Procedencia temporal cerrada en Resources

1. `ResourceRequirement` porta la procedencia temporal autoritativa y exactamente una de estas
   ramas:

   - `scheduling_event_interval`: procedencia P12/legacy, sin ventana Operations y con
     `resource_interval = Reservation.event_interval`;
   - `operations_window`: procedencia P13, con FK tenant-aware no nula a una ventana Operations
     autorizada e inmutable y con `resource_interval = required_interval` de esa ventana.

2. `ResourceAssignment` y `ResourceCapacityAllocation` no mantienen discriminadores de
   procedencia independientes. Heredan rama, organización, raíz, reserva e intervalo a través del
   requerimiento; el guardián exige su correspondencia exacta.
3. El discriminador es un conjunto cerrado y conjuntivo. Un valor arbitrario, una ventana nula en
   la rama P13, una ventana presente en legacy o cualquier intervalo divergente falla con
   `SQLSTATE 23514`.
4. En la rama P13, además de la igualdad exacta con la ventana, PostgreSQL vuelve a comprobar la
   concordancia estructural Scheduling y la contención en `occupied_interval`. Cambios directos en
   Operations, Resources o Scheduling que dejen el grafo incoherente fallan al cierre de la
   transacción.
5. Resources sigue decidiendo si existe capacidad y creando sus reservas, asignaciones,
   custodias, movimientos y estados. Una ventana válida no garantiza disponibilidad ni satisface
   un requerimiento.

### 12. Reprogramación y cancelación

1. Se preserva ADR 0016: solo preparaciones `preparing` o `ready` pueden reprogramarse. Scheduling
   crea la reserva sucesora y Operations conserva la predecesora como `rescheduled`.
2. La sucesora congela un nuevo snapshot de evento derivado de la misma versión inmutable de plan,
   pero recalcula verificaciones pendientes y ventanas desde anclas relativas contra la nueva
   Reservation, ScheduleAllocation y ScheduleEvent. No copia instantes absolutos ni hechos ya
   ejecutados.
3. Solo ítems `manual` seleccionados se trasladan. Baseline se recrea por 5.2 y readiness P13 se
   materializa de nuevo desde el snapshot aplicable, conservando procedencia explícita.
4. Resources libera o sustituye exclusivamente compromisos pendientes conforme a ADR 0021. La
   nueva ventana no mueve por sí sola capacidad, inventario ni custodia.
5. La cancelación conserva plan, snapshot, ventanas, incidencias, evidencia y decisiones. Libera
   solo compromisos pendientes permitidos por Scheduling y Resources; nunca borra hechos
   ejecutados, movimientos, custodia ni historia.

### 13. Cierre postevento

1. Solo una preparación `completed` puede registrar cierre postevento. El comando adquiere locks,
   fija revisiones y fuentes consultadas y crea un hecho único append-only con hash e idempotencia.
2. Para cerrar deben cumplirse o estar justificadamente `not_applicable` las verificaciones
   obligatorias `teardown` y `post_event`; no puede haber cambios propuestos pendientes ni
   incidencias `open`. Una incidencia `contained` de severidad `low` o `medium` puede quedar con
   responsable, impacto y seguimiento explícitos; `high` o `critical` debe estar `resolved`.
3. Los estados reales de `ResourceRequirement` se interpretan así:

   - `open` bloquea;
   - `shortage` puede conservarse honestamente si el evento se ejecutó pese al faltante, existe
     incidencia y evidencia explícitas de su consecuencia y no hay compromiso físico pendiente;
   - `satisfied` exige que sus asignaciones no dejen custodia o reserva pendientes;
   - `cancelled` solo es válido si Resources produjo legítimamente esa transición; nunca se usa
     para ocultar un faltante histórico.

4. Los estados reales de `ResourceAssignment` se interpretan así: `reserved` y `custody` bloquean;
   `issued` es terminal para consumibles, `fulfilled` para servicios y `returned` para reutilizables
   o activos; `released` y `cancelled` son terminales de compromiso, pero si el recurso requerido
   no se usó debe existir cambio autorizado o incidencia coherente.
5. Un faltante histórico conocido no equivale a un recurso pendiente de devolución. `shortage`
   puede sobrevivir al cierre bajo el punto anterior; cualquier custodia física pendiente bloquea.
6. El cierre congela referencias, estados y hashes observados de Operations, Resources y
   Documents. Hechos tardíos se registran como correcciones enlazadas y no reescriben ni reabren el
   cierre.

### 14. Capabilities P13

Se conserva la matriz 5.2 y se añaden exactamente estas capabilities:

| Capability                   | Propietario | Administrador | Comercial | Operaciones | Finanzas |
| ---------------------------- | ----------- | ------------- | --------- | ----------- | -------- |
| `operation:read`             | Sí          | Sí            | Sí        | Sí          | No       |
| `operation:manage`           | Sí          | Sí            | No        | Sí          | No       |
| `operation:execute`          | Sí          | Sí            | No        | Sí          | No       |
| `operation_template:read`    | Sí          | Sí            | No        | Sí          | No       |
| `operation_template:manage`  | Sí          | Sí            | No        | Sí          | No       |
| `operation_incident:read`    | Sí          | Sí            | No        | Sí          | No       |
| `operation_incident:manage`  | Sí          | Sí            | No        | Sí          | No       |
| `operation_change:authorize` | Sí          | Sí            | No        | Sí          | No       |
| `operation_evidence:read`    | Sí          | Sí            | No        | Sí          | No       |
| `operation_evidence:manage`  | Sí          | Sí            | No        | Sí          | No       |
| `operation:close`            | Sí          | Sí            | No        | Sí          | No       |

Una acción intermodular requiere además las capabilities del módulo propietario. P13 no concede a
Operaciones autorización para crear personas, cambiar agenda, reservar recursos, modificar
inventario, emitir documentos ni registrar finanzas.

### 15. PostgreSQL, concurrencia e idempotencia

1. Toda tabla privada P13 tendrá `organization_id`, RLS `ENABLE` + `FORCE`, políticas basadas en el
   GUC autorizado y FKs/uniques compuestas tenant-aware cuando cruce agregados privados.
2. El rol de aplicación tendrá privilegios mínimos. Ledgers, snapshots, versiones publicadas,
   ventanas, incidencias consumadas, decisiones y cierres no tendrán `DELETE`/`TRUNCATE`; los
   hechos inmutables tampoco tendrán `UPDATE`.
3. Los comandos exigen revisión esperada e idempotencia persistente por organización, acción y
   clave. Repetición con igual payload reproduce resultado; payload distinto entra en conflicto.
4. Los locks siguen un orden determinista: raíz/reserva y espacio Scheduling; EventPreparation y
   agregados P13; requerimientos, recursos, activos y ubicaciones P12 ordenados por UUID; identidad
   documental cuando corresponda. No se invierte el orden aprobado por ADR 0016/0021.
5. Constraints, triggers inmediatos y guardianes diferidos protegen también `QuerySet.update`, ORM
   bulk y SQL directo. Las inconsistencias conjuntivas fallan antes del commit con códigos SQL
   estables; una corrección funcional añade hechos compensatorios.

### 16. Migración y cutover desde P12

1. La migración clasifica determinísticamente los siete ítems por sus claves como
   `baseline_5_2` y los demás ítems existentes como `manual`. No altera título, sección,
   obligatoriedad, posición, estado, evidencia, revisiones ni significado histórico.
2. No se inventan plantillas, snapshots P13, ventanas, verificaciones de fase, roles, incidencias,
   decisiones, evidencia ni cierres para eventos históricos.
3. Los requerimientos P12 existentes conservan la rama `scheduling_event_interval` y la igualdad
   exacta con `Reservation.event_interval`.
4. Preparaciones activas al cutover reciben, solo si entran explícitamente al flujo P13, un snapshot
   `legacy_cutover` que describe el estado observado y no afirma que existió una plantilla previa.
   Eventos terminales anteriores no adquieren cierre postevento P13 retrospectivo.
5. El cutover valida primero coherencia 5.2, Scheduling y Resources, materializa solo datos
   deterministas, instala guardianes y RLS y vuelve a auditar bajo el rol de aplicación. Cualquier
   contradicción detiene la migración afectada.

### 17. Métricas operativas

P13 puede derivar tiempo hasta readiness, duración observada de setup/ejecución/teardown, avance de
verificaciones, incidencias por tipo/severidad y tiempo de resolución, cambios autorizados, ciclo
de cierre y consecuencias de faltantes/devoluciones desde DTO P12. Setup/teardown usan
exclusivamente sus hechos temporales efectivos y execution las marcas 5.2; ninguna duración se
infiere del orden de resolución de verificaciones. No calcula ni duplica ingreso, costo, margen,
utilidad, caja ni rentabilidad P11.

## Aspectos provisionales

1. Los nombres físicos `OperationalResourceWindow` y `ReadinessDeviation` pueden ajustarse durante
   implementación sin cambiar identidad, procedencia, inmutabilidad ni guardianes aceptados.
2. La representación exacta de anclas relativas y los nombres de índices/checks se cerrarán con la
   migración, siempre dentro del contrato funcional aprobado.

## Asuntos diferidos

1. Turnos, asistencia, horas trabajadas, nómina y disponibilidad laboral.
2. Gestión genérica de proyectos, dependencias arbitrarias, automatizaciones de tareas y portales
   colaborativos.
3. Logística avanzada, rutas, transporte, telemetría, IoT y optimización automática de recursos.
4. Nuevos proveedores externos, almacenamiento alternativo y una agenda paralela.
5. La forma exacta de endpoints y frontend; requerirá aprobación de implementación y no será CRUD
   genérico.

## Validación pendiente para la implementación

1. Migraciones PostgreSQL reales que prueben RLS/FORCE, privilegios, FKs tenant-aware, checks,
   triggers inmediatos y guardianes diferidos con dos organizaciones y con SQL directo.
2. Pruebas de estados 5.2, gates de fases, desviaciones, incidencias, cambios, cierre,
   reprogramación, cancelación, idempotencia, revisiones y carreras concurrentes.
3. Pruebas negativas que fabriquen o desalineen `ScheduleEvent.new_snapshot`, Reservation,
   ScheduleAllocation, `source_event`/`source_revision`, ventana, Requirement, Assignment y
   CapacityAllocation.
4. Pruebas de puertos públicos y análisis AST que impidan importaciones privadas cruzadas.
5. Cutover reproducible desde P12 final sin historia sintética y verificación del rol
   `claridez_app` después de `migrate` y `db:prepare`.

## Alternativas consideradas

### Ampliar PreparationItem para ejecución y postevento

Rechazada. Haría imposible alcanzar `ready` cuando existan obligaciones que solo pueden cumplirse
durante o después de la ejecución y alteraría el significado histórico de 5.2.

### Añadir closing/closed a EventPreparation

Rechazada. Mezclaría `execution_completed` con conciliación postevento y rompería el hecho que
consume Finance.

### Confiar en DTO o ScheduleEvent.new_snapshot para ventanas

Rechazada. No protege SQL directo ni prueba la concordancia estructural con reserva y asignación de
agenda.

### Copiar la procedencia temporal a cada entidad Resources

Rechazada. Discriminadores independientes podrían divergir. `ResourceRequirement` es el portador
único y Assignment/CapacityAllocation heredan su rama.

### Crear agenda, inventario, archivos o turnos dentro de Operations

Rechazada. Duplicaría autoridades ya cerradas y ampliaría P13 fuera del Blueprint.

## Consecuencias

### Positivas

- P13 amplía la operación sin romper el flujo 5.2 ni el reconocimiento financiero.
- Las plantillas son reutilizables, pero cada evento conserva una verdad histórica inmutable.
- Operations puede expresar ventanas específicas y Resources puede reservar capacidad con una
  procedencia verificable ante SQL directo.
- El cierre distingue ejecución terminada, faltante histórico y custodia todavía pendiente.

### Costes y restricciones

- La implementación requerirá guardianes diferidos intermodulares, FKs compuestas y pruebas de
  concurrencia exigentes.
- Las desviaciones y cambios no podrán resolverse mediante edición CRUD; requieren ledger,
  autorización e idempotencia.
- Una necesidad fuera de la ocupación autorizada exige coordinar primero un cambio de Scheduling.

## Evidencia

- `docs/product/PRODUCT_BLUEPRINT.md`
- `docs/product/PRODUCT_DELIVERY_ROADMAP.md`
- `docs/product/ITERATION_5_2_OPERATIONS_SPECIFICATION.md`
- `docs/product/P8_SCHEDULING_AND_ADVANCED_RESERVATIONS_SPECIFICATION.md`
- `docs/product/P13_ADVANCED_OPERATIONS_SPECIFICATION.md`
- `docs/adr/0013-commercial-operations-coordination-and-integrity.md`
- `docs/adr/0016-scheduling-ownership-and-temporal-integrity.md`
- `docs/adr/0017-contractual-domain-and-documentary-evidence.md`
- `docs/adr/0018-file-platform-and-document-processing.md`
- `docs/adr/0020-finance-authority-recognition-and-operational-close-integrity.md`
- `docs/adr/0021-resources-supply-inventory-and-financial-provenance-integrity.md`
- Código vigente de `claridez.operations`, `claridez.scheduling`, `claridez.resources` y sus puertos
  públicos, verificado antes de aceptar este ADR.
