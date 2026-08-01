# Iteración 5.2 — De reserva confirmada a evento preparado

- **Estado:** Propuesta
- **Fecha de propuesta:** 1 de agosto de 2026
- **Módulo propuesto:** `claridez.operations`
- **Naturaleza:** especificación funcional y técnica; no autoriza implementación
- **Flujo precedente:** Iteración 5.1, 5.1.1 y 5.1.2 completadas

## 0. Estado documental y alcance de la decisión

Este documento propone el siguiente flujo vertical de Claridez. No está aprobado, aceptado,
iniciado ni implementado. Sus nombres, reglas, capacidades, endpoints y defensas PostgreSQL son
recomendaciones sujetas a aprobación expresa del propietario antes de modificar código o esquema.

La propuesta parte del contrato implementado en la
[Iteración 5.1](ITERATION_5_1_COMMERCIAL_FLOW.md): una `Reservation` confirmada conserva el horario,
la zona horaria y la versión aceptada de la cotización; `cancelled` es terminal; y la confirmación
no procesa pagos. El endurecimiento de [5.1.1](ITERATION_5_1_1_HARDENING.md) mantiene la
representación personal restringida para actores sin `person:read`. La reorganización de
[5.1.2](ITERATION_5_1_2_MAINTAINABILITY_CI.md) no cambió esos contratos.

### Problema operativo

Después de confirmar una reserva, salones y espacios de eventos pequeños y medianos necesitan una
vista compartida que convierta el compromiso comercial en trabajo operativo concreto. Hoy el flujo
termina en la confirmación y no responde, desde un límite operativo propio:

- qué eventos confirmados requieren preparación y atención inmediata;
- qué verificaciones faltan y quién responde por ellas;
- qué trabajo está pendiente, vencido o bloqueado;
- si la preparación satisface condiciones verificables para declararse lista;
- si la ejecución ya comenzó o terminó;
- qué trabajo debe cerrarse cuando comercial cancela la reserva.

### Resultado de producto propuesto

5.2 terminaría cuando un evento confirmado quede `completed` o cuando una cancelación comercial
cierre su preparación como `cancelled`. No incorpora trabajo posterior al evento.

## 1. Límite del módulo

### 1.1 Recomendación

Se recomienda crear `claridez.operations` como módulo del monolito modular. La preparación tiene
lenguaje, ciclo de vida, permisos e invariantes distintos de comercial; incorporarla a
`claridez.commercial` mezclaría la decisión de vender y reservar con la responsabilidad de
preparar y ejecutar.

`claridez.operations` sería propietario de:

- la preparación operativa uno-a-uno de una reserva confirmada;
- el responsable operativo principal;
- el checklist concreto de ese evento, sus responsables, vencimientos y bloqueos;
- la declaración de listo, el inicio y la finalización de la ejecución;
- el historial mínimo de transiciones operativas;
- las proyecciones de atención calculadas al consultar.

No sería propietario de persona, solicitud, cotización, líneas, importes, constancia de anticipo,
disponibilidad ni cancelación comercial.

### 1.2 Contrato consumido de comercial

Operaciones consumiría una proyección backend de solo lectura construida desde la reserva y sus
relaciones ya protegidas:

| Dato consumido                           | Fuente y semántica                                                                                           |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `reservation_id`                         | Identidad estable de `Reservation`; también identifica el evento operativo.                                  |
| `organization_id`                        | Límite tenant de la reserva; nunca se toma del cuerpo enviado por el cliente.                                |
| `status`                                 | Estado vivo de la reserva. Alcanzar `confirmed` crea y habilita la preparación en la misma transacción.      |
| `starts_at`, `ends_at`, `event_timezone` | Snapshot inmutable ya conservado por la reserva y su versión aceptada.                                       |
| Tipo, invitados y necesidad general      | Snapshots inmutables de la `QuotationVersion` aceptada.                                                      |
| Nombre del contacto                      | Snapshot aceptado para identificación histórica.                                                             |
| Teléfono del contacto                    | Proyección mínima y viva de `Person`, solo en detalle y mientras la preparación no terminó ni fue cancelada. |
| Cancelación                              | Estado, actor, fecha y razón permanecen en `Reservation`; operaciones solo refleja el cierre.                |

La proyección no entregaría correo, origen, notas comerciales, identificador de persona, revisiones
de persona, líneas o totales de cotización, moneda, descuentos, constancia de anticipo ni sus
actores. El puerto de lectura sería una superficie pública estrecha de `claridez.commercial`; no se
autoriza a operaciones a consultar tablas comerciales de forma dispersa.

### 1.3 Desacoplamiento

Se recomienda una **orquestación transaccional explícita** por encima de los dos módulos. El caso de
uso de confirmación invoca, dentro del mismo `transaction.atomic()` y del mismo
`authorized_tenant_scope`, el servicio comercial que confirma la reserva y el servicio operativo
que crea `EventPreparation`, sus siete `PreparationItem` y la transición `initialized`. El
endpoint solo responde correctamente si las cuatro operaciones se confirman juntas. No se usan
señales Django, callbacks ocultos ni infraestructura asíncrona.

La creación operativa es un efecto obligatorio de `reservation:confirm`, no un comando operativo
independiente. El actor solo necesita la capacidad comercial ya exigida para confirmar; ejecutar el
efecto no le concede `operation:read`, `operation:manage` ni `operation:execute`. En particular,
`finance` puede provocar la creación al confirmar según la matriz vigente de 5.1, pero no puede leer
ni gestionar el agregado resultante.

El coordinador de aplicación depende de las superficies públicas de `commercial` y `operations`;
ninguno de esos servicios llama internamente al otro. `operations` conserva una dependencia de
lectura hacia la proyección comercial y la FK a `Reservation`, pero `commercial` no consulta
tablas operativas de forma dispersa.

Una reserva que alcanza `confirmed` debe tener exactamente una `EventPreparation`. Si crear la
preparación, la baseline o la transición falla, se revierte también la confirmación. Reservas
provisionales, vencidas o canceladas antes de confirmar no tienen preparación.

Un trigger PostgreSQL transversal permanece como **decisión pendiente**, no aceptada. Esta
propuesta recomienda evaluar la combinación de orquestación explícita como ruta principal y trigger
como defensa final para SQL directo o bulk, pero exige un ADR antes de implementarla. El ADR deberá
comparar dependencia entre módulos, garantías transaccionales, operaciones fuera de servicios y
orden y reversión de migraciones.

## 2. Modelo de dominio propuesto

```text
commercial.Reservation que alcanzó confirmed (1) ─── (1) operations.EventPreparation
                                                         │
                                                         ├── (1..n) PreparationItem
                                                         └── (1..n) PreparationTransition
```

### 2.1 `EventPreparation`

Se recomienda una relación **uno a uno obligatoria desde la confirmación** con `Reservation`. Una
reserva representa un único compromiso confirmado y 5.2 excluye reprogramación; varias
preparaciones para la misma reserva crearían versiones operativas sin una causa de dominio
aprobada. Antes de confirmar, la reserva no tiene preparación; al confirmarse, ambas quedan
coherentes dentro de la misma transacción.

`reservation_id` sería a la vez clave primaria de `EventPreparation`. No hace falta un segundo UUID
para nombrar el mismo evento.

| Campo conceptual                             | Regla propuesta                                                                                                            |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `reservation_id`                             | PK y FK protegida hacia `commercial.Reservation`; inmutable.                                                               |
| `organization_id`                            | Obligatorio; participa en FK compuesta con la reserva y todas las relaciones tenant-aware.                                 |
| `status`                                     | `preparing`, `ready`, `in_progress`, `completed` o `cancelled`.                                                            |
| `responsible_membership_id`                  | Membresía principal; puede faltar en `preparing` y en un `cancelled` que nunca fue asignado; es obligatoria desde `ready`. |
| `operational_notes`                          | Texto operativo propio, opcional, máximo 4000 caracteres; no copia notas comerciales.                                      |
| `baseline_version`                           | Identificador inmutable del checklist base sembrado, inicialmente `operations-5.2-v1`.                                     |
| `revision`                                   | Entero positivo; comienza en 1 y protege cambios del agregado.                                                             |
| `ready_at`, `ready_by_membership_id`         | Evidencia de la última declaración de listo; se limpia solo al reabrir y se conserva al iniciar, completar o cancelar.     |
| `started_at`, `started_by_membership_id`     | Evidencia inmutable del inicio de ejecución.                                                                               |
| `completed_at`, `completed_by_membership_id` | Evidencia inmutable de finalización.                                                                                       |
| `created_at`, `updated_at`                   | `created_at` pertenece a la transacción de confirmación; `updated_at` solo cambia ante una mutación efectiva.              |

No se copian nombre, teléfono, correo, solicitud, cotización, importes, moneda, anticipo, fecha del
evento ni zona horaria. La reserva y la versión aceptada ya preservan los snapshots necesarios. La
configuración y el estado de las membresías se consultan como referencias vivas; las FK usan
`PROTECT`.

### 2.2 `PreparationItem`

El checklist se modelaría con ítems operativos específicos, no con un sistema genérico de tareas.

| Campo conceptual                             | Regla propuesta                                                                                                                        |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                                         | UUID propio.                                                                                                                           |
| `organization_id`                            | Obligatorio y parte de todas las FK compuestas.                                                                                        |
| `preparation_id`                             | FK a `EventPreparation`; inmutable.                                                                                                    |
| `client_request_id`                          | UUID único por preparación para reintentos idempotentes; lo envía el cliente en ítems libres y lo genera el servidor para la baseline. |
| `baseline_key`                               | Clave nullable e inmutable de un ítem base; única por preparación.                                                                     |
| `section`                                    | `definitions`, `setup` o `final_review`; no existe tabla de secciones.                                                                 |
| `position`                                   | Entero positivo, único dentro de la preparación; el servicio mantiene orden contiguo.                                                  |
| `title`                                      | Texto obligatorio, canónico, máximo 160 caracteres.                                                                                    |
| `is_required`                                | Indica que debe resolverse antes de `ready`. Los ítems base siempre son obligatorios.                                                  |
| `responsible_membership_id`                  | Responsable opcional del ítem; si falta, se muestra el responsable principal efectivo.                                                 |
| `due_on`                                     | Fecha calendario en la zona horaria capturada por la reserva; nullable para ítems libres.                                              |
| `status`                                     | `pending`, `in_progress`, `blocked`, `completed` o `not_applicable`.                                                                   |
| `notes`                                      | Texto operativo opcional, máximo 2000 caracteres.                                                                                      |
| `status_note`                                | Obligatoria en `blocked` y `not_applicable`; vacía en los demás estados.                                                               |
| `completed_at`, `completed_by_membership_id` | Presentes únicamente en `completed`.                                                                                                   |
| `revision`                                   | Entero positivo para control optimista del ítem.                                                                                       |
| `created_at`, `updated_at`                   | Marcas conscientes; no cambian en reintentos sin diferencias.                                                                          |

`not_applicable` resuelve expresamente un requisito que no corresponde al evento y exige
justificación y actor. El ítem base `final_readiness_review` nunca admite `not_applicable`.
`blocked` no es una nota informal: exige motivo y bloquea la declaración de listo incluso si el
ítem era opcional.

No se concede `DELETE`. Un ítem creado por error se conserva como `not_applicable` con explicación.
La edición de un ítem deja de estar disponible cuando la ejecución comienza.

### 2.3 `PreparationTransition`

Una tabla append-only preservaría el historial mínimo de estados, incluidas reaperturas:

| Campo conceptual                          | Regla propuesta                                                                                                                    |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `id`, `organization_id`, `preparation_id` | UUID y relaciones tenant-aware.                                                                                                    |
| `from_status`, `to_status`                | Estado anterior nullable solo en la creación automática y estado resultante.                                                       |
| `cause`                                   | `initialized`, `readiness_declared`, `checklist_reopened`, `execution_started`, `execution_completed` o `commercial_cancellation`. |
| `actor_membership_id`                     | Actor explícito; en cancelación es la membresía registrada por comercial.                                                          |
| `preparation_revision`                    | Revisión resultante, única por preparación para una transición.                                                                    |
| `occurred_at`                             | Instante consciente e inmutable.                                                                                                   |

No contendría JSON libre ni duplicaría la razón de cancelación. El estado actual y sus marcas viven
en `EventPreparation`; la razón y evidencia comercial permanecen en `Reservation`. La aplicación
no podría actualizar ni borrar transiciones.

5.2 no propone historial de cada carácter editado en títulos o notas. Revisiones optimistas,
ausencia de borrado, evidencia de completado y transiciones preservan el historial necesario para
este alcance; una bitácora de auditoría exhaustiva queda diferida.

## 3. Máquina de estados

### 3.1 Estados persistidos

```text
reserva provisional ── confirmar + crear agregado operativo ──► preparing
                                                               │
                                          declarar listo       ▼
                                      preparing ─────────────► ready
                                          ▲                     │
                                          └── cambio que ───────┘
                                              invalida listo     │ iniciar
                                                                 ▼
                                                            in_progress
                                                                 │ completar
                                                                 ▼
                                                             completed

commercial cancellation: preparing | ready → cancelled
```

No se adopta `pending` para la preparación porque duplicaría la existencia de ítems pendientes. La
creación atómica deja el agregado directamente en `preparing`.

| Estado        | Significado                                                                             |
| ------------- | --------------------------------------------------------------------------------------- |
| `preparing`   | Existe trabajo operativo editable; aún no hay una declaración de listo vigente.         |
| `ready`       | Un actor autorizado verificó responsable, checklist obligatorio y ausencia de bloqueos. |
| `in_progress` | La ejecución del evento comenzó por comando explícito.                                  |
| `completed`   | La ejecución terminó; no implica pagos, cierre financiero ni tareas posteriores.        |
| `cancelled`   | Comercial canceló la reserva; todo trabajo operativo queda congelado.                   |

El tiempo por sí solo no cambia estados. Llegar a la hora del evento no inicia ni completa nada.

### 3.2 Transiciones y comandos

| Entrada               | Transición                                | Actor y capacidad                                                    | Condiciones previas                                                                                                                                                           | Efectos e idempotencia                                                                                                                                                                                                                                        |
| --------------------- | ----------------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Reserva provisional   | `Reservation → confirmed` y `→ preparing` | Actor con `reservation:confirm` mediante el orquestador              | Todas las condiciones comerciales de 5.1; todavía no existe preparación.                                                                                                      | Confirma la reserva y crea preparación, siete ítems base y transición `initialized` en una sola transacción. El actor de la transición es quien confirma. Repetir la confirmación valida que exista exactamente un agregado y no duplica filas ni revisiones. |
| `preparing`           | `→ ready`                                 | Actor con `operation:manage`                                         | Revisión vigente, reserva confirmada, responsable principal activo y elegible, baseline íntegra, todos los obligatorios resueltos, revisión final completada y cero bloqueos. | Registra actor/fecha y transición; reintento en `ready` es `200` sin nueva transición.                                                                                                                                                                        |
| `ready`               | `→ preparing`                             | Mismo actor que efectúa un cambio con `operation:manage`             | Una mutación autorizada invalida la declaración: reabre un obligatorio, bloquea un ítem, añade un obligatorio pendiente o cambia el contenido ya completado.                  | Ocurre antes del cambio, limpia evidencia vigente de listo, incrementa revisión y registra `checklist_reopened`. No hay comando de reapertura separado.                                                                                                       |
| `ready`               | `→ in_progress`                           | Actor con `operation:execute`                                        | Revisión vigente y reserva todavía confirmada.                                                                                                                                | Registra inicio. No impone tolerancia horaria inventada: el actor declara el hecho. Repetir devuelve el estado actual.                                                                                                                                        |
| `in_progress`         | `→ completed`                             | Actor con `operation:execute`                                        | Revisión vigente y reserva todavía confirmada.                                                                                                                                | Registra finalización. Repetir devuelve el estado actual.                                                                                                                                                                                                     |
| `preparing` o `ready` | `→ cancelled`                             | Actor de comercial con `reservation:cancel`, mediante el orquestador | Reserva confirmada y preparación bloqueada en uno de los dos estados permitidos.                                                                                              | Cancela reserva y preparación y registra `commercial_cancellation` en una transacción. Repetir la cancelación no duplica transición.                                                                                                                          |

### 3.3 Transiciones prohibidas

- `preparing → in_progress` o `completed`: no se omite la declaración de listo.
- `ready → completed`: siempre debe registrarse el inicio.
- `in_progress → preparing` o `ready`: no se retrocede una ejecución observada.
- `in_progress → cancelled` y `completed → cancelled`: el comando comercial devuelve `409` y no
  modifica reserva ni preparación.
- cualquier comando operativo desde `cancelled`: estado terminal.
- cualquier comando desde `completed`: estado terminal en 5.2.
- edición de checklist en `in_progress`, `completed` o `cancelled`.
- una interrupción durante la ejecución y una corrección administrativa posterior quedan fuera de
  5.2; no se representan como cancelación.
- reactivación de una reserva cancelada. La reserva de 5.1 ya es terminal; una futura
  reprogramación deberá crear su propio contrato y, previsiblemente, una nueva reserva y
  preparación. No se define en 5.2.

## 4. Checklist operativo

### 4.1 Combinación mínima

Se recomienda una combinación gradual:

1. checklist base de producto, versionado y creado automáticamente al confirmar;
2. ítems libres por evento;
3. tres secciones controladas como enum para lectura y orden;
4. estados, responsables y fechas límite por ítem.

No se crean entidades de sección, hito, proyecto, dependencia entre tareas ni plantilla por
organización. `ready`, `in_progress` y `completed` ya actúan como hitos del flujo.

### 4.2 Baseline `operations-5.2-v1`

| Orden | `baseline_key`           | Sección        | Título inicial                               | Vencimiento sugerido |
| ----: | ------------------------ | -------------- | -------------------------------------------- | -------------------- |
|     1 | `space_layout`           | `definitions`  | Confirmar distribución del espacio           | 7 días antes         |
|     2 | `guest_count`            | `definitions`  | Revisar número estimado de invitados         | 7 días antes         |
|     3 | `special_requirements`   | `definitions`  | Confirmar requerimientos especiales          | 7 días antes         |
|     4 | `entry_schedule`         | `definitions`  | Validar horario de ingreso                   | 7 días antes         |
|     5 | `furniture`              | `setup`        | Preparar mobiliario                          | 1 día antes          |
|     6 | `decoration`             | `setup`        | Verificar decoración                         | 1 día antes          |
|     7 | `final_readiness_review` | `final_review` | Revisar que todo esté listo antes del evento | Fecha del evento     |

Todos son obligatorios en el sentido de que deben resolverse. Los seis primeros admiten
`not_applicable` con justificación; la revisión final solo se resuelve con `completed`.

Las fechas se calculan con el día local del evento en `Reservation.event_timezone` y nunca antes
del día local de confirmación: `max(fecha de confirmación, fecha del evento - desplazamiento)`.
Así, una confirmación tardía produce trabajo para hoy en lugar de fechas artificialmente pasadas.

Los títulos pueden aclararse para el evento, pero `baseline_key` no cambia. Modificar el contenido
de un ítem ya completado lo devuelve a `pending` porque la evidencia anterior describía otra
verificación.

### 4.3 Ítems libres

Un actor con `operation:manage` puede añadir verificaciones específicas, por ejemplo ubicación de
una mesa especial o restricción de acceso. Decide si son obligatorias, asigna responsable, fecha y
sección. No existen subtareas, dependencias, porcentajes, etiquetas ni recurrencia.

Antes de iniciar la ejecución, un ítem puede pasar entre `pending`, `in_progress`, `blocked`,
`completed` y `not_applicable`, sujeto a las evidencias indicadas. Volver desde `completed` o
`not_applicable` a un estado sin resolver es una corrección válida, incrementa revisiones y reabre
una preparación `ready`. Repetir el mismo estado y contenido normalizados es idempotente. Desde
`in_progress`, `completed` o `cancelled` de la preparación no se admite ninguna transición de ítem.

La prioridad no se incorpora. En un checklist corto, obligatoriedad, vencimiento, bloqueo y orden
ya expresan qué requiere atención; una escala adicional sería ambigua sin reglas de negocio.

### 4.4 Reglas de listo

`ready` exige simultáneamente:

1. reserva todavía `confirmed`;
2. responsable principal de la misma organización, activo y con `operation:manage` al declarar;
3. los siete `baseline_key` presentes exactamente una vez;
4. todo ítem con `is_required=true` en `completed` o `not_applicable`;
5. `final_readiness_review` en `completed`;
6. ningún ítem en `blocked`;
7. revisión de preparación coincidente.

Una fecha vencida no impide declarar listo si el trabajo ya se resolvió; queda reflejada por sus
marcas. Un ítem opcional pendiente tampoco bloquea. La interfaz debe explicar ambos casos antes de
confirmar la declaración.

### 4.5 Archivos y evidencia

No hay campos de archivo, fotografías, enlaces de evidencia ni adjuntos. Las notas son texto breve
y no deben usarse para almacenar secretos o datos personales innecesarios. Evidencia adjunta queda
fuera de 5.2.

## 5. Responsables y autorización

### 5.1 Catálogo mínimo de capacidades nuevas

Se recomiendan tres capacidades:

- `operation:read`: lista, detalle, estados, checklist y proyección personal mínima;
- `operation:manage`: notas, responsable principal, ítems y declaración de listo;
- `operation:execute`: inicio y finalización de la ejecución.

No se crean `operation:assign` ni `operation:mark_ready` porque en 5.2 tendrían exactamente los
mismos actores que `operation:manage`. Tampoco se separan `start` y `complete`: comparten actores y
riesgo, mientras la máquina de estados ya impide usarlos fuera de orden. Si una política futura
necesita separar funciones, deberá ampliar explícitamente el catálogo.

No existe `operation:cancel`. La única autoridad de cancelación sigue siendo
`reservation:cancel` en comercial.

### 5.2 Matriz provisional propuesta

| Capacidad           | `owner` | `administrator` | `commercial` | `operations` | `finance` |
| ------------------- | :-----: | :-------------: | :----------: | :----------: | :-------: |
| `operation:read`    |   Sí    |       Sí        |      Sí      |      Sí      |    No     |
| `operation:manage`  |   Sí    |       Sí        |      No      |      Sí      |    No     |
| `operation:execute` |   Sí    |       Sí        |      No      |      Sí      |    No     |

- `operations` prepara, asigna, declara listo, inicia y completa.
- `owner` y `administrator` realizan las mismas acciones para supervisión y cobertura en equipos
  pequeños.
- `commercial` consulta estado, pendientes y bloqueos para coordinar expectativas, pero no modifica.
- `finance` no necesita este módulo en 5.2. Sus capacidades comerciales existentes no conceden
  acceso operativo. Si confirma una reserva mediante su capacidad vigente de 5.1, la creación
  automática ocurre como efecto obligatorio del comando sin otorgarle ninguna capacidad de
  operations.

No hay jerarquía implícita. Cada endpoint exige una capacidad concreta en
`authorized_tenant_scope`; rol desconocido, capacidad desconocida, usuario, organización o
membresía inactivos se deniegan por defecto. Ocultar botones en React solo mejora la experiencia.

### 5.3 Elegibilidad de responsables

El responsable principal y el responsable directo de un ítem deben ser membresías activas de la
misma organización que posean `operation:manage`: `owner`, `administrator` u `operations` según la
matriz propuesta. No se asigna a `commercial` ni `finance`.

El responsable principal puede cambiar en `preparing`, `ready` o `in_progress`; la reasignación a
otra membresía elegible no altera por sí sola una declaración de listo. `completed` y `cancelled`
congelan la asignación final. Los responsables de ítems solo cambian antes de iniciar la ejecución.

Operaciones no recibe `membership:read`. Un directorio operativo estrecho entrega únicamente
`membership_id`, `display_name` y `role` de responsables elegibles activos, sin correo ni el resto
del ciclo de membresía. Una suspensión posterior no borra la asignación histórica; la respuesta
marca `responsible_available=false` para que un actor autorizado reasigne. No se deshace
automáticamente una declaración de listo porque la preparación física ya fue atestiguada.

## 6. Privacidad y minimización de datos personales

### 6.1 Representación operacional

`operation:read` no implica ni concede `person:read`. La API operativa materializa una vista
específica:

| Dato                                      |          Listado          |                   Detalle                    | Justificación                                            |
| ----------------------------------------- | :-----------------------: | :------------------------------------------: | -------------------------------------------------------- |
| Nombre del contacto                       |            Sí             |           Sí, en todos los estados           | Identificación histórica desde el snapshot aceptado.     |
| Teléfono E.164 vivo                       |            No             | Solo en `preparing`, `ready` e `in_progress` | Coordinación inmediata mientras el evento sigue activo.  |
| Correo                                    |            No             |                      No                      | No es necesario para preparación en 5.2.                 |
| Tipo, horario e invitados del evento      |            Sí             |                      Sí                      | Núcleo de planificación; proviene del snapshot aceptado. |
| Necesidad general                         | Resumen truncado opcional |                      Sí                      | Requerimiento operativo confirmado.                      |
| Notas comerciales                         |            No             |                      No                      | Pueden incluir negociación o datos no necesarios.        |
| Cotización, líneas, importes y descuentos |            No             |                      No                      | Propiedad comercial y fuera del propósito operativo.     |
| Anticipo, referencia o excepción          |            No             |                      No                      | Información financiera/comercial no necesaria.           |
| `person_id`, origen y revisiones          |            No             |                      No                      | Evita convertir la vista operativa en acceso a personas. |

El nombre procede de `QuotationVersion.person_name_snapshot` y puede conservarse en `completed` y
`cancelled` para identificación histórica. El teléfono se obtiene de la persona viva mediante el
puerto de proyección comercial y **se omite por completo**, en lugar de enviarse como `null`, cuando
la preparación está `completed` o `cancelled`. Ninguno se copia a tablas operativas. Los demás
detalles del evento provienen del snapshot aceptado e inmutable.

El backend aplica esta forma antes de salir de `authorized_tenant_scope`, usando el estado operativo
persistido para decidir la presencia del teléfono. Ni parámetros del cliente ni el frontend deciden
campos. Las pruebas deben buscar explícitamente teléfono en estados terminales y correo, notas,
importes y evidencia de anticipo en todas las respuestas, incluidas estructuras anidadas y errores.
Estado y contacto deben materializarse desde una misma vista transaccional para que una transición
concurrente a `completed` o `cancelled` no combine un estado terminal con un teléfono leído después.

## 7. Fechas, vencimientos y alertas calculadas

### 7.1 Regla temporal

PostgreSQL guarda instantes conscientes. `starts_at`, `ends_at` y `event_timezone` siguen siendo los
capturados por la reserva. `due_on` es una fecha calendario interpretada en esa zona; `ready_at`,
`started_at`, `completed_at` y auditoría son instantes renderizados en la zona del evento.

`OrganizationSettings.timezone` comienza en `America/Guayaquil` y se captura en el flujo comercial.
Si la organización cambia después su configuración, los eventos ya confirmados mantienen su zona
capturada; los nuevos eventos heredan la configuración vigente. Esto evita que un cambio futuro
desplace fechas límite ya acordadas.

### 7.2 Indicadores derivados al consultar

Con `today` y `now` calculados en `Reservation.event_timezone`:

| Indicador                 | Regla exacta                                                                                     |
| ------------------------- | ------------------------------------------------------------------------------------------------ |
| Ítem pendiente            | `status` es `pending` o `in_progress`.                                                           |
| Ítem vencido              | `due_on < today` y estado no es `completed` ni `not_applicable`.                                 |
| Con bloqueo               | Existe al menos un ítem `blocked`.                                                               |
| Preparación atrasada      | Está `preparing` y se cumple `(existe un obligatorio vencido sin resolver OR now >= starts_at)`. |
| Evento próximo            | `now < starts_at` y su fecha local está entre `today` y `today + 7 días`, inclusivos.            |
| Evento listo              | Estado persistido `ready`.                                                                       |
| Responsable no disponible | La membresía asignada ya no está activa o dejó de ser elegible.                                  |

Los siete días son una regla de presentación propuesta, no una notificación ni una nueva
configuración. La API devuelve flags y conteos independientes; no aplasta situaciones simultáneas
en una sola etiqueta. Ninguna consulta persiste cambios por el paso del tiempo.

No hay cron, worker, cola, correo, WhatsApp ni notificación push. Los indicadores se calculan en la
consulta con índices sobre organización, estado, intervalo, responsable, `due_on` y estado de ítem.

## 8. Concurrencia e integridad PostgreSQL

### 8.1 Revisión optimista

- `EventPreparation.revision` protege responsable, notas y comandos de estado.
- Toda mutación efectiva de un ítem incrementa también, mediante expresión `F`, la revisión de la
  preparación. Así `mark-ready` detecta cualquier cambio agregado posterior a la pantalla leída.
- `PreparationItem.revision` permite que dos ediciones del mismo ítem tengan un solo ganador.
- Dos ítems distintos pueden actualizarse sucesivamente y ambos completar; no comparten una
  revisión esperada de ítem.
- Normalizar y enviar exactamente el estado ya persistido devuelve `200` sin cambiar revisión ni
  `updated_at`.
- Una revisión obsoleta devuelve `409 stale_revision` con la representación actual autorizada; el
  backend nunca aplica last-write-wins silencioso.

### 8.2 Orden de bloqueos

Toda escritura operativa seguiría el orden:

```text
Reservation → EventPreparation → PreparationItem(s)
```

El orquestador de confirmación bloquea primero `Reservation` y mantiene el bloqueo hasta que la
reserva, preparación, baseline y transición queden confirmadas. El orquestador de cancelación
bloquea después `EventPreparation` para validar que todavía esté `preparing` o `ready`. Esta regla
evita el ciclo inverso. Asignaciones validan la membresía tenant-aware dentro de la misma
transacción, sin convertirla en pivote de bloqueo del agregado.

Casos concurrentes:

- mismo ítem: una revisión gana y la otra recibe `409`;
- ítems distintos: ambos cambios pueden completar y cada uno incrementa la revisión agregada;
- dos asignaciones: el bloqueo y revisión de preparación dejan un ganador;
- dos declaraciones de listo: la primera transiciona; la segunda observa `ready` y responde
  idempotentemente sin otra transición;
- ítem contra `ready`: si el ítem gana primero, `ready` ve revisión obsoleta; si `ready` gana, un
  cambio invalidante reabre primero la preparación;
- dos confirmaciones: la primera crea el agregado completo; la segunda valida la reserva ya
  confirmada y la única preparación sin duplicar baseline ni transición;
- fallo al crear preparación, cualquier ítem o `initialized`: toda la confirmación se revierte;
- cancelación contra edición en `preparing` o `ready`: si cancela primero, la edición devuelve
  conflicto; si la edición termina primero, la cancelación conserva el cambio y cierra después el
  agregado;
- cancelación contra `start`: si cancelar obtiene primero el bloqueo, deja ambos agregados
  `cancelled` y `start` falla; si `start` gana, deja `in_progress` y cancelar responde `409` sin
  modificar la reserva;
- cancelación contra `complete`: la preparación ya está `in_progress` o `completed`, por lo que la
  cancelación se rechaza en cualquier orden.

### 8.3 Defensas por capa

| Invariante                                 | Defensa propuesta                                                                                                                                                                 |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Como máximo una preparación por reserva    | PK/FK uno-a-uno.                                                                                                                                                                  |
| Toda confirmada tiene preparación completa | Orquestador y transacción atómica; la defensa PostgreSQL para SQL directo/bulk queda sujeta al ADR transversal.                                                                   |
| Pertenencia al mismo tenant                | FK compuesta `(organization_id, reservation_id)` y equivalentes para preparación, ítems, transiciones y membresías.                                                               |
| Cancelación solo antes de ejecutar         | Orquestador bloquea preparación y permite únicamente `preparing`/`ready`; el trigger guardián para rutas directas es candidato pendiente.                                         |
| Cancelación coherente                      | Servicio operativo cambia preparación y agrega transición en la misma transacción comercial; un trigger de sincronización se recomienda solo como defensa final pendiente de ADR. |
| Estado y marcas coherentes                 | `CHECK` para catálogo, revisión positiva y combinaciones de `ready_at`, `started_at`, `completed_at`; trigger interno de operaciones para el orden de transiciones.               |
| Listo realmente válido                     | Trigger interno inmediato al entrar en `ready`, bajo bloqueo de preparación, comprueba responsable, baseline, obligatorios, revisión final y bloqueos.                            |
| No invalidar listo por SQL directo         | Trigger interno de ítems rechaza mutaciones mientras el padre esté `ready` salvo que la transacción ya lo haya reabierto a `preparing`.                                           |
| Ítems terminales/evidencia                 | `CHECK` de estado, `status_note` y evidencia de completado; trigger interno impide edición tras inicio y todo `DELETE`.                                                           |
| Historial                                  | Transiciones append-only; trigger interno valida estado/revisión actuales y rechaza inserciones incoherentes, `UPDATE` y `DELETE`.                                                |
| Orden e idempotencia                       | `UNIQUE` por preparación para posición, `baseline_key` y `client_request_id`.                                                                                                     |

Los triggers **internos de operaciones** propuestos serían funciones invoker con `search_path`
fijo, sin `SECURITY DEFINER` y con ejecución revocada a `PUBLIC`, siguiendo 5.1. El eventual trigger
sobre `commercial_reservation` no pertenece todavía a este conjunto decidido: el ADR deberá
determinar si crea o exige el agregado al confirmar, si bloquea cancelaciones tardías y si
sincroniza la cancelación para SQL directo/bulk. También deberá resolver si puede ser inmediato sin
duplicar lógica y sin perder el GUC tenant antes del commit.

Todas las tablas operativas tendrían RLS `ENABLE` + `FORCE`, políticas `USING` y `WITH CHECK`
basadas en `claridez_current_organization_id()`. `claridez_app` recibiría solo `SELECT`, `INSERT` y
`UPDATE` necesarios; no `DELETE`, `TRUNCATE`, ownership ni `BYPASSRLS`. El migrador conservaría DDL
y el test runner los privilegios de integración definidos por la plataforma.

ORM, `QuerySet.update`, `bulk_create`, `bulk_update` y SQL directo no son rutas de dominio para
confirmar o cancelar. Antes de implementar, el ADR debe fijar y probar si PostgreSQL los rechaza o
los completa de forma coherente; nunca podrán dejar silenciosamente una reserva confirmada sin
preparación, cancelar durante/después de ejecución ni mantener una preparación activa tras cancelar.
RLS, FK y checks siguen aplicando en cualquier alternativa. Vistas, serializers y tareas futuras no
podrían establecer el GUC directamente ni salir de `authorized_tenant_scope` durante validación,
consulta y materialización.

## 9. API REST propuesta

Todas las rutas comienzan con `/api/v1/organizations/{organization_id}/`, usan sesión Django y
JSON. Todo `PUT`, `PATCH` y `POST` exige CSRF. No hay `DELETE`.

### 9.1 Convenciones de respuesta

El recurso de detalle se identifica por `reservation_id` y tiene esta forma conceptual:

```json
{
  "reservation_id": "uuid",
  "event": {
    "event_type": "Boda",
    "starts_at": "2026-09-12T20:00:00Z",
    "ends_at": "2026-09-13T02:00:00Z",
    "timezone": "America/Guayaquil",
    "estimated_guests": 120,
    "general_need": "Recepción y ceremonia"
  },
  "contact": { "display_name": "Contacto", "phone_e164": "+593999999999" },
  "preparation": {
    "status": "preparing",
    "revision": 1,
    "baseline_version": "operations-5.2-v1"
  }
}
```

Toda respuesta operativa corresponde a una preparación existente. `preparation` incorpora estado,
revisión, responsable mínimo, notas, baseline, marcas, flags/conteos y los ítems ordenados. El
listado omite teléfono, notas extensas y detalle de ítems; expone conteos y nombre de contacto. En
detalle, `phone_e164` solo aparece para `preparing`, `ready` e `in_progress`; el objeto `contact` de
`completed` y `cancelled` conserva el nombre pero omite esa clave.

El listado acepta `from`, `to`, `status`, `attention`, `responsible_membership_id`, `cursor` y
`page_size` (1–100). Sin fechas usa desde el inicio del día local actual hasta el final del día 30,
e incluye además toda preparación no terminal cuyo evento quedó antes del rango para que el trabajo
abierto no desaparezca. `completed` y `cancelled` se excluyen por defecto y aparecen al pedir esos
estados. El rango explícito máximo es 366 días. Orden estable: `starts_at`, `reservation_id`.

### 9.2 Endpoints

| Método y ruta relativa                                      | Capacidad             | Entrada                                                                                                                                  | Respuesta y códigos                                                                                                                                                        | Errores e idempotencia                                                                                                                                                                                 |
| ----------------------------------------------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET operations/capabilities/`                              | `organization:access` | Sin cuerpo.                                                                                                                              | `200` con las capacidades operativas efectivas.                                                                                                                            | `401`, `404`; seguro e idempotente. Permite que `finance` reciba lista vacía sin obtener datos operativos.                                                                                             |
| `GET operations/assignees/`                                 | `operation:manage`    | Sin cuerpo.                                                                                                                              | `200` con membresías activas elegibles: id, nombre y rol.                                                                                                                  | `401`, `403`, `404`; seguro e idempotente; nunca entrega correo.                                                                                                                                       |
| `GET operations/events/`                                    | `operation:read`      | Filtros y cursor descritos.                                                                                                              | `200` paginado; cada fila tiene preparación.                                                                                                                               | `400 invalid_filter`, `401`, `403`, `404`; seguro e idempotente.                                                                                                                                       |
| `GET operations/events/{reservation_id}/`                   | `operation:read`      | Sin cuerpo.                                                                                                                              | `200` con preparación y checklist; teléfono condicionado al estado.                                                                                                        | `401`, `403`, `404 resource_unavailable`; seguro e idempotente.                                                                                                                                        |
| `PATCH operations/events/{reservation_id}/preparation/`     | `operation:manage`    | `{revision, operational_notes}`; las notas pueden ser texto vacío para limpiar.                                                          | `200` con detalle.                                                                                                                                                         | `400`, `404`, `409 stale_revision`, `409 invalid_transition`; mismo valor normalizado es idempotente.                                                                                                  |
| `POST operations/events/{reservation_id}/assign/`           | `operation:manage`    | `{revision, responsible_membership_id}`.                                                                                                 | `200` con detalle.                                                                                                                                                         | `400`, `404` para membresía inexistente o ajena, `409 stale_revision`, `409 responsible_unavailable`, `409 invalid_transition`; repetir misma asignación no incrementa.                                |
| `POST operations/events/{reservation_id}/items/`            | `operation:manage`    | `{client_request_id, title, section, is_required, due_on?, responsible_membership_id?, notes?, place_before_item_id?}`.                  | `201`; replay idéntico `200`.                                                                                                                                              | `400`, `404`, `409 idempotency_conflict`, `409 invalid_transition`; token igual con payload distinto se rechaza.                                                                                       |
| `PATCH operations/events/{reservation_id}/items/{item_id}/` | `operation:manage`    | `{revision, title?, section?, is_required?, due_on?, responsible_membership_id?, notes?, status?, status_note?, place_before_item_id?}`. | `200` con ítem y resumen actualizado.                                                                                                                                      | `400`, `404`, `409 stale_revision`, `409 invalid_item_transition`, `409 invalid_transition`; no-op normalizado es idempotente.                                                                         |
| `POST operations/events/{reservation_id}/ready/`            | `operation:manage`    | `{revision}`.                                                                                                                            | `200` con preparación `ready`.                                                                                                                                             | `404`, `409 stale_revision`, `409 responsible_required`, `409 baseline_incomplete`, `409 required_items_pending`, `409 blocked_items`, `409 reservation_cancelled`; repetir en `ready` es idempotente. |
| `POST operations/events/{reservation_id}/start/`            | `operation:execute`   | `{revision}`.                                                                                                                            | `200` con `in_progress`.                                                                                                                                                   | `404`, `409 stale_revision`, `409 invalid_transition`, `409 reservation_cancelled`; repetir en `in_progress` es idempotente.                                                                           |
| `POST operations/events/{reservation_id}/complete/`         | `operation:execute`   | `{revision}`.                                                                                                                            | `200` con `completed` y sin teléfono.                                                                                                                                      | `404`, `409 stale_revision`, `409 invalid_transition`, `409 reservation_cancelled`; repetir en `completed` es idempotente.                                                                             |
| `POST reservations/{reservation_id}/confirm/` existente     | `reservation:confirm` | Contrato de 5.1.                                                                                                                         | `200` solo después de confirmar reserva y crear preparación, baseline y `initialized`.                                                                                     | Repetición idempotente valida la única preparación; cualquier fallo operativo revierte la confirmación. Una incoherencia previa devuelve `409 operation_integrity_conflict`.                           |
| `POST reservations/{reservation_id}/cancel/` existente      | `reservation:cancel`  | Contrato de 5.1: `{reason}`.                                                                                                             | `200` desde `preparing` o `ready`; ambas quedan `cancelled`. Cualquier replay cuando ambas ya están canceladas devuelve el resultado actual sin cambiar la razón original. | `409 operation_already_started` en `in_progress`; `409 operation_already_completed` en `completed`; no añade endpoint operativo de cancelación.                                                        |

### 9.3 Semántica de errores y tenancy

- sesión ausente o inválida: `401 authentication_required`;
- capacidad ausente en una organización válida del actor: `403 forbidden`;
- CSRF ausente o inválido: `403` sin ejecutar el servicio;
- organización ajena, `reservation_id`, `item_id`, responsable o referencia relacionada ajenos o
  inexistentes: mismo `404 resource_unavailable`, sin confirmar existencia;
- JSON, enum, fecha o texto inválidos: `400 invalid_request` con errores de campo seguros;
- conflicto de estado o revisión: `409` con código funcional estable.

Las respuestas de conflicto solo incluyen la representación actual cuando el actor sigue
autorizado dentro del mismo tenant. OpenAPI debe enumerar bodies, enums, formatos, respuestas y
códigos funcionales; no se documentan respuestas más amplias que la materialización real.

## 10. Frontend mínimo

### 10.1 Navegación y pantallas

Se añade una sola entrada **Operación** cuando existe `operation:read`. No se añade dashboard
general ni enlaces a módulos vacíos.

1. **Próximos eventos**: bandeja ordenada por fecha con filtros de periodo, estado, atención y
   responsable. Distingue «En preparación», «Listo», «En ejecución», «Completado» y «Cancelado»
   mediante texto e icono, nunca solo color. Los conteos muestran pendientes, vencidos y bloqueados.
2. **Detalle de preparación**: encabezado con evento, fecha, contacto mínimo, estado y responsable;
   resumen de atención; notas operativas; checklist agrupado en Definiciones, Preparación y Revisión
   final; y una zona de acción contextual para declarar listo, iniciar o completar.

Comercial puede abrir el detalle operativo en modo lectura. Después de confirmar, la vista
comercial puede enlazar inmediatamente a la preparación creada. La cancelación permanece en la
vista comercial, solo está disponible antes de iniciar y el detalle operativo explica el efecto y
congela controles. `completed` y `cancelled` conservan el nombre, pero nunca muestran teléfono.

### 10.2 Jerarquía de interacción

- una sola acción primaria dominante según estado;
- los requisitos que impiden `ready` aparecen junto al botón, con enlaces de foco a los ítems;
- responsable y vencimiento son visibles sin abrir cada ítem;
- bloqueos muestran motivo textual;
- una actualización concurrente no se sobreescribe: se presenta «La información cambió», se carga
  la versión actual y se conserva el texto no enviado cuando sea seguro copiarlo;
- cambiar un ítem que invalida `ready` advierte que el evento volverá a «En preparación»;
- `in_progress`, `completed` y `cancelled` presentan el checklist como historial de solo lectura.

### 10.3 Estados de interfaz

- **Vacío real:** «No hay eventos confirmados en este periodo», con acción para cambiar fechas; no
  ofrece crear reservas desde operaciones.
- **Vacío filtrado:** explica que los filtros no coinciden y permite limpiarlos.
- **Carga:** conserva encabezados y usa esqueletos con nombre accesible; evita saltos de layout.
- **Error recuperable:** mensaje contextual y botón Reintentar.
- **403:** explica falta de acceso sin revelar datos.
- **404:** mensaje genérico y retorno a la bandeja.
- **409:** presenta el conflicto funcional, no un error técnico genérico.
- **Cancelación concurrente antes de ejecutar:** reemplaza el formulario por el estado cancelado y
  conserva cualquier texto local no guardado para copiar, sin reintentar automáticamente la
  escritura.
- **Cancelación rechazada:** si ejecución ya comenzó o terminó, la vista comercial explica el
  conflicto `409` y mantiene intactos ambos estados; no ofrece representar una interrupción.

### 10.4 Responsive y accesibilidad

- escritorio puede usar tabla/lista de densidad moderada; móvil usa cards y nunca depende de scroll
  horizontal;
- targets táctiles de al menos 44 px, contenido legible a 320 px y acciones críticas no escondidas
  tras hover;
- jerarquía de headings, landmarks y listas semánticas;
- labels persistentes; placeholder solo como ejemplo;
- foco visible, orden lógico, retorno de foco al cerrar diálogos y operación completa por teclado;
- reordenar usa botones «Subir/Bajar» además de cualquier interacción de puntero;
- cambios de estado y errores se anuncian mediante región `aria-live` apropiada;
- botones incluyen verbo y objeto; badges incluyen texto;
- iconos decorativos se ocultan a tecnologías de asistencia y el color solo refuerza información;
- confirmaciones de listo, inicio y completado describen el efecto antes de aceptar.

La dirección visual oficial sigue gobernando color, tipografía y componentes; claridad y jerarquía
prevalecen sobre decoración.

## 11. Integración exacta con comercial

### 11.1 Confirmación y creación automática

El endpoint comercial de confirmación delega en un coordinador explícito. Dentro del mismo
`authorized_tenant_scope(reservation:confirm)` y `transaction.atomic()`:

1. comercial evalúa vencimientos, bloquea la reserva y valida toda la evidencia de confirmación de
   5.1;
2. si ya está confirmada, el coordinador exige exactamente una preparación, siete claves base y una
   sola transición `initialized`, y responde idempotentemente;
3. en la primera confirmación, comercial lleva la reserva a `confirmed`;
4. operations crea `EventPreparation` en `preparing`, los siete `PreparationItem` y
   `PreparationTransition(cause=initialized)` con la membresía que confirmó;
5. el coordinador materializa la respuesta después de verificar el agregado completo y confirma la
   transacción.

Si cualquier escritura o verificación falla, todo hace rollback y la reserva conserva su estado
anterior. No hay señal Django, polling, outbox ni consistencia eventual.

La bandeja operativa consulta exclusivamente `EventPreparation` y su proyección comercial dentro
de `authorized_tenant_scope(operation:read)`. Toda reserva que alcanzó `confirmed` ya tiene el
agregado. Provisionales, expiradas y canceladas sin confirmación previa no pertenecen a operations.

### 11.2 Cancelación

El comando comercial existente conserva propiedad y capacidad, pero delega la coordinación cuando
la reserva ya fue confirmada. En la misma transacción:

1. el coordinador bloquea `Reservation` y su única `EventPreparation`;
2. si ambas ya están `cancelled`, cualquier replay devuelve el resultado actual sin cambiar la
   razón original, la revisión ni repetir transición, preservando la idempotencia vigente de 5.1;
3. `preparing` o `ready` permiten continuar;
4. commercial cambia la reserva a `cancelled` con su evidencia actual;
5. operations cambia la preparación a `cancelled`, incrementa revisión y agrega
   `commercial_cancellation` con actor y fecha comerciales;
6. si la preparación está `in_progress`, devuelve `409 operation_already_started`; si está
   `completed`, devuelve `409 operation_already_completed`; en ambos casos no cambia ninguna fila;
7. cualquier fallo revierte ambas mutaciones.

La cancelación de una reserva provisional mantiene el contrato de 5.1 y no involucra operations
porque nunca tuvo preparación. La razón de una cancelación confirmada no se copia: el detalle
autorizado la lee de la reserva. Una reserva cancelada permanece terminal; 5.2 no permite
reactivarla. Interrupciones durante la ejecución y correcciones posteriores permanecen fuera.

### 11.3 Defensa transversal pendiente

La orquestación anterior es la ruta funcional recomendada. Un trigger sobre
`commercial_reservation` para proteger confirmación/cancelación por SQL directo o bulk es una
alternativa complementaria pendiente de ADR. La especificación no decide todavía su forma, orden
de disparo ni migración, y no lo presenta como sustituto de los servicios, la autorización o los
bloqueos explícitos.

### 11.4 Propiedad de datos

| `claridez.commercial`                          | `claridez.operations`                            |
| ---------------------------------------------- | ------------------------------------------------ |
| Persona y contacto maestro                     | Responsable operativo principal                  |
| Solicitud y notas comerciales                  | Notas operativas propias                         |
| Cotización, versiones, líneas y dinero         | Baseline versionada e ítems del evento           |
| Reserva, horario, zona y estado comercial      | Estado de preparación y ejecución                |
| Confirmación, anticipo/excepción y cancelación | Bloqueos, vencimientos y transiciones operativas |
| Snapshots de oferta y evento aceptado          | Referencias a esos snapshots, sin duplicarlos    |

## 12. Exclusiones obligatorias

Quedan expresamente fuera de 5.2:

- pagos, cuentas por cobrar, costos, rentabilidad, contabilidad y facturación;
- proveedores, compras, inventario y personal externo;
- contratos;
- archivos y evidencias adjuntas;
- montaje y desmontaje como ventanas de agenda;
- múltiples espacios;
- reprogramación o reactivación;
- portal público, WhatsApp y correo comercial;
- notificaciones asíncronas, colas, workers y cron obligatorio;
- control de asistencia y encuestas;
- interrupciones durante la ejecución y correcciones administrativas posteriores;
- tareas posteriores al evento.

Tampoco se incluyen plantillas configurables por organización, dependencias entre ítems, subtareas,
recurrencia, prioridades, porcentajes, diagramas, dashboard general ni gestor genérico de proyectos.

## 13. Estrategia de pruebas para una futura implementación

### 13.1 Dominio y servicios

- confirmación crea atómicamente preparación, siete ítems y `initialized`;
- fallo en cualquier creación revierte también el estado y evidencia de confirmación comercial;
- confirmación repetida no duplica preparación, baseline ni transición y detecta cualquier agregado
  parcial como conflicto de integridad;
- catálogo y todas las entradas/salidas permitidas y prohibidas de estados;
- evidencia temporal/actor consistente en listo, inicio, completado y cancelación;
- cinco estados de ítem, notas obligatorias, revisión final no omitible y cambios que reabren;
- baseline completa, orden, fechas relativas y creación de ítems libres;
- `ready` rechazado por responsable ausente/inactivo, baseline incompleta, obligatorio pendiente,
  final no completado o cualquier bloqueo;
- ítem opcional pendiente no impide `ready`; obligatorio `not_applicable` justificado sí se resuelve;
- cancelación admitida solo desde `preparing` y `ready`, y rechazada sin mutaciones desde
  `in_progress` y `completed`;
- idempotencia sin cambios de revisiones ni `updated_at`;
- ausencia de edición después de iniciar y ausencia total de borrado soportado.

### 13.2 Concurrencia real en PostgreSQL

- dos actualizaciones del mismo ítem: un ganador y un `stale_revision`;
- dos ítems distintos: ambos persisten y la revisión agregada aumenta dos veces;
- dos asignaciones: un ganador;
- dos confirmaciones concurrentes: exactamente una reserva confirmada, una preparación, siete ítems
  base y una transición `initialized`;
- dos `ready`: una transición y dos respuestas coherentes;
- `ready` concurrente con cambio obligatorio en ambos órdenes de bloqueo;
- cancelación comercial concurrente con edición, asignación y `ready` conserva atomicidad;
- carrera cancelación/`start`: cancela si gana el bloqueo o devuelve `409` si ejecución empieza;
- cancelación durante `in_progress` o después de `complete` siempre se rechaza;
- rollback inyectado después de cada bloqueo sin estado parcial;
- ausencia de deadlock y concurrencia independiente entre organizaciones.

### 13.3 Autorización y privacidad

- matriz exhaustiva de las tres capacidades para los cinco roles;
- `owner`, `administrator` y `operations` gestionan/ejecutan; `commercial` solo lee; `finance` no
  obtiene datos;
- un actor `finance` con la capacidad comercial vigente puede confirmar y disparar la creación
  obligatoria, pero sigue sin poder listar, consultar o mutar el agregado operativo;
- denegación de capacidad y rol desconocidos;
- operaciones no puede usar endpoints de persona por poseer `operation:read`;
- listado sin teléfono; detalle `preparing`/`ready`/`in_progress` con teléfono y detalle
  `completed`/`cancelled` sin la clave, conservando nombre;
- ninguna respuesta incluye correo, `person_id`, origen, notas comerciales, cotización, importes,
  descuentos ni anticipo;
- directorio de responsables sin correo y solo con membresías activas elegibles;
- materialización completa dentro de `authorized_tenant_scope`.

### 13.4 Tenancy e integridad PostgreSQL

Con al menos dos organizaciones:

- RLS cierra lecturas, inserciones y actualizaciones cruzadas por ORM y SQL;
- `WITH CHECK` impide mover filas de tenant;
- FK compuestas rechazan reserva, preparación, ítem, transición o membresía de otro tenant;
- FK/PK impiden preparaciones duplicadas y cruces tenant; la confirmación soportada siempre crea el
  agregado completo;
- `QuerySet.update`, `bulk_update` y SQL directo no saltan estados, evidencia, readiness ni
  congelación de ítems;
- según la alternativa aprobada en el ADR, SQL directo y bulk de confirmación/cancelación se
  rechazan o completan coherentemente; nunca dejan una confirmada sin preparación, cancelan desde
  `in_progress`/`completed` ni dejan preparación activa después de cancelar;
- mutación de ítems en `ready` sin reapertura previa falla;
- `UPDATE`/`DELETE` de transiciones y todo `DELETE` de ítems falla para la aplicación;
- triggers internos son invoker, tienen `search_path` fijo, no son públicos y los roles no poseen
  `BYPASSRLS` ni tablas; cualquier trigger transversal aprobado debe superar las mismas pruebas.

### 13.5 API y contrato

- flujo HTTP: confirmar → preparación automática visible → asignar → resolver checklist → listo →
  iniciar → completar;
- cancelación correcta en `preparing` y `ready`, y conflictos estables sin mutación en
  `in_progress` y `completed`;
- replay de cancelación devuelve `200` sin cambiar la razón original ni crear otra transición o
  revisión;
- códigos `400/401/403/404/409`, error cross-tenant indistinguible y conflicto con representación
  solo autorizada;
- CSRF rechazado en cada `PATCH` y `POST`; `GET` no muta;
- replays de confirmación, creación de ítem con token, asignación y comandos;
- paginación, orden, filtros, periodo máximo y cálculo de alertas en bordes de fecha;
- OpenAPI generado, validado y probado contra serializers y respuestas reales.

### 13.6 Frontend

- navegación visible por capacidad, nunca como única defensa;
- bandeja de preparaciones con estados, filtros, conteos, vacíos, carga y error;
- detalle, directorio mínimo, edición de ítems, reapertura, bloqueos y acciones por estado;
- conflicto de revisión y cancelación concurrente sin pérdida silenciosa de texto;
- pruebas accesibles por rol, label, heading y texto; foco, teclado, `aria-live` y estados no
  comunicados solo por color;
- revisión real al menos en 1280 × 720, 768 × 1024, 390 × 844 y 320 px de ancho, sin overflow
  horizontal ni controles inaccesibles.

### 13.7 Migraciones y puerta completa

- migración desde cero sobre PostgreSQL 17 crea tablas, FK, checks, triggers internos, RLS y
  privilegios; el trigger transversal solo se incluye si el ADR lo aprueba;
- si el ADR aprueba el trigger transversal, la reversión en base desechable lo elimina antes de las
  tablas operativas y la reaplicación restaura exactamente el contrato;
- reversión/reaplicación con reservas comerciales existentes no altera sus filas; las preparaciones
  solo se prueban con respaldo desechable porque revertir una tabla con datos sería destructivo;
- `makemigrations --check --dry-run` sin cambios pendientes;
- `npm run format:check`, `npm run lint`, `npm run typecheck`, suites dirigidas, `npm test`,
  `npm run build`, `npm run check`, `npm run check:all`, `npm run audit` y `git diff --check` según
  el cierre futuro, distinguiendo resultados locales de CI remota.

## 14. Decisiones, alternativas y deuda

### 14.1 Decisiones recomendadas por esta propuesta

1. Crear `claridez.operations` con `EventPreparation`, `PreparationItem` y
   `PreparationTransition`.
2. Usar uno-a-uno con reserva e identidad pública por `reservation_id`; toda reserva que alcance
   `confirmed` tiene exactamente una preparación.
3. Crear automáticamente preparación, siete ítems y `initialized` mediante orquestación explícita
   en la misma transacción de confirmación.
4. Usar cinco estados persistidos, sin `pending` redundante.
5. Adoptar checklist base más ítems libres, sin plantillas configurables todavía.
6. Crear solo `operation:read`, `operation:manage` y `operation:execute`.
7. Exponer el nombre histórico en todos los estados y el teléfono solo durante `preparing`, `ready`
   e `in_progress`, mediante proyección mínima y sin conceder `person:read`.
8. Calcular alertas al consultar y conservar la zona capturada por la reserva.
9. Combinar servicios transaccionales, revisión optimista, FK compuestas, checks, triggers internos
   y RLS; someter el trigger transversal a ADR.
10. Mantener la cancelación en comercial y reflejarla atómicamente solo desde `preparing` o `ready`,
    sin señales Django.

### 14.2 Alternativas no recomendadas para 5.2

- agregar campos operativos a `commercial.Reservation`;
- varias preparaciones para una reserva sin reprogramación aprobada;
- creación manual, reserva confirmada sin preparación o endpoint operativo para crearla;
- señales Django o sincronización eventual mediante worker;
- usar un trigger PostgreSQL como único orquestador funcional;
- copiar persona, correo, notas comerciales, cotización, importes o anticipo;
- conceder `person:read` a `operations` o acceso operativo a `finance`;
- adoptar los siete nombres de capacidad sugeridos cuando tres expresan la matriz real;
- modelar secciones, hitos, dependencias, subtareas y plantillas como un gestor de proyectos;
- alertas persistidas o estados cambiados por el reloj;
- cancelar desde operaciones, cancelar durante/después de ejecución o reactivar una reserva
  cancelada;
- borrar ítems y perder por qué dejaron de aplicar.

### 14.3 Decisiones que requieren aprobación expresa del propietario

Antes de implementar debe aprobarse, como mínimo:

1. el nuevo módulo, el coordinador de aplicación y sus dependencias públicas;
2. creación automática y atómica como parte de la confirmación comercial;
3. nombres y semántica de los cinco estados;
4. los siete ítems base, su obligatoriedad, `not_applicable` y vencimientos de 7/1 días;
5. las tres capacidades y la matriz de cinco roles;
6. el nombre histórico y el teléfono vivo limitado a `preparing`, `ready` e `in_progress`, sin
   `person:read`;
7. cancelación solo desde `preparing` o `ready`, con rechazo en `in_progress` y `completed`;
8. rutas, payloads, códigos de error y ventana visual de siete días;
9. el alcance de historial mínimo frente a una auditoría de cambios más detallada;
10. el ADR transversal antes de decidir o crear cualquier trigger sobre tablas comerciales.

Ese ADR deberá comparar expresamente:

1. la orquestación transaccional explícita entre servicios como ruta soportada;
2. el trigger PostgreSQL como posible defensa final, nunca como sustituto de autorización y dominio;
3. el resultado de confirmación y cancelación mediante SQL directo, `QuerySet.update` y bulk;
4. la dirección de dependencia entre `commercial`, `operations` y el coordinador de aplicación;
5. el orden de migraciones, la eliminación segura del trigger al revertir y la reaplicación.

La combinación recomendada en esta propuesta es orquestación explícita más defensa PostgreSQL
final, siempre que el ADR demuestre que no duplica reglas de forma divergente y conserva el contexto
tenant. Esta recomendación no está aceptada.

La aprobación de esta especificación no debe inferirse de la creación del archivo.

### 14.4 Riesgos

- hacer atómica la creación operativa significa que un fallo de operations también impide confirmar
  comercialmente; los errores deben ser observables y no dejar estados parciales;
- el posible trigger sobre `commercial_reservation` crea acoplamiento de esquema y duplicación de
  defensas; su conveniencia, orden y reversión siguen pendientes del ADR;
- hasta resolver el ADR, SQL directo y bulk de transiciones comerciales no tienen una defensa final
  seleccionada y no pueden considerarse rutas soportadas;
- el teléfono es dato personal legítimamente útil, pero amplía la exposición frente a 5.1.1 y
  requiere omisión estricta al completar o cancelar;
- una baseline única puede no cubrir todos los tipos de salón; `not_applicable` mitiga sin resolver
  todavía plantillas por organización;
- una interrupción real durante ejecución no puede registrarse como cancelación en 5.2 y requerirá
  un flujo futuro;
- campos de texto operativo pueden recibir datos personales por error y no existe clasificación
  automática;
- el bloqueo del padre para coordinar readiness reduce concurrencia dentro de un mismo evento,
  aunque eventos de organizaciones distintas permanecen independientes;
- el cálculo de alertas en consulta exige índices y límites de rango para no degradar listados.

### 14.5 Deuda deliberadamente diferida

- plantillas configurables por organización y versionado de sus cambios;
- historial de cada edición de ítem, notas y reasignaciones previas;
- reprogramación y relación entre reserva anterior y nueva;
- archivos o evidencia;
- notificaciones y outbox al existir un proceso asíncrono real;
- ventanas de montaje/desmontaje, espacios múltiples e inventario;
- correcciones posteriores al evento y tareas postevento;
- métricas agregadas o dashboard operativo;
- responsabilidades por equipos, personal externo o turnos.

## 15. Criterio propuesto de salida futura

Si el propietario aprueba 5.2, la implementación solo podría declararse terminada cuando el flujo
completo, la matriz, la minimización personal, la concurrencia, SQL/bulk, RLS con dos organizaciones,
CSRF, OpenAPI, frontend responsive/accesible y migraciones desde cero/reversión/reaplicación hayan
sido observados y documentados. Este criterio no declara que ninguna de esas comprobaciones se haya
ejecutado en la fase actual de especificación.
