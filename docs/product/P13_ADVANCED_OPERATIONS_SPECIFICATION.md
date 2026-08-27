# P13 — Contrato funcional breve de operación avanzada

- **Estado:** Implementado y validado localmente el 25 de agosto de 2026
- **Fecha de aprobación:** 2026-08-25
- **Arquitectura:** ADR 0022
- **Implementación:** Completa en el checkout local; no presume despliegue ni cutover de destino

## 1. Propósito y límites

P13 amplía la preparación 5.2 para coordinar planes operativos versionados, montaje real,
ejecución, desmontaje, incidencias, cambios autorizados, necesidades temporales de recursos y
cierre postevento. La primera superficie se construye sobre autoridades existentes.

P13 no es un gestor genérico de proyectos o tareas, un segundo inventario, otra agenda, otro
repositorio documental ni un sistema de turnos o nómina. Tampoco duplica costos, margen o
rentabilidad P11.

## 2. Autoridades y puertos

- Operations posee plan/snapshot operacional, checklist de readiness P13, verificaciones de fase,
  responsables del evento, incidencias, cambios, ventanas-necesidad y cierre postevento.
- Commercial conserva solicitud, cotización y confirmación. Operations solo lo consume por
  `commercial.public`.
- Scheduling conserva raíz, reserva, espacio, intervalo del evento, minutos de montaje/desmontaje,
  buffers, ocupación, conflictos e historia. Su puerto debe exponer una proyección estructural
  suficiente para validar reserva, asignación, evento y revisiones.
- Resources conserva proveedor, recurso, disponibilidad, capacidad, requerimiento, asignación,
  custodia, movimiento y estados. Operations solo intercambia DTO inmutables por
  `resources.public`.
- Documents conserva archivos y evidencia privados. Operations solo guarda referencias
  tenant-aware autorizadas por su puerto.
- Organizations conserva membresías/sedes; People la persona; Catalog el tipo/oferta vendible;
  Finance los hechos monetarios y la rentabilidad.

Los puertos de Scheduling, Resources, Documents, Organizations y Catalog deberán ser estrechos y
suficientes antes de conectar P13. Una coordinación transaccional puede usar FKs físicas
tenant-aware, pero ningún consumidor importa modelos privados de otro módulo.

## 3. Ciclo de EventPreparation

La máquina de estados permanece:

`preparing -> ready -> in_progress -> completed`

con salidas vigentes a `cancelled` o `rescheduled` donde ADR 0013/0016 lo permiten.

- `ready` significa que el checklist de preparación está resuelto.
- `in_progress` significa que inició la ejecución.
- `completed` significa exclusivamente `execution_completed` y mantiene el disparador conceptual
  de reconocimiento de ADR 0020.
- El cierre postevento no es un estado de EventPreparation y no existe `closing`/`closed`.

Toda transición conserva revisión esperada, actor, tiempo, causa, idempotencia e historia. Los
guardianes 5.2 siguen siendo obligatorios.

## 4. Plantillas y snapshot

### 4.1 Versión organizacional

Una plantilla se identifica por organización y tipo de evento. Admite borrador, publicación y
retiro. La publicación produce una versión inmutable con:

- definiciones de readiness P13;
- verificaciones tipadas de `setup`, `execution`, `teardown` y `post_event`;
- roles operativos requeridos;
- necesidades de recursos y anclas temporales relativas.

Retirar una versión impide aplicarla a nuevos eventos; no altera snapshots existentes.

### 4.2 Fallback de sistema

Si no hay versión organizacional publicada se aplica `operations-p13-system-v1`, versión de
sistema explícita, identificable e inmutable. No añade requisitos organizacionales y mantiene el
flujo mínimo 5.2. No convierte la baseline 5.2 en una plantilla P13. La ausencia de plantilla
organizacional no bloquea por sí sola la confirmación comercial: el fallback queda seleccionado en
la creación atómica de la preparación aplicable.

### 4.3 Snapshot del evento

Cada preparación que entra al flujo P13 congela fuente `organization` o `system`, versión, hash,
definiciones, roles, necesidades y anclas. Un snapshot no se reconstruye consultando la plantilla
vigente. Una publicación posterior solo afecta eventos futuros.

## 5. Checklist de readiness

### 5.1 Procedencias

Cada `PreparationItem` declara exactamente una:

- `baseline_5_2`: una de las siete definiciones `operations-5.2-v1`;
- `manual`: ítem libre 5.2;
- `p13_template_readiness`: definición del snapshot P13.

Solo `manual` es trasladable en reprogramación. Los siete baseline conservan claves, contenido,
reglas y significado históricos de readiness; el etiquetado de procedencia no los transforma ni
cambia la edición controlada que 5.2 ya permite.

### 5.2 Definición y proyección de plantilla

En un ítem `p13_template_readiness` son inmutables organización, preparación, procedencia,
snapshot/definición, clave e identidad idempotente, ausencia de baseline/traslado, título, sección,
obligatoriedad, fecha relativa resuelta, rol requerido y orden relativo.

Durante `preparing` o `ready` se pueden actualizar responsable válido, estado, nota de estado,
notas operativas y resolución. Los ítems manuales conservan la edición 5.2.

Una desviación de un campo definido requiere:

1. propuesta con `operation:manage`, revisión esperada, antes/después y razón;
2. autorización con `operation_change:authorize`;
3. hecho append-only con proponente, autorizador, idempotencia, hash y revisiones;
4. actualización de la proyección efectiva sin editar la definición;
5. reapertura atómica a `preparing` si la nueva proyección invalida `ready`.

La misma membresía puede proponer y autorizar si posee ambas capabilities. PostgreSQL debe poder
reconstruir definición más desviaciones y rechazar cualquier proyección divergente, incluso por
bulk o SQL directo.

## 6. Verificaciones de fase

Una verificación tiene una fase cerrada, una definición de snapshot, obligatoriedad, rol requerido
y estado `pending`, `completed` o `not_applicable`. `not_applicable` exige razón y actor. No admite
subtareas, dependencias arbitrarias ni campos libres de gestión de proyectos.

| Fase         | Momento de cumplimiento | Gate                                                |
| ------------ | ----------------------- | --------------------------------------------------- |
| `setup`      | `preparing` o `ready`   | Todo obligatorio debe resolverse antes de iniciar   |
| `execution`  | `in_progress`           | Todo obligatorio debe resolverse antes de completar |
| `teardown`   | después de `completed`  | Todo obligatorio debe resolverse antes de cerrar    |
| `post_event` | después de `completed`  | Todo obligatorio debe resolverse antes de cerrar    |

Las verificaciones de fase nunca cuentan para el gate `ready`. Un hecho cumplido es inmutable; una
corrección se enlaza como hecho adicional. `setup` y `teardown` prueban trabajo real; no alteran los
minutos, buffers ni `occupied_interval` propiedad de Scheduling.

### 6.1 Hechos temporales observados

- `execution` usa únicamente `execution_started`/`execution_completed` y
  `EventPreparation.started_at/completed_at` de 5.2. No existe otra cronología de ejecución.
- `setup` y `teardown` registran inicio y finalización explícitos como hechos append-only con actor,
  instante observado, revisión esperada, idempotencia, procedencia y hash.
- Una corrección temporal enlaza el hecho exacto, declara valor efectivo y razón, y nunca reescribe
  el original.
- El inicio/finalización efectivo debe ser único y coherente con EventPreparation y la fase. No se
  admite finalizar antes de iniciar, duplicar un hecho consumado ni fabricar una secuencia mediante
  bulk o SQL directo.
- La duración de setup/teardown se calcula solo con esos hechos efectivos; la de execution solo con
  5.2. Nunca se usan el primer o último cumplimiento de verificaciones como sustituto temporal.
- Los hechos describen trabajo observado y no modifican minutos, buffers, intervalos ni ocupación
  de Scheduling.
- `post_event` no tiene duración de fase artificial. Las verificaciones mantienen exclusivamente
  `pending`, `completed` y `not_applicable`; no se añade `in_progress` ni una segunda máquina de
  EventPreparation.

## 7. Responsabilidades operativas

El coordinador existente de EventPreparation sigue siendo el responsable principal. El snapshot
puede definir roles por fase y el evento puede asignarlos a membresías activas de la misma
organización. Una asignación debe conservar rol, fase, responsable, revisión, vigencia e historia.

No se registran jornada, turno, disponibilidad personal, asistencia, remuneración ni contrato
laboral.

## 8. Incidencias

- Tipos: `safety`, `schedule_or_space`, `resource`, `supplier`, `service_quality`,
  `customer_scope`, `other_operational`.
- Severidades: `low`, `medium`, `high`, `critical`.
- Estados: `open`, `contained`, `resolved`.

La apertura fija evento, tipo, severidad inicial, instante, descripción, reportante, impacto no
vacío y responsable opcional. Contención, reasignación, cambio de impacto, cambio de seguimiento,
resolución y corrección son eventos append-only. Las transiciones ordinarias son
`open -> contained`, `open -> resolved` y `contained -> resolved`. Una recurrencia abre una
incidencia enlazada nueva; una corrección no sobrescribe la secuencia.

El seguimiento es un campo estrecho y explícito en la proyección y en cada hecho del ledger. Su
valor efectivo procede del último evento canónico y describe la acción posterior comprometida para
una incidencia contenida; `detail` conserva exclusivamente el relato del evento y nunca cuenta como
seguimiento. `follow_up_updated` cambia solo ese dato. Una corrección enlaza el hecho corregido y
publica una nueva proyección completa; constraints y guardianes impiden divergencia por ORM bulk o
SQL directo. Abrir o resolver no exige inventar seguimiento, pero una incidencia que permanezca
`contained low/medium` solo es compatible con el cierre si tiene responsable, impacto no vacío y
seguimiento no vacío. Una `contained high/critical` siempre bloquea y una `resolved` no hereda ese
gate.

La evidencia se enlaza exclusivamente con Documents y queda sujeta a sus permisos, estado y
retención.

## 9. Cambios autorizados

`operation:manage` propone y `operation_change:authorize` acepta o rechaza. Una propuesta declara
alcance tipado —readiness, verificación pendiente, responsabilidad, necesidad o ventana—,
antes/después, razón, impacto, revisión e idempotencia.

Autorizar crea una decisión inmutable y una nueva proyección o revisión. Rechazar conserva el
hecho y no modifica la proyección. No se exige separación de personas. Ningún cambio puede
reescribir una verificación cumplida, ejecución iniciada/terminada, incidencia, movimiento,
custodia, evidencia o cierre.

## 10. Ventanas de recursos

### 10.1 Significado

Una ventana P13 es la necesidad de disponer de un recurso en un intervalo `[inicio, fin)` derivado
de una necesidad del snapshot o cambio autorizado. No reserva capacidad ni espacio.

La identidad persistente e inmutable de `OperationalResourceWindow` —nombre físico provisional—
incluye organización, preparación, raíz, reserva, snapshot/necesidad, intervalo, revisión,
predecesora, procedencia/versionado, decisión autorizante cuando aplique, hash y referencias a la
revisión Scheduling utilizada.

### 10.2 Autoridad Scheduling obligatoria

La ventana es válida solo si concuerdan estructuralmente:

- EventPreparation, raíz y Reservation de la misma organización;
- ScheduleAllocation exacta de la reserva y su espacio;
- ScheduleEvent correspondiente;
- `source_event`, `source_revision`, `aggregate_revision`, identidad de reserva y, cuando aplique,
  predecesora/sucesora;
- estado y revisión persistentes de Reservation;
- `required_interval <@ ScheduleAllocation.occupied_interval`.

`ScheduleEvent.new_snapshot` es evidencia histórica, no autorización suficiente. Un JSON fabricado
o alterado por SQL directo no puede sustituir las relaciones anteriores. Si la necesidad excede la
ocupación, el comando falla y requiere primero un cambio de Scheduling.

### 10.3 Entrega y validación por Resources

Operations entrega por puerto un DTO inmutable con identidad, necesidad, organización, raíz,
reserva, intervalo, versión/hash y procedencia Scheduling. Resources adquiere sus locks y decide
capacidad/asignación.

`ResourceRequirement` porta exactamente una procedencia:

- `scheduling_event_interval`: legacy/P12, ventana nula e intervalo exactamente igual a
  `Reservation.event_interval`;
- `operations_window`: FK tenant-aware a ventana autorizada e intervalo exactamente igual a su
  `required_interval`, además contenido en `occupied_interval`.

Assignment y CapacityAllocation heredan esa rama del Requirement y no tienen discriminador
independiente. Sus organizaciones, raíz, reserva, recurso, cantidad e intervalos deben corresponder
con el requerimiento y entre sí.

## 11. Reprogramación y cancelación

Al reprogramar en `preparing` o `ready`:

1. Scheduling crea la reserva sucesora conforme a ADR 0016.
2. Operations conserva la predecesora `rescheduled`.
3. La sucesora congela un nuevo snapshot de evento desde la misma versión inmutable de plan y
   recalcula ventanas desde sus anclas contra la nueva autoridad Scheduling; no copia instantes
   absolutos.
4. Baseline se recrea por 5.2, readiness de plantilla se deriva del snapshot y solo ítems `manual`
   seleccionados se trasladan.
5. Resources libera/sustituye compromisos pendientes según ADR 0021; no se copian movimientos,
   custodia ni hechos ejecutados.

Cancelar conserva toda la historia y libera solo compromisos pendientes permitidos. No borra
snapshots, ventanas, incidencias, evidencia, asignaciones ejecutadas ni movimientos.

## 12. Cierre postevento

El cierre es un hecho append-only separado y solo se crea para una preparación `completed`.
Requiere revisión/idempotencia, actor, tiempo, fuentes exactas, hashes y evidencia del resultado.

Bloquean el cierre:

- verificaciones obligatorias `teardown`/`post_event` pendientes;
- cambios propuestos sin decisión;
- cualquier incidencia `open`;
- toda incidencia `contained high/critical`;
- incidencia `contained low/medium` cuya proyección efectiva y ledger canónico no conserven
  responsable, impacto no vacío y seguimiento explícito no vacío;
- ResourceRequirement `open`;
- ResourceAssignment `reserved` o `custody`;
- cualquier custodia o compromiso físico pendiente incompatible con cierre.

Se permiten:

- incidencia `contained` `low`/`medium` con responsable, impacto no vacío y seguimiento explícito
  no vacío; `detail` no satisface esta condición;
- incidencia `resolved`, sin imponerle responsable o seguimiento propios del estado `contained`;
- Requirement `shortage` histórico si existe incidencia/evidencia de consecuencia y no queda
  custodia o compromiso físico pendiente;
- Requirement `satisfied` con asignaciones terminales coherentes;
- Requirement `cancelled` solo por una transición legítima de Resources, nunca para ocultar un
  shortage;
- Assignment `issued` para consumible, `fulfilled` para servicio, `returned` para reutilizable o
  activo, y `released`/`cancelled` cuando un cambio autorizado o incidencia explica que no se usó.

Una corrección posterior añade un hecho enlazado; no reabre `completed` ni el cierre y no puede
degradar retrospectivamente una incidencia contenida por debajo de las condiciones con las que se
autorizó cerrar.

## 13. Capabilities

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

Los comandos intermodulares comprueban además la capability del módulo propietario. No se
infieren jerarquías ni permisos adicionales.

## 14. Seguridad, integridad e idempotencia

- Todo dato privado P13 pertenece a una organización y usa RLS `ENABLE` + `FORCE`.
- Las relaciones privadas usan FKs/uniques compuestas tenant-aware.
- El rol de aplicación recibe privilegios mínimos; snapshots, versiones publicadas, ledgers,
  ventanas, decisiones, incidencias consumadas y cierres no admiten destrucción.
- Cada comando relevante usa revisión esperada y clave idempotente persistente. Misma clave con
  payload distinto falla.
- Los locks siguen el orden: raíz/reserva y espacio; EventPreparation/P13; Requirement y recursos,
  activos/ubicaciones P12 en UUID ordenado; identidad Documents cuando aplique.
- Checks, triggers y guardianes diferidos deben cubrir servicios, `QuerySet.update`, ORM bulk y SQL
  directo y fallar antes del commit.
- Las correcciones son append-only y enlazan el hecho corregido.

## 15. Métricas

Operations puede informar tiempo hasta readiness, duración observada de fases, cumplimiento de
verificaciones, incidencias por tipo/severidad y tiempo de resolución, cambios autorizados, tiempo
hasta cierre y consecuencia operativa de faltantes/devoluciones. Setup/teardown se miden solo desde
sus hechos temporales efectivos y execution solo desde 5.2; post_event no tiene duración sintética.
Los estados de recursos provienen de DTO P12. Ingresos, costos, margen, utilidad y caja permanecen
en Finance.

## 16. Cutover desde P12

1. Clasificar por clave los siete baseline como `baseline_5_2`; clasificar los demás ítems
   existentes como `manual`, sin alterar contenido ni historia.
2. Mantener todos los ResourceRequirement existentes en
   `scheduling_event_interval = Reservation.event_interval`.
3. No fabricar plantillas, snapshots, ventanas, fases, roles, incidencias, decisiones, archivos ni
   cierres históricos.
4. Una preparación activa solo recibe snapshot `legacy_cutover` si se incorpora expresamente a
   P13; este registra estado observado y no afirma una plantilla previa.
5. Eventos terminales anteriores al cutover no reciben cierre P13 retrospectivo.

## 17. Criterios de aceptación de la implementación

- Las siete baseline y la máquina 5.2 siguen superando sus pruebas sin cambio semántico.
- Una obligación posterior no bloquea `ready` y cada fase bloquea únicamente su transición/cierre.
- La definición P13 no puede desviarse sin ledger y autorización, tampoco por bulk/SQL.
- El fallback y cada snapshot muestran una procedencia inequívoca y no mutan por publicaciones
  futuras.
- Reprogramación recalcula contra Scheduling; cancelación conserva historia.
- El guardián rechaza ScheduleEvent JSON fabricado, revisiones cruzadas, ventana fuera de ocupación,
  rama temporal arbitraria e intervalos divergentes en Resources.
- Dos organizaciones no pueden leer, relacionar ni mutar datos entre sí.
- Cierre preserva shortage histórico válido y bloquea custody/reserved.
- Evidencia usa exclusivamente Documents; imports de producción respetan todos los puertos.
- El rol de aplicación conserva privilegios mínimos después de `migrate -> db:prepare`.
- Métricas P13 reconcilian con sus fuentes y no duplican rentabilidad P11.

## 18. Exclusiones expresas

No se autorizan tareas libres fuera de PreparationItem manual, dependencias entre tareas, Gantt,
sprints, turnos, nómina, control horario, inventario o logística paralelos, agenda propia,
almacenamiento de archivos, marketplace, contabilidad, rentabilidad duplicada, microservicios ni
CRUD genérico. La API, serializers y frontend implementados conservan comandos y consultas
acotados; los nombres físicos respetan ADR 0022 y no alteran estas exclusiones.
