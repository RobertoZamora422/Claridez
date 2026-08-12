# P8 — Agenda y reservas avanzadas

- **Estado:** Aprobada
- **Fecha de propuesta:** 2026-08-06
- **Módulo propietario:** `claridez.scheduling`
- **ADR relacionado:** ADR 0016, en estado `Aceptado`
- **Precedentes:** Iteraciones 5.1 y 5.2, P6 y P7 cerradas
- **Naturaleza:** contrato funcional y técnico previo a implementación

## 0. Estado documental

Esta especificación concreta y autoriza P8. Su aprobación no declara todavía creados modelos,
migraciones, endpoints, pruebas ni interfaz, y tampoco declara ejecutado un cutover en ningún
entorno. Esos resultados solo podrán registrarse después de observar su implementación y
validación.

Los contratos aprobados de 5.1 y 5.2 permanecen vigentes salvo las ampliaciones expresas de este
documento. En particular:

- `EventRequest` y la cotización aceptada siguen bajo `claridez.commercial`;
- la confirmación sigue registrando evidencia externa, no procesa pagos;
- `reservation:cancel` sigue siendo la única autoridad de cancelación de la reserva;
- una preparación `in_progress` o `completed` no se puede cancelar ni reprogramar;
- una cotización aceptada no se edita, reemite ni recalcula por una reprogramación con términos
  comerciales sin cambios;
- el catálogo vigente nunca reemplaza snapshots históricos.

## 1. Resultado funcional y límites

P8 incorpora:

- disponibilidad por sede y espacio con intervalos ocupados que incluyen montaje, desmontaje y
  buffers;
- bloqueos internos parciales por espacios o completos por sede;
- agenda diaria, semanal y mensual;
- holds temporales con expiración determinista;
- confirmación segura frente a cambios de disponibilidad;
- reprogramación append-only mediante reserva sucesora;
- cancelación con liberación temporal y consecuencias operativas;
- historia única de agenda;
- proyección de revisión de tareas CRM;
- exportación básica de calendario en iCalendar.

P8 no incorpora calendario personal genérico, capacidad fraccional dentro de un espacio, inventario
detallado, cambios comerciales dentro de una reprogramación, pagos, sincronización bidireccional con
proveedores ni infraestructura asíncrona.

## 2. Propiedad modular y contratos públicos

| Módulo | Autoridad en P8 | Relación permitida |
|---|---|---|
| `claridez.scheduling` | Reserva, política temporal, bloqueo, asignación, disponibilidad, reprogramación, cancelación de reserva e historia de agenda. | Expone comandos y proyecciones inmutables por `scheduling.public`. |
| `claridez.commercial` | `EventRequest`, cotización, versiones, snapshots, aceptación y estados de oportunidad. | Entrega evidencia comercial por `commercial.public` y participa en coordinadores sin importar ORM de scheduling. |
| `claridez.operations` | `EventPreparation`, ítems, responsables y transiciones operativas. | Consume una proyección de reserva y coordina confirmación, cancelación y reprogramación. |
| `claridez.catalog` | Catálogo y revisiones vigentes. | Solo alimenta nuevas cotizaciones; no reconstruye reservas ni preparaciones históricas. |
| `claridez.crm` | Interacciones, tareas y su historia. | Compone la última novedad de agenda desde `scheduling.public`, sin importar modelos ORM. |
| `claridez.organizations` | Organización, membresía, sede, espacio, zona horaria y autorización. | Scheduling referencia identificadores tenant-aware y valida configuración y membresía dentro del scope autorizado. |

`Reservation` pasa al estado de aplicación `scheduling.Reservation`, pero mantiene inicialmente la
tabla `commercial_reservation`. La migración no copia filas ni cambia UUID. Las FK actuales se
conservan físicamente y cambian de destino en el estado de Django. La relación
`quotation_version_id` pasa de uno-a-uno a muchos-a-uno para que las reservas de una misma cadena
apunten a la misma versión aceptada.

Los imports entre módulos se limitan a tipos y funciones de `*.public`. La capa coordinadora puede
invocar varios puertos dentro de un único `authorized_tenant_scope` y una única transacción, pero no
se convierte en propietaria de sus datos.

## 3. Modelo funcional

### 3.1 Entidades y autoridad de campos

| Entidad | Campos autoritativos principales | Regla |
|---|---|---|
| `SpaceSchedulePolicy` | organización, espacio, minutos de montaje, desmontaje, buffer previo y posterior, revisión | Una fila por espacio; defaults para compromisos nuevos. |
| `Reservation` | `EventRequest`, cotización aceptada, raíz, predecesora, fuente de confirmación, espacio, intervalo del evento, zona capturada, duraciones capturadas, estado, plazo del hold y revisión | Entidad de dominio de un compromiso comercial temporal. |
| `ScheduleBlock` | organización, alcance, razón, intervalo local convertido, zona capturada, estado, actor y revisión | Entidad de dominio de indisponibilidad interna. |
| `ScheduleBlockTarget` | bloqueo y espacio objetivo | Conjunto inmutable de espacios afectados; no se borra al liberar. |
| `ScheduleAllocation` | origen exclusivo, organización, espacio, intervalo ocupado, revisión de origen, evento fuente e `is_blocking` | Proyección temporal actual, no fuente editable. |
| `ScheduleEvent` | tipo, fuente, actor, razón, revisiones, entidades afectadas, snapshots anterior/nuevo, idempotencia y tiempos | Única evidencia append-only de agenda. |

Las sedes y espacios siguen siendo de organizations. Una política ausente equivale a cero minutos
en los cuatro componentes hasta que se cree explícitamente. Los valores son enteros no negativos;
el intervalo ocupado final debe continuar siendo finito y válido.

### 3.2 Reserva y evidencia comercial

Se conservan los campos vigentes de `Reservation`. P8 añade como mínimo:

- `root_reservation_id` no nulo;
- `predecessor_id` nulo solo en la raíz;
- `confirmation_source_reservation_id` nulo mientras nunca existió confirmación;
- `setup_minutes`, `teardown_minutes`, `buffer_before_minutes` y
  `buffer_after_minutes` como snapshots;
- `revision` positiva para control optimista;
- el estado `rescheduled`.

La raíz se referencia a sí misma. Una sucesora usa la misma organización, `EventRequest`,
`QuotationVersion` y raíz. En una cadena nunca confirmada,
`confirmation_source_reservation_id` permanece nulo. Al confirmar la reserva vigente, esa reserva
se convierte en fuente y conserva los campos vigentes de evidencia de 5.1. Las sucesoras confirmadas
apuntan a esa misma fuente y no duplican la evidencia; la representación pública resuelve los
campos de confirmación desde la fuente.

La fuente, su clase de confirmación, monto reconocido, referencia, waiver, actores y fechas son
inmutables. Una sucesora no puede apuntar a una fuente de otra raíz, tenant, solicitud o cotización.
Una `QuotationVersion` puede originar una sola raíz, aunque sea referenciada por todas sus
sucesoras.

La raíz conserva la coherencia exacta de P6 entre cotización aceptada, espacio, intervalo y zona.
Una sucesora puede diferir únicamente en sede, espacio, intervalo, zona y snapshots temporales,
siempre que `reservation_rescheduled` pruebe el cambio. Invitados, necesidad, líneas, precio,
vigencia, aceptación y demás evidencia comercial no se alteran. El guardián de snapshot existente
se amplía con esta excepción explícita; no se elimina.

Los campos de fecha, espacio y necesidad de `EventRequest` continúan describiendo la solicitud
comercial que originó la cotización; una reprogramación no los reescribe. Mientras la sucesora sea
provisional, `EventRequest.status` permanece `accepted`; si es confirmada, permanece `confirmed`.
La agenda vigente se obtiene de la reserva actual de scheduling. `EventRequestHistory` no recibe
una revisión ficticia por reprogramación.

### 3.3 Bloqueos

Un bloqueo contiene razón obligatoria, intervalo, zona capturada, actor creador, estado y alcance:

- `spaces`: uno o más espacios explícitos de una misma sede; representa cierre parcial;
- `venue`: todos los espacios activos de la sede durante el intervalo; representa cierre completo.

No existe porcentaje de capacidad. Un bloqueo de sede materializa un target y una asignación por
cada espacio activo. Crear o reactivar un espacio mientras exista un bloqueo de sede vigente exige
al puerto de organizations materializar la asignación correspondiente dentro de la misma
transacción; si hay una incoherencia, la activación falla. Los targets no se editan: para cambiar el
alcance se libera el bloqueo y se crea otro.

Estados de bloqueo:

`active → released | cancelled`

- `released` significa liberación deliberada de un bloqueo que ya estuvo vigente;
- `cancelled` significa anulación por error antes de que su intervalo empezara;
- ambos son terminales, no bloqueantes y exigen razón;
- repetir la misma acción devuelve el estado actual sin cambiar actor, fecha o razón;
- intentar `released ↔ cancelled` devuelve `invalid_transition`.

### 3.4 Asignación temporal unificada

Cada asignación pertenece a exactamente uno de estos orígenes:

- una reserva; o
- un `ScheduleBlockTarget`.

Un `CHECK` exige exclusividad entre ambas FK. FK compuestas garantizan que origen, organización y
espacio coincidan. La asignación de reserva toma su intervalo y revisión desde `Reservation`; la de
bloqueo, desde `ScheduleBlock` y su target. Ningún serializer ni endpoint acepta campos de
`ScheduleAllocation`.

La equivalencia al commit es:

| Origen | Estado de dominio | Asignación requerida |
|---|---|---|
| Reserva | `provisional` antes o en su plazo | Una fila, `is_blocking=true`, intervalo ocupado exacto. |
| Reserva | `confirmed` | Una fila, `is_blocking=true`, intervalo ocupado exacto. |
| Reserva | `expired`, `cancelled` o `rescheduled` | Una fila histórica, `is_blocking=false`, sin cambiar su snapshot. |
| Bloqueo | `active` | Una fila bloqueante por target, intervalo exacto. |
| Bloqueo | `released` o `cancelled` | Las mismas filas, `is_blocking=false`. |

El guardián diferido compara organización, origen, espacio, intervalo, revisión y último
`ScheduleEvent`. Una divergencia falla con SQLSTATE `23514`. La proyección nunca se repara
silenciosamente durante tráfico normal.

`claridez_app` tendrá `SELECT`, `INSERT` y `UPDATE` sobre la proyección solo para permitir que los
servicios materialicen efectos. No tendrá `DELETE` ni `TRUNCATE`. Los triggers impedirán cambiar
identidad de origen, tenant o snapshot histórico y el guardián rechazará una actualización aislada.
`claridez_migrator` podrá construir y verificar el backfill durante el cutover. No existe escritura
HTTP directa de la proyección.

## 4. Tiempo, intervalos y zona horaria

### 4.1 Forma canónica

El intervalo del evento y el intervalo ocupado son `tstzrange` finitos, no vacíos y `[inicio, fin)`.
No se aceptan límites nulos, infinitos, abiertos ni `inicio >= fin`. Dos ocupaciones donde una
termina exactamente cuando otra empieza son compatibles.

La ocupación de una reserva es:

`[event_start - setup - buffer_before, event_end + teardown + buffer_after)`

Montaje, desmontaje y buffers son cuatro datos distintos. Se capturan desde la política del espacio
al crear el hold o la sucesora; un cambio posterior de política no altera reservas existentes. Un
bloqueo usa su propio intervalo como intervalo ocupado y no añade buffers implícitos.

Un evento puede cruzar medianoche y continúa siendo una sola reserva. Las vistas por día podrán
representarlo en varios segmentos visuales, sin dividir la entidad ni su historia.

### 4.2 Conversión de hora local

Las nuevas mutaciones P8 de disponibilidad candidata, bloqueo y reprogramación reciben
`starts_at_local` y `ends_at_local` sin offset, más `timezone` IANA. El backend vuelve a leer
`OrganizationSettings.timezone` dentro del scope; la zona enviada debe coincidir o responde
`organization_timezone_changed`. La zona empleada se captura en la entidad y en el evento
canónico. La creación de solicitud de 5.1 conserva su payload vigente de instantes aware y zona; P8
no lo sustituye silenciosamente. Al aceptar, scheduling usa los instantes y la zona del snapshot de
la cotización.

Para cada hora local el backend:

1. evalúa `fold=0` y `fold=1`;
2. convierte cada candidata a UTC y realiza round-trip a la zona;
3. si ninguna candidata vuelve al mismo valor local, rechaza `nonexistent_local_time`;
4. si dos instantes UTC distintos vuelven al mismo valor, rechaza `ambiguous_local_time`;
5. si existe un único instante, lo usa.

No se adelanta una hora inexistente ni se elige una ocurrencia ambigua. Esos errores son `400` de
dominio y nombran el campo afectado sin exponer internals.

### 4.3 Límites de calendario

`anchor_date` es una fecha en la zona vigente de la organización:

- día: desde 00:00 de `anchor_date` hasta 00:00 del día siguiente;
- semana: lunes ISO 00:00 hasta el lunes siguiente;
- mes: primer día 00:00 hasta el primer día del mes siguiente.

Cada límite local se convierte por separado a instante y la consulta usa solapamiento `&&` con el
intervalo `[inicio, fin)`. Un límite local ambiguo o inexistente produce
`invalid_calendar_boundary`; no se corrige. Día, semana y mes siempre significan una sola unidad
calendárica, no 24 horas, 7×24 horas ni una duración fija.

Si la zona organizacional cambia, los instantes y la zona capturada de reservas, bloqueos e historia
no cambian. El grid nuevo usa la zona vigente para sus límites y posición visual, mientras cada
entrada devuelve `captured_timezone` y sus valores locales originales. El detalle histórico muestra
ambas representaciones cuando difieren.

## 5. Máquinas de estado y transiciones

### 5.1 Reserva

`provisional → confirmed | expired | cancelled | rescheduled`

`confirmed → cancelled | rescheduled`

`expired`, `cancelled` y `rescheduled` son terminales.

| Transición | Precondiciones | Efectos atómicos |
|---|---|---|
| creación → `provisional` | Cotización vigente aceptada, espacio disponible, hora válida. | Crea raíz, snapshot temporal, asignación bloqueante y `reservation_hold_created`; plazo 48 horas como en 5.1. |
| `provisional → confirmed` | `hold_expires_at > transaction_timestamp()`, asignación equivalente, evidencia válida de 5.1. | Conserva ocupación, registra fuente inmutable, actualiza oportunidad, crea preparación de 5.2 y `reservation_confirmed`. |
| `provisional → expired` | `hold_expires_at <= transaction_timestamp()`. | Libera asignación, actualiza oportunidad según 5.1 y registra `reservation_expired`. |
| `provisional → cancelled` | Razón no vacía y `reservation:cancel`. | Libera asignación y registra `reservation_cancelled`; no crea preparación. |
| `confirmed → cancelled` | Preparación `preparing` o `ready` y razón no vacía. | Cancela reserva y preparación, libera asignación y registra las historias propias de cada módulo. |
| `provisional → rescheduled` | No vencida, revisión vigente, nuevo espacio disponible, términos sin cambios. | Crea sucesora provisional con el mismo vencimiento, libera la anterior y registra un evento de reprogramación. |
| `confirmed → rescheduled` | Preparación `preparing` o `ready`, revisión vigente, nuevo espacio disponible, términos sin cambios. | Crea sucesora confirmada, sustituye preparación, libera la anterior y registra un evento de reprogramación. |

Una confirmación repetida de la reserva vigente conserva la idempotencia de 5.1. Confirmar una
predecesora `rescheduled` o una provisional vencida falla. Cancelar una ya cancelada devuelve la
evidencia original; una razón nueva no reemplaza la primera.

### 5.2 Preparación operativa

P8 añade:

`preparing | ready → rescheduled`

`rescheduled` es terminal, al igual que `completed` y `cancelled`. La transición usa causa
`schedule_reschedule`, actor de la reprogramación, fecha y revisión. Los guardianes internos de
operations y el guardián transversal exigirán:

- reserva predecesora `rescheduled`;
- preparación anterior `rescheduled`;
- `rescheduled_to_reservation_id` igual a la única sucesora;
- nueva preparación exactamente una para la sucesora confirmada;
- baseline nueva completa y transición `initialized`;
- ausencia de preparación para sucesora provisional.

`in_progress` y `completed` rechazan reprogramación con `operation_already_started` y
`operation_already_completed`. `cancelled` y `rescheduled` devuelven `invalid_transition`.

### 5.3 Reprogramación completa

El comando exige:

- `revision` de la reserva vigente;
- `idempotency_key` UUID;
- nueva hora local, zona y `space_id`;
- razón obligatoria;
- `commercial_terms_unchanged=true`;
- lista opcional de `carry_free_item_ids`.

El servicio valida que el espacio pertenezca a una sede activa del tenant, convierte el tiempo,
captura la política actual y comprueba la ocupación. Luego, dentro de una transacción:

1. toma locks de los espacios anterior y nuevo en orden total;
2. materializa expiraciones vencidas en ambos espacios;
3. bloquea raíz y reserva vigente, y valida revisión e idempotencia;
4. si está confirmada, bloquea preparación e ítems en el orden aprobado por ADR 0013;
5. crea la sucesora con la misma raíz, `EventRequest` y `QuotationVersion`;
6. materializa su asignación, deja no bloqueante la anterior y marca la predecesora
   `rescheduled`;
7. en una confirmada, cierra la preparación anterior, crea la nueva preparación y sus ítems;
8. inserta un único `reservation_rescheduled` que enlaza snapshots anterior y nuevo;
9. valida guardianes y materializa la respuesta antes de salir del tenant scope.

No existe intervalo observable sin reserva vigente porque ninguna escritura es visible antes del
commit. Cualquier fallo, incluida una exclusión GiST, revierte todos los pasos.

Una reprogramación provisional conserva exactamente `hold_expires_at`; no extiende 48 horas. Una
confirmada conserva `confirmation_source_reservation_id`. Si la disponibilidad cambió antes del
lock, el comando devuelve `availability_conflict` y la predecesora permanece vigente.

Una clave idempotente repetida con el mismo hash devuelve la sucesora existente sin nueva historia.
La misma clave con payload distinto devuelve `idempotency_conflict`. Una revisión obsoleta devuelve
`stale_revision` aunque el destino todavía esté libre. Dos comandos distintos solo pueden producir
una sucesora; el perdedor recibe `stale_revision` o `already_rescheduled`.

### 5.4 Reconstrucción operativa

La nueva preparación se construye desde `QuotationVersion` aceptada originalmente y sus snapshots,
nunca desde revisiones vigentes de catálogo. Usa el nuevo intervalo y zona de la sucesora para
fechas derivadas. Se crea una baseline nueva con las siete claves de 5.2 y una nueva transición
`initialized`.

No se copian:

- estado, revisión ni notas de estado de la preparación anterior;
- `ready_at`, `ready_by_membership`, `started_at`, `completed_at` ni sus actores;
- resoluciones, `resolved_at`, `resolved_by_membership` o estados completados;
- transiciones anteriores;
- `operational_notes`, porque pueden describir el horario sustituido;
- vencimientos de ítems libres, porque su semántica frente a la nueva fecha no es inferible.

Un **ítem libre** es exactamente un `PreparationItem` cuyo `baseline_key IS NULL` y que fue creado
por un usuario, no uno de los siete ítems base. Solo los IDs incluidos expresamente se trasladan.
Cada copia:

- conserva `title`, `section`, posición relativa entre los ítems trasladados, `is_required` y
  `notes`;
- recibe nuevo UUID, nuevo `client_request_id`, `status=pending`, `revision=1`,
  `due_on=NULL`, `status_note` vacío y evidencia de resolución nula;
- guarda `carried_from_item_id` hacia el ítem anterior; esa FK es tenant-aware y única por
  preparación nueva;
- conserva `responsible_membership_id` solo si la membresía está activa, pertenece a la
  organización y posee `operation:manage` en ese instante; de lo contrario queda nula y la
  respuesta incluye `responsible_was_cleared=true`.

La preparación anterior guarda `rescheduled_to_reservation_id`. La sucesora permite navegar de
forma pública a la preparación nueva sin reescribir la anterior.

### 5.5 Cancelación

La razón continúa siendo obligatoria. Se permite:

- `provisional → cancelled` sin efecto operativo;
- `confirmed → cancelled` solo con preparación `preparing` o `ready`.

Se rechaza:

- `in_progress` con `operation_already_started`;
- `completed` con `operation_already_completed`;
- reservas `expired` o `rescheduled` con `invalid_transition`.

La cancelación libera la asignación, conserva evidencia comercial y agrega
`reservation_cancelled`. La preparación usa su transición `commercial_cancellation` de 5.2. No se
reactiva una cancelada. El replay devuelve actor, fecha y razón originales sin nuevo evento. La
reserva actual, asignación, historia comercial aplicable, historia scheduling y efecto operativo se
confirman o revierten juntos.

## 6. Invariantes de cadena e historia

### 6.1 Constraints e índices

La implementación deberá materializar al menos:

| Defensa | Invariante |
|---|---|
| FK `(organization_id, root_reservation_id)` → reserva | La raíz existe en el mismo tenant. |
| FK `(organization_id, predecessor_id)` → reserva | El predecesor existe en el mismo tenant. |
| `CHECK` raíz/predecesor | `predecessor IS NULL ⇔ root=id`; una sucesora no se apunta a sí misma. |
| `UNIQUE (organization_id, predecessor_id) WHERE predecessor_id IS NOT NULL` | Como máximo una sucesora directa; no hay bifurcación. |
| `UNIQUE (organization_id, quotation_version_id) WHERE predecessor_id IS NULL` | Una cotización aceptada origina una sola raíz; sus sucesoras reutilizan esa evidencia. |
| `UNIQUE (organization_id, root_reservation_id) WHERE status IN (provisional, confirmed)` | Como máximo una reserva vigente por raíz. |
| `UNIQUE (organization_id, event_request_id) WHERE status IN (provisional, confirmed)` | Como máximo una reserva vigente por oportunidad, incluso entre raíces históricas. |
| FK a `QuotationVersion` y guardianes | Toda la cadena comparte solicitud y evidencia comercial. |
| Índice `(organization_id, root_reservation_id, created_at, id)` | Recorrido estable de cadena e historia. |
| Índice `(organization_id, event_request_id, status)` | Resolución de agenda y proyección CRM. |
| Unicidad de evento por comando/idempotencia | Un reintento no crea una segunda sucesora ni una segunda transición. |

Los estados del índice parcial son persistidos; un provisional vencido se materializa como
`expired` bajo lock antes de competir. No se usa el reloj dentro del predicado.

### 6.2 Guardián recursivo y guardián de commit

Un constraint trigger `DEFERRABLE INITIALLY DEFERRED` recorre mediante CTE la cadena afectada y
comprueba:

- una sola raíz autocontenida;
- ningún ciclo, bifurcación, salto de raíz ni predecesor ajeno;
- misma organización, `EventRequest` y `QuotationVersion`;
- misma fuente de confirmación o ausencia coherente;
- una sola reserva vigente;
- revisiones monotónicas;
- predecesora `rescheduled` con una única sucesora;
- asignaciones y evento canónico del mismo comando;
- preparación anterior/nueva coherente cuando existió confirmación.

El trigger es invoker, fija `search_path`, no usa `SECURITY DEFINER`, revoca ejecución a `PUBLIC` y
aplica el patrón RLS aprobado en ADR 0013. `QuerySet.update`, `bulk_update`, `bulk_create` y SQL
directo que no construyan todo el estado válido fallan al commit. No se considera API soportada una
transacción técnica que reproduzca manualmente el agregado.

### 6.3 Autoridad append-only

`ScheduleEvent` es la única autoridad de scheduling para:

- `reservation_hold_created`;
- `reservation_confirmed`;
- `reservation_expired`;
- `reservation_rescheduled`;
- `reservation_cancelled`;
- `block_created`;
- `block_released`;
- `block_cancelled`;
- `cutover_snapshot`.

Un evento normal registra UUID, organización, tipo, origen, actor, razón, `EventRequest`, raíz,
reserva/bloqueo, predecesora y sucesora cuando apliquen, revisión resultante, snapshots anterior y
nuevo, `idempotency_key`, hash canónico de payload, `occurred_at` y `recorded_at` generados por
PostgreSQL. El actor puede ser nulo solo en expiración determinista y cutover; `source` distingue
`user`, `database_expiration` y `cutover`.

La reprogramación produce un solo evento que prueba tanto el cierre de la predecesora como la
creación de la sucesora. No se crea un segundo registro de reprogramación.

`ScheduleEvent` admite `SELECT` e `INSERT` para la aplicación, pero no `UPDATE`, `DELETE` ni
`TRUNCATE`. Triggers de inmutabilidad protegen incluso al propietario ordinario de aplicación.
`EventRequestHistory` continúa describiendo cambios de oportunidad; `PreparationTransition`,
cambios operativos. Si una cancelación cambia las tres entidades, cada historia prueba únicamente
su agregado y enlaza el mismo comando, sin reclamar autoridad sobre las otras transiciones.

## 7. Expiración y defensa temporal PostgreSQL

### 7.1 Protocolo

Antes de consultar o escribir competencia en un espacio, la operación PostgreSQL:

1. toma `pg_advisory_xact_lock` para la clave estable organización/espacio;
2. fija `effective_now = transaction_timestamp()` una sola vez;
3. bloquea provisionales de ese espacio con `hold_expires_at <= effective_now` en orden por UUID;
4. para cada una, valida que siga provisional, la cambia a `expired`, hace no bloqueante su
   asignación, inserta `reservation_expired` con idempotencia derivada de la reserva y coordina el
   estado comercial de 5.1;
5. solo entonces prueba o inserta la ocupación candidata.

La función es reentrante dentro de la misma transacción y se invoca desde servicios y desde triggers
`BEFORE` de escrituras que puedan crear competencia en `Reservation`, `ScheduleBlockTarget` o
`ScheduleAllocation`. Un SQL directo sobre una ruta competidora ejecuta el mismo saneamiento. Si
inserta solo una entidad sin su asignación o evento, el guardián diferido revierte la transacción.

Una asignación vencida puede permanecer visible hasta la siguiente lectura o escritura relevante,
pero no puede impedir indefinidamente una nueva ocupación: la disponibilidad y toda escritura
competidora la materializan como no bloqueante bajo el lock antes de evaluar conflicto.

### 7.2 Exclusión única

La única exclusión temporal usa GiST:

`organization_id WITH =, space_id WITH =, occupied_interval WITH &&`

con predicado inmutable `WHERE is_blocking`. Sustituye
`commercial_reservation_no_overlap` durante el cutover. Incluye reservas y bloqueos porque ambos se
proyectan en la misma tabla.

La exclusión es la defensa final, no el mecanismo de expiración. Los advisory locks permiten
errores de dominio previsibles y ordenan efectos; si una ruta los omite, GiST aún impide el
solapamiento.

### 7.3 Confirmación en el límite

Confirmación y expiración toman primero el lock del espacio y después la fila de reserva. Ambas usan
el mismo `transaction_timestamp()`:

- si `hold_expires_at > effective_now`, la confirmación puede continuar;
- si `hold_expires_at <= effective_now`, se materializa `expired` y confirmar responde
  `hold_expired`;
- en igualdad exacta gana expiración;
- la transacción perdedora relee el estado después del lock y no genera un segundo evento.

## 8. Locks, RLS e integridad

### 8.1 Orden total

El orden obligatorio de locks es:

1. advisory locks `(organization_id, space_id)` ordenados por UUID de espacio;
2. raíces y reservas ordenadas por UUID;
3. bloqueos y targets ordenados por UUID;
4. `EventPreparation`;
5. `PreparationItem` ordenados por posición e ID;
6. asignaciones afectadas ordenadas por espacio e ID.

El orden extiende, sin invertir, `Reservation → EventPreparation → PreparationItem` de ADR 0013.
Una reprogramación entre A y B y otra entre B y A toman A/B en el mismo orden. Crear un bloqueo de
sede toma todos los espacios activos ordenados.

### 8.2 Tenant y privilegios

`SpaceSchedulePolicy`, `Reservation`, `ScheduleBlock`, `ScheduleBlockTarget`,
`ScheduleAllocation` y `ScheduleEvent` son privadas. Todas incluyen organización explícita, FK
compuestas cuando cruzan tablas y políticas `ENABLE RLS` + `FORCE RLS`. IDs de organización, sede,
espacio, reserva, bloqueo o membresía del cliente nunca sustituyen la organización autorizada.

El rol de aplicación:

- no tiene `DELETE` sobre entidades scheduling;
- no actualiza ni elimina `ScheduleEvent`;
- no elimina targets ni asignaciones;
- solo muta dominio/proyección dentro de `authorized_tenant_scope`;
- no puede desactivar triggers, constraints o RLS.

Una solicitud sin sesión, sin CSRF en métodos no seguros, con organización inactiva, membresía
inactiva, rol desconocido, capacidad ausente o referencia cruzada se deniega antes de materializar
una respuesta privada. El guardián sigue siendo defensa, no autorización.

## 9. Proyección CRM

`scheduling.public` expondrá una estructura inmutable, no un QuerySet ni una instancia ORM, con:

- `organization_id` y `event_request_id`;
- tipo, UUID y `occurred_at` del último evento de reserva aplicable;
- raíz y reserva vigente;
- snapshot anterior/nuevo mínimo;
- condición de cutover.

Para una `FollowUpTask`:

`requires_schedule_review = task.status == open AND last_applicable_schedule_event.occurred_at >=
last_task_history.created_at`

El último cambio de tarea es la fila de mayor `revision` en `FollowUpTaskHistory`. Son aplicables
`reservation_hold_created`, `reservation_confirmed`, `reservation_expired`,
`reservation_rescheduled` y `reservation_cancelled`. `cutover_snapshot` y eventos de bloqueo no
activan revisión. Ante igualdad temporal se requiere revisión de forma conservadora y determinista.
Sin tarea vinculada, sin evento aplicable o con tarea terminal, el valor es falso.

No se guarda un booleano en CRM. No se actualizan `due_at`, `next_contact_at`, estado, responsable,
revisión ni historia. Cuando un usuario autorizado modifica la tarea, su nueva revisión se convierte
en el punto de comparación y la condición se recalcula.

## 10. Capacidades y autorización

### 10.1 Matriz final de P8

| Capacidad | `owner` | `administrator` | `commercial` | `operations` | `finance` |
|---|:---:|:---:|:---:|:---:|:---:|
| `availability:read` existente | Sí | Sí | Sí | Sí | Sí |
| `schedule:block` nueva | Sí | Sí | No | Sí | No |
| `reservation:reschedule` nueva | Sí | Sí | Sí | No | No |
| `schedule:export` nueva | Sí | Sí | Sí | Sí | No |
| `reservation:confirm` existente | Sí | Sí | Sí | No | Sí |
| `reservation:cancel` existente | Sí | Sí | No | No | No |
| `reservation:waive_deposit` existente | Sí | Sí | No | No | No |
| `venue:manage` existente | Sí | Sí | No | No | No |
| `operation:manage` existente | Sí | Sí | No | Sí | No |

No se altera el resto de matrices P6/P7. No hay jerarquía implícita.

### 10.2 Reglas conjuntivas

- leer calendario, disponibilidad, detalle de bloqueo e historia de agenda:
  `organization:access ∧ availability:read`;
- crear, liberar o cancelar bloqueo:
  `organization:access ∧ availability:read ∧ schedule:block`;
- cambiar política temporal de un espacio:
  `organization:access ∧ venue:manage ∧ schedule:block`;
- reprogramar:
  `organization:access ∧ sales:manage ∧ reservation:reschedule`;
- exportar:
  `organization:access ∧ availability:read ∧ schedule:export`;
- confirmar, cancelar o autorizar waiver: contratos existentes sin cambios;
- el efecto operativo automático de confirmar, cancelar o reprogramar no concede capacidades
  `operation:*` al actor.

En todos los casos se exige sesión Django autenticada, CSRF en métodos no seguros, organización
activa, contexto activo coherente y membresía activa. El backend vuelve a evaluar todas las
condiciones dentro de la transacción.

## 11. API REST preliminar

Todas las rutas empiezan por `/api/v1/organizations/{organization_id}/`. Los nombres nuevos son
preliminares hasta aceptar ADR 0016; sus contratos funcionales no lo son.

| Método y ruta preliminar | Capacidad | Entrada principal | Resultado |
|---|---|---|---|
| `GET scheduling/capabilities/` | `organization:access` | Sin cuerpo. | Capacidades efectivas P8; no entrega agenda. |
| `GET scheduling/calendar/` | `availability:read` | `view=day|week|month`, `anchor_date`, filtros opcionales `venue_id`, `space_id` y tipos. | Entradas que solapan el rango, con reserva/bloqueo/hold, estado, ocupación y zona. |
| `POST scheduling/availability/` | `availability:read` | Hora local, zona y uno o más `space_ids`. | Disponibilidad por espacio y conflictos mínimos. |
| `GET scheduling/spaces/{space_id}/policy/` | `availability:read` | Sin cuerpo. | Política y revisión. |
| `PATCH scheduling/spaces/{space_id}/policy/` | `venue:manage ∧ schedule:block` | `revision` y los cuatro minutos. | Política actualizada; no mueve reservas. |
| `GET scheduling/blocks/` | `availability:read` | Rango y filtros de sede/espacio/estado. | Bloqueos autorizados del tenant. |
| `POST scheduling/blocks/` | `schedule:block` | `idempotency_key`, alcance, hora local, zona y razón. | `201`; replay idéntico `200`. |
| `POST scheduling/blocks/{block_id}/release/` | `schedule:block` | `revision` y razón. | `200` idempotente con evidencia original. |
| `POST scheduling/blocks/{block_id}/cancel/` | `schedule:block` | `revision` y razón. | `200` idempotente si aún puede anularse. |
| `POST reservations/{reservation_id}/reschedule/` | `sales:manage ∧ reservation:reschedule` | Revisión, idempotencia, destino, hora local, razón, declaración comercial e ítems libres. | Sucesora y proyección coordinada. |
| `GET reservations/{reservation_id}/schedule-history/` | `availability:read` | Sin cuerpo; resuelve toda la raíz. | Historia canónica ordenada. |
| `GET scheduling/calendar.ics` | `schedule:export` | Rango máximo día/semana/mes y filtros. | iCalendar generado al vuelo, sin URL pública persistente. |

El `GET availability/` vigente de 5.1 se conserva y delega internamente en scheduling con su forma de
respuesta compatible. `POST reservations/{id}/confirm/` y
`POST reservations/{id}/cancel/` conservan payloads, capacidades y errores previos, añadiendo solo
la coordinación interna y conflictos de integridad que P8 hace posibles.

### 11.1 Respuestas y privacidad

Las entradas de calendario distinguen `reservation`, `hold` y `block`. Incluyen intervalo de evento,
intervalo ocupado, sede, espacio, estado, zona capturada y capacidades de acción. La identidad de
persona y datos comerciales solo aparecen si el actor posee además sus capacidades vigentes. Un
conflicto de disponibilidad nunca filtra persona, notas, precio ni evidencia de depósito.

El iCalendar contiene UID opaco, horario, zona, sede/espacio y estado mínimo. No contiene teléfono,
correo, notas, monto ni referencias financieras. Se descarga bajo sesión; no se crea feed público.

### 11.2 Errores

- `400 invalid_request`: forma, rango o campo inválido;
- `400 ambiguous_local_time` y `400 nonexistent_local_time`;
- `400 invalid_calendar_boundary`;
- `401 unauthenticated` y `403 forbidden`;
- `404 not_found` para referencias ausentes, ajenas o no visibles;
- `409 stale_revision`;
- `409 idempotency_conflict`;
- `409 availability_conflict`;
- `409 hold_expired`;
- `409 already_rescheduled`;
- `409 invalid_transition`;
- `409 operation_already_started` y `operation_already_completed`;
- `409 organization_timezone_changed`;
- `409 schedule_integrity_conflict` para una violación inesperada normalizada.

Un conflicto puede devolver tipo, espacio e intervalo ocupado del competidor solo bajo
`availability:read`. No expone el texto SQL ni detalles de otro tenant.

## 12. Experiencia web

La navegación Agenda será una vista conectada a comercial y operations, no un calendario genérico:

- selector día/semana/mes y navegación por fecha;
- filtros acumulables por sede, espacio y tipo de entrada;
- color y patrón redundantes, con texto/ícono, para confirmada, hold, bloqueo y terminal;
- intervalo del evento y ocupación ampliada visibles de forma diferenciada;
- panel de detalle con solicitud/cotización/preparación solo según capacidades;
- creación de bloqueo desde rango seleccionado o formulario accesible;
- reprogramación desde la reserva, con disponibilidad del destino y resumen de efectos;
- cancelación con razón obligatoria y advertencia operativa;
- conflicto que conserva los datos ingresados y ofrece volver a consultar;
- indicador derivado `Requiere revisión de agenda` en tareas CRM, sin botón de resolución ficticio;
- exportación solo si `schedule:export`.

En 1440×900 la semana muestra columnas sin perder la jerarquía; en 390×844 usa lista cronológica o
un día a la vez, filtros en panel y acciones apiladas. No existe scroll horizontal de página. Las
tablas secundarias se convierten en tarjetas.

Los controles son operables por teclado, tienen foco visible, nombres accesibles y objetivos
táctiles suficientes. El color no es la única señal. Modales retienen foco, restauran foco al cerrar
y anuncian conflictos mediante región viva. El zoom a 200 %, textos largos y zonas diferentes no
producen recorte ni desbordamiento.

## 13. Migración y cutover

### 13.1 Evolución de esquema y estado

La secuencia obligatoria es:

1. adquirir lock de mantenimiento y ejecutar preflight sin mutar datos;
2. crear tablas scheduling nuevas, políticas RLS y privilegios todavía sin tráfico;
3. adoptar `Reservation` con operaciones de estado de Django y
   `db_table=commercial_reservation`, sin copiar ni renombrar;
4. cambiar la relación de cotización a FK protegida, añadir cadena, revisión, snapshots de
   ocupación y estado `rescheduled`;
5. convertir cada reserva existente en raíz autocontenida y poner los cuatro minutos en cero;
6. añadir `rescheduled` y vínculos de procedencia a operations, sin cambiar filas existentes;
7. materializar expiraciones reales cuyo plazo ya venció bajo el protocolo P8;
8. insertar un `cutover_snapshot` por reserva observada y por cualquier dato de bloqueo importado,
   con `recorded_at` del cutover y `source=cutover`;
9. crear una asignación por reserva provisional no vencida o confirmada, y filas no bloqueantes para
   estados terminales;
10. verificar cardinalidad, tenant, intervalos, evidencia, preparaciones y ausencia de
    solapamientos;
11. instalar guardianes y triggers; crear la exclusión unificada y eliminar
    `commercial_reservation_no_overlap` dentro de la misma ventana;
12. aplicar `FORCE RLS`, comprobar privilegios mínimos, ejecutar smoke tests y liberar tráfico.

`cutover_snapshot` describe el estado observado, no afirma que ocurrieron creación, confirmación o
cancelación históricas si no existe evidencia. Usa fechas vigentes solo como snapshots atribuidos.
Una reserva histórica sin montaje, desmontaje o buffers recibe cero; no se infiere política.

### 13.2 Preflight y divergencias

El preflight aborta ante:

- reserva sin organización, solicitud, cotización aceptada o espacio coherente;
- intervalo no canónico o zona IANA inválida;
- cotización compartida por reservas que no puedan explicarse como una cadena;
- dos reservas vigentes para una solicitud;
- solapamiento de ocupaciones que la exclusión nueva rechazaría;
- reserva confirmada sin el agregado operativo exigido por 5.2;
- evidencia de confirmación o cancelación parcial;
- RLS, propietario o privilegios diferentes del contrato;
- cualquier proyección existente no reparable de forma determinista.

Durante la migración solo se reparan ausencias derivables de una autoridad existente: raíz propia,
ceros históricos, snapshot de cutover y asignación equivalente. Valores contradictorios, historia
ambigua o conflictos abortan con conteos e IDs técnicos; no se elige una versión silenciosamente.

### 13.3 Compatibilidad de migraciones

Se probarán con `MigrationExecutor` y PostgreSQL real:

- base vacía hasta HEAD;
- estado exacto posterior a P6 hasta HEAD;
- estado exacto posterior a P7 hasta HEAD;
- reversión inmediata del cutover antes de tráfico y reaplicación;
- migración con datos sintéticos en todos los estados 5.1/5.2;
- fallo atómico de cada preflight.

El rollback anterior a tráfico elimina primero guardianes/exclusión nueva, restaura la exclusión
vigente y revierte el estado Django sin perder filas. Una reversión después de crear bloqueos,
sucesoras, buffers no nulos o `rescheduled` no es representable por 5.1/P7 y debe abortar; en un
entorno destino se recuperará el backup/PITR ensayado en vez de inventar un down-migration.

### 13.4 Tres significados de cutover

- **Procedimiento documentado y ensayado:** scripts, consultas, locks, backup, rollback y criterios
  de go/no-go revisados.
- **Ejecución local desechable:** ensayo reproducible sobre PostgreSQL local con datos sintéticos;
  prueba el procedimiento, no un despliegue.
- **Ejecución futura en entorno destino:** requiere autorización, ventana, backup verificado,
  credenciales y evidencia de ese entorno.

P8 documental no afirma ninguno de los dos últimos. La implementación deberá registrar por separado
lo que realmente se ejecute.

## 14. Escenarios concurrentes obligatorios

Todos se prueban con dos conexiones PostgreSQL reales, barreras explícitas, timeouts acotados y
estado final observado:

1. **C01:** dos aceptaciones/holds solapados en el mismo espacio: uno confirma, otro recibe
   `availability_conflict`.
2. **C02:** hold contra creación de bloqueo solapado: un único ganador y ninguna fila huérfana.
3. **C03:** bloqueo contra confirmación de un hold ya existente: confirmación conserva ocupación o
   el bloqueo pierde; nunca coexisten.
4. **C04:** confirmación contra expiración antes, exactamente en y después del plazo: en igualdad
   gana expiración y hay un solo evento.
5. **C05:** asignación vencida dejada por SQL directo contra nuevo hold/bloqueo: el trigger la hace
   no bloqueante bajo el lock antes de evaluar GiST.
6. **C06:** dos reprogramaciones con la misma clave y payload: una sucesora y un evento; ambas
   respuestas convergen.
7. **C07:** misma clave con payload distinto: una gana y la otra recibe
   `idempotency_conflict`.
8. **C08:** dos claves distintas sobre la misma raíz hacia destinos distintos: una sola sucesora;
   la otra queda obsoleta.
9. **C09:** reprogramaciones A→B y B→A simultáneas: orden total, sin deadlock y sin solapamiento.
10. **C10:** reprogramación contra cancelación: un estado terminal coherente, nunca predecesora
    `rescheduled` sin sucesora.
11. **C11:** reprogramación confirmada contra `start` operativo: si start gana se rechaza; si
    reprogramar gana, start sobre la anterior se rechaza.
12. **C12:** liberación de bloqueo contra creación de hold: resultado serializable y un único evento
    de liberación.
13. **C13:** actualización de política contra creación/reprogramación: cada reserva captura una
    revisión completa anterior o posterior, nunca mezcla campos.
14. **C14:** bloqueo completo de sede contra alta/reactivación de espacio: se crea su target o la
    activación revierte.
15. **C15:** `bulk_update`/`QuerySet.update`/SQL directo intenta marcar `rescheduled` sin sucesora,
    evento o asignación: falla al commit y conserva todo.
16. **C16:** dos tenants usan los mismos instantes y referencias cruzadas: no se bloquean entre sí y
    RLS niega la referencia ajena.
17. **C17:** actualización o borrado concurrente de `ScheduleEvent`: privilegio/trigger lo impide y
    la historia no cambia.
18. **C18:** cancelación, expiración o reprogramación simultánea con lectura de calendario: la
    respuesta materializada corresponde enteramente a antes o después del commit, no a una mezcla.

Las pruebas también inspeccionan ausencia de deadlocks, número de eventos, cadena, estado comercial,
preparación, asignaciones y tenant GUC restaurado.

## 15. Pruebas y validación de cierre futuro

### 15.1 Backend

- servicios de política, disponibilidad, hold, expiración, bloqueo, confirmación, reprogramación,
  cancelación, historia y exportación;
- todas las transiciones válidas e inválidas, replays, razones, revisiones y hashes;
- snapshots de política, conversión local, horas ambiguas/inexistentes, medianoche y cambio de zona;
- reconstrucción operativa desde cotización, ítems libres y responsables inactivos;
- proyección CRM y comparación determinista sin mutar tareas;
- API completa, errores, privacidad y contratos compatibles 5.1/5.2;
- matriz de roles, reglas conjuntivas, sesión, CSRF y membresía inactiva;
- dos tenants, IDs cruzados, `ENABLE/FORCE RLS` y privilegios;
- SQL directo, `bulk_create`, `bulk_update` y `QuerySet.update`;
- inmutabilidad de historia y denegación de `DELETE`;
- escenarios C01–C18 con PostgreSQL real;
- migraciones desde cero, P6 y P7, rollback pretráfico y preflight fallido;
- regresión completa 5.1, 5.2, P6 y P7.

### 15.2 Contrato y frontend

- OpenAPI describe payloads, respuestas, errores y seguridad de todas las rutas;
- los endpoints vigentes no pierden campos ni cambian códigos sin contrato explícito;
- pruebas unitarias de rango, filtros, conflictos, capacidades y revisión CRM;
- integración de día/semana/mes, bloqueo, reprogramación, cancelación e iCalendar;
- teclado, foco, región viva, etiquetas, contraste, zoom 200 % y textos largos;
- validación visual a 1440×900 y 390×844 en día, semana, mes, modal, conflicto y detalle;
- comprobación explícita de ausencia de desbordamiento horizontal.

### 15.3 Puerta de finalización

P8 solo podrá declararse implementada cuando:

- ADR 0016 y esta especificación estén aprobados;
- modelo, API y web cumplan todo el alcance sin infraestructura asíncrona;
- exclusión única, cadena, expiración, RLS e historia resistan las rutas alternativas;
- migraciones y cutover estén documentados y ensayados sin afirmar despliegue no observado;
- suites oficiales pertinentes pasen con PostgreSQL real;
- Roadmap y Handoff se actualicen con evidencia observada, no antes.

## 16. Decisiones humanas pendientes

No queda una decisión funcional o arquitectónica abierta dentro de esta propuesta. Los nombres
físicos y rutas preliminares pueden ajustarse durante revisión sin cambiar sus autoridades o
invariantes.

La única decisión humana bloqueante es aprobar expresamente ADR 0016 y esta especificación. Más
adelante, ejecutar un cutover en un entorno destino requerirá una autorización operativa separada,
ventana y estrategia de recuperación verificadas.
