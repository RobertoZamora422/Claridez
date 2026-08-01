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

- qué eventos confirmados todavía no han iniciado su preparación;
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

| Dato consumido                           | Fuente y semántica                                                                            |
| ---------------------------------------- | --------------------------------------------------------------------------------------------- |
| `reservation_id`                         | Identidad estable de `Reservation`; también identifica el evento operativo.                   |
| `organization_id`                        | Límite tenant de la reserva; nunca se toma del cuerpo enviado por el cliente.                 |
| `status`                                 | Estado vivo de la reserva. Solo `confirmed` habilita inicialización y trabajo activo.         |
| `starts_at`, `ends_at`, `event_timezone` | Snapshot inmutable ya conservado por la reserva y su versión aceptada.                        |
| Tipo, invitados y necesidad general      | Snapshots inmutables de la `QuotationVersion` aceptada.                                       |
| Nombre y teléfono del contacto           | Proyección mínima y viva de la `Person` relacionada, materializada solo por backend.          |
| Cancelación                              | Estado, actor, fecha y razón permanecen en `Reservation`; operaciones solo refleja el cierre. |

La proyección no entregaría correo, origen, notas comerciales, identificador de persona, revisiones
de persona, líneas o totales de cotización, moneda, descuentos, constancia de anticipo ni sus
actores. El puerto de lectura sería una superficie pública estrecha de `claridez.commercial`; no se
autoriza a operaciones a consultar tablas comerciales de forma dispersa.

### 1.3 Desacoplamiento

La dirección ordinaria de dependencia sería `operations → commercial`: operaciones conoce la
identidad y proyección autorizada de una reserva; comercial no conoce modelos ni servicios
operativos. La cancelación se sincroniza mediante una defensa PostgreSQL explícita instalada por
la migración de operaciones, no mediante señales Django, callbacks ocultos ni infraestructura
asíncrona.

Como ese trigger establece una convención transversal y difícil de revertir entre módulos, su
aprobación exigiría un ADR antes de implementar. Esta propuesta describe la opción; no crea ni
acepta ese ADR.

La inicialización se recomienda **explícita**, no automática al confirmar. La reserva confirmada
aparece como `not_initialized` en la bandeja operativa y un actor autorizado inicia su preparación
mediante un `PUT` idempotente. Esto evita que un fallo operativo impida confirmar una venta,
incorpora sin backfill destructivo las reservas confirmadas que ya existan y mantiene a comercial
sin dependencia del nuevo módulo.

Reservas provisionales o vencidas nunca aparecen como candidatas y no admiten preparación. Una
reserva confirmada cuyo intervalo ya terminó tampoco puede inicializarse en 5.2.

## 2. Modelo de dominio propuesto

```text
commercial.Reservation (1) ─── (0..1) operations.EventPreparation
                                      │
                                      ├── (1..n) PreparationItem
                                      └── (1..n) PreparationTransition
```

### 2.1 `EventPreparation`

Se recomienda una relación **uno a uno** con `Reservation`. Una reserva representa un único
compromiso confirmado y 5.2 excluye reprogramación; varias preparaciones para la misma reserva
crearían versiones operativas sin una causa de dominio aprobada.

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
| `created_at`, `updated_at`                   | Instantes conscientes; `updated_at` solo cambia ante una mutación efectiva.                                                |

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
| `from_status`, `to_status`                | Estado anterior nullable en inicialización y estado resultante.                                                                    |
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
reserva confirmada sin preparación
              │ inicializar
              ▼
          preparing ◄──────── ready
              │  declarar listo  │ cambio que invalida la declaración
              └───────────────►───┘
                                  │ iniciar
                                  ▼
                             in_progress
                                  │ completar
                                  ▼
                              completed

commercial cancellation: preparing | ready | in_progress | completed → cancelled
```

`not_initialized` es una condición de la bandeja, no un estado almacenado. No se adopta `pending`
para la preparación porque duplicaría la existencia de ítems pendientes: desde que se inicializa,
el trabajo ya está `preparing`.

| Estado        | Significado                                                                             |
| ------------- | --------------------------------------------------------------------------------------- |
| `preparing`   | Existe trabajo operativo editable; aún no hay una declaración de listo vigente.         |
| `ready`       | Un actor autorizado verificó responsable, checklist obligatorio y ausencia de bloqueos. |
| `in_progress` | La ejecución del evento comenzó por comando explícito.                                  |
| `completed`   | La ejecución terminó; no implica pagos, cierre financiero ni tareas posteriores.        |
| `cancelled`   | Comercial canceló la reserva; todo trabajo operativo queda congelado.                   |

El tiempo por sí solo no cambia estados. Llegar a la hora del evento no inicia ni completa nada.

### 3.2 Transiciones y comandos

| Entrada                     | Transición      | Actor y capacidad                                                         | Condiciones previas                                                                                                                                                           | Efectos e idempotencia                                                                                                                                                 |
| --------------------------- | --------------- | ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Sin preparación             | `→ preparing`   | Actor con `operation:manage`                                              | Reserva del mismo tenant en `confirmed`; evento no terminado.                                                                                                                 | Crea preparación, responsable opcional, siete ítems base y transición en una transacción. Repetir el `PUT` devuelve la existente sin duplicar ni incrementar revisión. |
| `preparing`                 | `→ ready`       | Actor con `operation:manage`                                              | Revisión vigente, reserva confirmada, responsable principal activo y elegible, baseline íntegra, todos los obligatorios resueltos, revisión final completada y cero bloqueos. | Registra actor/fecha y transición; reintento en `ready` es `200` sin nueva transición.                                                                                 |
| `ready`                     | `→ preparing`   | Mismo actor que efectúa un cambio con `operation:manage`                  | Una mutación autorizada invalida la declaración: reabre un obligatorio, bloquea un ítem, añade un obligatorio pendiente o cambia el contenido ya completado.                  | Ocurre antes del cambio, limpia evidencia vigente de listo, incrementa revisión y registra `checklist_reopened`. No hay comando de reapertura separado.                |
| `ready`                     | `→ in_progress` | Actor con `operation:execute`                                             | Revisión vigente y reserva todavía confirmada.                                                                                                                                | Registra inicio. No impone tolerancia horaria inventada: el actor declara el hecho. Repetir devuelve el estado actual.                                                 |
| `in_progress`               | `→ completed`   | Actor con `operation:execute`                                             | Revisión vigente y reserva todavía confirmada.                                                                                                                                | Registra finalización. Repetir devuelve el estado actual.                                                                                                              |
| Cualquier estado persistido | `→ cancelled`   | Actor de comercial con `reservation:cancel`; no existe `operation:cancel` | La cancelación comercial satisface el contrato de 5.1.                                                                                                                        | El trigger sincroniza estado y transición en la misma transacción. Conserva `started_at`/`completed_at` si existían. Repetir la cancelación no duplica transición.     |

Una cancelación posterior a `completed` conserva la evidencia de que la ejecución había terminado y
la interfaz debe decir «Cancelada después de completarse», no fingir que el evento nunca ocurrió.
Esta regla respeta que la reserva es la fuente comercial vigente y evita introducir en 5.2 un
flujo de corrección posterior.

### 3.3 Transiciones prohibidas

- `preparing → in_progress` o `completed`: no se omite la declaración de listo.
- `ready → completed`: siempre debe registrarse el inicio.
- `in_progress → preparing` o `ready`: no se retrocede una ejecución observada.
- cualquier comando operativo desde `cancelled`: estado terminal.
- cualquier comando operativo desde `completed`: terminal para operaciones; solo puede superponerse
  la cancelación comercial existente.
- edición de checklist en `in_progress`, `completed` o `cancelled`.
- reactivación de una reserva cancelada. La reserva de 5.1 ya es terminal; una futura
  reprogramación deberá crear su propio contrato y, previsiblemente, una nueva reserva y
  preparación. No se define en 5.2.

## 4. Checklist operativo

### 4.1 Combinación mínima

Se recomienda una combinación gradual:

1. checklist base de producto, versionado y sembrado al inicializar;
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
del día local de inicialización: `max(fecha de inicialización, fecha del evento - desplazamiento)`.
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
- `operation:manage`: inicialización, notas, responsable principal, ítems y declaración de listo;
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
  acceso operativo.

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

| Dato                                      |          Listado          | Detalle | Justificación                                            |
| ----------------------------------------- | :-----------------------: | :-----: | -------------------------------------------------------- |
| Nombre del contacto                       |            Sí             |   Sí    | Identificar el evento y recibir al contacto.             |
| Teléfono E.164 vivo                       |            No             |   Sí    | Coordinar ingreso o resolver una incidencia inmediata.   |
| Correo                                    |            No             |   No    | No es necesario para preparación en 5.2.                 |
| Tipo, horario e invitados del evento      |            Sí             |   Sí    | Núcleo de planificación; proviene del snapshot aceptado. |
| Necesidad general                         | Resumen truncado opcional |   Sí    | Requerimiento operativo confirmado.                      |
| Notas comerciales                         |            No             |   No    | Pueden incluir negociación o datos no necesarios.        |
| Cotización, líneas, importes y descuentos |            No             |   No    | Propiedad comercial y fuera del propósito operativo.     |
| Anticipo, referencia o excepción          |            No             |   No    | Información financiera/comercial no necesaria.           |
| `person_id`, origen y revisiones          |            No             |   No    | Evita convertir la vista operativa en acceso a personas. |

El nombre y teléfono se obtienen de la persona viva mediante el puerto de proyección comercial para
que una corrección de contacto sea útil; no se copian a tablas operativas. Los detalles del evento
provienen del snapshot aceptado e inmutable para que una edición comercial posterior no cambie
silenciosamente lo que se preparó.

El backend aplica esta forma antes de salir de `authorized_tenant_scope`. Ni parámetros del cliente
ni el frontend deciden campos. Las pruebas deben buscar explícitamente correo, notas, importes y
evidencia de anticipo en todas las respuestas, incluidas estructuras anidadas y errores.

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

| Indicador                 | Regla exacta                                                                                                                                  |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Ítem pendiente            | `status` es `pending` o `in_progress`.                                                                                                        |
| Ítem vencido              | `due_on < today` y estado no es `completed` ni `not_applicable`.                                                                              |
| Con bloqueo               | Existe al menos un ítem `blocked`.                                                                                                            |
| Preparación atrasada      | No está inicializada y `now >= starts_at`, o está `preparing` y se cumple `(existe un obligatorio vencido sin resolver OR now >= starts_at)`. |
| Evento próximo            | `now < starts_at` y su fecha local está entre `today` y `today + 7 días`, inclusivos.                                                         |
| Evento listo              | Estado persistido `ready`.                                                                                                                    |
| Sin iniciar preparación   | Reserva confirmada, no terminada y sin `EventPreparation`.                                                                                    |
| Responsable no disponible | La membresía asignada ya no está activa o dejó de ser elegible.                                                                               |

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

La cancelación comercial ya bloquea `Reservation`; el trigger toma después la preparación. Esta
regla evita el ciclo inverso. Asignaciones validan la membresía tenant-aware dentro de la misma
transacción, sin convertirla en pivote de bloqueo del agregado.

Casos concurrentes:

- mismo ítem: una revisión gana y la otra recibe `409`;
- ítems distintos: ambos cambios pueden completar y cada uno incrementa la revisión agregada;
- dos asignaciones: el bloqueo y revisión de preparación dejan un ganador;
- dos declaraciones de listo: la primera transiciona; la segunda observa `ready` y responde
  idempotentemente sin otra transición;
- ítem contra `ready`: si el ítem gana primero, `ready` ve revisión obsoleta; si `ready` gana, un
  cambio invalidante reabre primero la preparación;
- cancelación contra edición: quien obtiene `Reservation` primero termina; si cancela primero, la
  edición devuelve conflicto; si la edición termina primero, la cancelación la conserva y cierra
  después todo el agregado.

### 8.3 Defensas por capa

| Invariante                             | Defensa propuesta                                                                                                                                                             |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Una preparación por reserva            | PK/FK uno-a-uno.                                                                                                                                                              |
| Pertenencia al mismo tenant            | FK compuesta `(organization_id, reservation_id)` y equivalentes para preparación, ítems, transiciones y membresías.                                                           |
| Coherencia entre reserva y preparación | Trigger inmediato `BEFORE INSERT/UPDATE` exige reserva `confirmed` para todo estado operativo distinto de `cancelled`, y reserva `cancelled` para la preparación `cancelled`. |
| Cancelación coherente                  | Trigger explícito `AFTER UPDATE OF status` en reserva pasa la preparación a `cancelled`, incrementa revisión y registra transición en la misma transacción.                   |
| Estado y marcas coherentes             | `CHECK` para catálogo, revisión positiva y combinaciones de `ready_at`, `started_at`, `completed_at`; trigger de transiciones para orden.                                     |
| Listo realmente válido                 | Trigger inmediato al entrar en `ready`, bajo bloqueo de preparación, comprueba responsable, baseline, obligatorios, revisión final y bloqueos.                                |
| No invalidar listo por SQL directo     | Trigger de ítems rechaza mutaciones mientras el padre esté `ready` salvo que la transacción ya lo haya reabierto a `preparing`.                                               |
| Ítems terminales/evidencia             | `CHECK` de estado, `status_note` y evidencia de completado; trigger impide edición tras inicio y todo `DELETE`.                                                               |
| Historial                              | Transiciones append-only; trigger valida estado/revisión actuales y rechaza inserciones incoherentes, `UPDATE` y `DELETE`.                                                    |
| Orden e idempotencia                   | `UNIQUE` por preparación para posición, `baseline_key` y `client_request_id`.                                                                                                 |

Los triggers serían funciones invoker con `search_path` fijo, sin `SECURITY DEFINER`, con ejecución
revocada a `PUBLIC`, siguiendo las defensas de 5.1. No se usarían triggers diferidos porque el GUC
tenant es local a `authorized_tenant_scope` y debe seguir siendo confiable durante la comprobación
inmediata.

Todas las tablas operativas tendrían RLS `ENABLE` + `FORCE`, políticas `USING` y `WITH CHECK`
basadas en `claridez_current_organization_id()`. `claridez_app` recibiría solo `SELECT`, `INSERT` y
`UPDATE` necesarios; no `DELETE`, `TRUNCATE`, ownership ni `BYPASSRLS`. El migrador conservaría DDL
y el test runner los privilegios de integración definidos por la plataforma.

ORM, `QuerySet.update`, `bulk_create`, `bulk_update` y SQL directo no se consideran rutas de dominio,
pero tampoco pueden eludir FK, checks, triggers o RLS. Vistas, serializers y tareas futuras no
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
  "preparation": null
}
```

Cuando está inicializada, `preparation` incorpora estado, revisión, responsable mínimo, notas,
baseline, marcas, flags/conteos y los ítems ordenados. El listado omite teléfono, notas extensas y
detalle de ítems; expone conteos y nombre de contacto.

El listado acepta `from`, `to`, `status`, `attention`, `responsible_membership_id`, `cursor` y
`page_size` (1–100). Sin fechas usa desde el inicio del día local actual hasta el final del día 30,
e incluye además toda preparación no terminal cuyo evento quedó antes del rango para que el trabajo
abierto no desaparezca. `completed` y `cancelled` se excluyen por defecto y aparecen al pedir esos
estados. El rango explícito máximo es 366 días. Orden estable: `starts_at`, `reservation_id`.

### 9.2 Endpoints

| Método y ruta relativa                                      | Capacidad             | Entrada                                                                                                                                  | Respuesta y códigos                                                                                            | Errores e idempotencia                                                                                                                                                                                           |
| ----------------------------------------------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET operations/capabilities/`                              | `organization:access` | Sin cuerpo.                                                                                                                              | `200` con las capacidades operativas efectivas.                                                                | `401`, `404`; seguro e idempotente. Permite que `finance` reciba lista vacía sin obtener datos operativos.                                                                                                       |
| `GET operations/assignees/`                                 | `operation:manage`    | Sin cuerpo.                                                                                                                              | `200` con membresías activas elegibles: id, nombre y rol.                                                      | `401`, `403`, `404`; seguro e idempotente; nunca entrega correo.                                                                                                                                                 |
| `GET operations/events/`                                    | `operation:read`      | Filtros y cursor descritos.                                                                                                              | `200` paginado; incluye reservas confirmadas no inicializadas y preparaciones.                                 | `400 invalid_filter`, `401`, `403`, `404`; seguro e idempotente.                                                                                                                                                 |
| `GET operations/events/{reservation_id}/`                   | `operation:read`      | Sin cuerpo.                                                                                                                              | `200`; una confirmada elegible puede devolver `preparation:null`; una inicializada cancelada conserva detalle. | `401`, `403`, `404 resource_unavailable`; seguro e idempotente.                                                                                                                                                  |
| `PUT operations/events/{reservation_id}/preparation/`       | `operation:manage`    | `{responsible_membership_id?: uuid, operational_notes?: string}`.                                                                        | `201` al crear; replay idéntico `200`.                                                                         | `400`, `404`, `409 reservation_not_confirmed`, `409 event_already_ended`, `409 responsible_unavailable`, `409 idempotency_conflict` si ya existe con otros valores iniciales; no duplica baseline ni transición. |
| `PATCH operations/events/{reservation_id}/preparation/`     | `operation:manage`    | `{revision, operational_notes}`; `operational_notes` puede ser texto vacío para limpiar.                                                 | `200` con detalle.                                                                                             | `400`, `404`, `409 stale_revision`, `409 invalid_transition`; mismo valor normalizado es idempotente.                                                                                                            |
| `POST operations/events/{reservation_id}/assign/`           | `operation:manage`    | `{revision, responsible_membership_id}`.                                                                                                 | `200` con detalle.                                                                                             | `400`, `404` para membresía inexistente o ajena, `409 stale_revision`, `409 responsible_unavailable`, `409 invalid_transition`; repetir misma asignación no incrementa.                                          |
| `POST operations/events/{reservation_id}/items/`            | `operation:manage`    | `{client_request_id, title, section, is_required, due_on?, responsible_membership_id?, notes?, place_before_item_id?}`.                  | `201`; replay idéntico `200`.                                                                                  | `400`, `404`, `409 idempotency_conflict`, `409 invalid_transition`; token igual con payload distinto se rechaza.                                                                                                 |
| `PATCH operations/events/{reservation_id}/items/{item_id}/` | `operation:manage`    | `{revision, title?, section?, is_required?, due_on?, responsible_membership_id?, notes?, status?, status_note?, place_before_item_id?}`. | `200` con ítem y resumen actualizado.                                                                          | `400`, `404`, `409 stale_revision`, `409 invalid_item_transition`, `409 invalid_transition`; no-op normalizado es idempotente.                                                                                   |
| `POST operations/events/{reservation_id}/ready/`            | `operation:manage`    | `{revision}`.                                                                                                                            | `200` con preparación `ready`.                                                                                 | `404`, `409 stale_revision`, `409 responsible_required`, `409 baseline_incomplete`, `409 required_items_pending`, `409 blocked_items`, `409 reservation_cancelled`; repetir en `ready` es idempotente.           |
| `POST operations/events/{reservation_id}/start/`            | `operation:execute`   | `{revision}`.                                                                                                                            | `200` con `in_progress`.                                                                                       | `404`, `409 stale_revision`, `409 invalid_transition`, `409 reservation_cancelled`; repetir en `in_progress` es idempotente.                                                                                     |
| `POST operations/events/{reservation_id}/complete/`         | `operation:execute`   | `{revision}`.                                                                                                                            | `200` con `completed`.                                                                                         | `404`, `409 stale_revision`, `409 invalid_transition`, `409 reservation_cancelled`; repetir en `completed` es idempotente.                                                                                       |
| `POST reservations/{reservation_id}/cancel/` existente      | `reservation:cancel`  | Contrato de 5.1: `{reason}`.                                                                                                             | `200` comercial; al confirmar la transacción, el detalle operativo ya está `cancelled`.                        | Conserva idempotencia de 5.1. No se añade endpoint operativo de cancelación.                                                                                                                                     |

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
   responsable. Distingue «Preparación sin iniciar», «En preparación», «Listo», «En ejecución»,
   «Completado» y «Cancelado» mediante texto e icono, nunca solo color. Los conteos muestran
   pendientes, vencidos y bloqueados. Un candidato ofrece «Iniciar preparación» solo a quien puede.
2. **Detalle de preparación**: encabezado con evento, fecha, contacto mínimo, estado y responsable;
   resumen de atención; notas operativas; checklist agrupado en Definiciones, Preparación y Revisión
   final; y una zona de acción contextual para declarar listo, iniciar o completar.

Comercial puede abrir el detalle operativo en modo lectura. La cancelación permanece en la vista
comercial; el detalle operativo explica el efecto y congela controles.

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
- **Cancelación concurrente:** reemplaza el formulario por el estado cancelado y conserva cualquier
  texto local no guardado para copiar, sin reintentar automáticamente la escritura.

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

### 11.1 Detección e inicialización

La bandeja operativa ejecuta, dentro de `authorized_tenant_scope(operation:read)`, una proyección de
reservas:

- candidatas: `Reservation.status=confirmed`, `ends_at > now` y sin preparación;
- inicializadas: preparación existente, incluida su historia terminal cuando los filtros la pidan;
- provisionales y expiradas: excluidas;
- canceladas sin preparación previa: excluidas porque nunca hubo trabajo operativo;
- canceladas con preparación: visibles como historia `cancelled`.

No hay polling especial, evento de dominio persistido, outbox ni señal. La siguiente consulta ve la
confirmación ya comprometida. El actor decide cuándo inicializar mediante `PUT`; inicializar y
sembrar baseline es una única transacción.

### 11.2 Cancelación

El comando comercial existente conserva propiedad y capacidad. En la misma transacción:

1. comercial bloquea y cambia `Reservation` a `cancelled` con su evidencia actual;
2. el trigger inmediato de integración localiza la preparación por FK tenant-aware;
3. si existe y aún no está cancelada, la cambia a `cancelled`, incrementa revisión y agrega una
   transición con actor y fecha comerciales;
4. cualquier escritura operativa posterior falla porque la reserva ya no está confirmada y el
   agregado está terminal;
5. si cualquier paso falla, se revierte también la cancelación comercial.

La razón no se copia: el detalle autorizado la lee de la reserva. `completed_at` o `started_at` no
se borran. Una reserva ya cancelada permanece terminal; 5.2 no permite reactivarla ni crear otra
preparación para ella.

### 11.3 Propiedad de datos

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
- tareas posteriores al evento.

Tampoco se incluyen plantillas configurables por organización, dependencias entre ítems, subtareas,
recurrencia, prioridades, porcentajes, diagramas, dashboard general ni gestor genérico de proyectos.

## 13. Estrategia de pruebas para una futura implementación

### 13.1 Dominio y servicios

- creación solo desde reserva confirmada y no terminada;
- `PUT` repetido no duplica preparación, baseline ni transición;
- catálogo y todas las entradas/salidas permitidas y prohibidas de estados;
- evidencia temporal/actor consistente en listo, inicio, completado y cancelación;
- cinco estados de ítem, notas obligatorias, revisión final no omitible y cambios que reabren;
- baseline completa, orden, fechas relativas y creación de ítems libres;
- `ready` rechazado por responsable ausente/inactivo, baseline incompleta, obligatorio pendiente,
  final no completado o cualquier bloqueo;
- ítem opcional pendiente no impide `ready`; obligatorio `not_applicable` justificado sí se resuelve;
- idempotencia sin cambios de revisiones ni `updated_at`;
- ausencia de edición después de iniciar y ausencia total de borrado soportado.

### 13.2 Concurrencia real en PostgreSQL

- dos actualizaciones del mismo ítem: un ganador y un `stale_revision`;
- dos ítems distintos: ambos persisten y la revisión agregada aumenta dos veces;
- dos asignaciones: un ganador;
- dos `ready`: una transición y dos respuestas coherentes;
- `ready` concurrente con cambio obligatorio en ambos órdenes de bloqueo;
- cancelación comercial concurrente con edición, asignación, `ready`, `start` y `complete`;
- rollback inyectado después de cada bloqueo sin estado parcial;
- ausencia de deadlock y concurrencia independiente entre organizaciones.

### 13.3 Autorización y privacidad

- matriz exhaustiva de las tres capacidades para los cinco roles;
- `owner`, `administrator` y `operations` gestionan/ejecutan; `commercial` solo lee; `finance` no
  obtiene datos;
- denegación de capacidad y rol desconocidos;
- operaciones no puede usar endpoints de persona por poseer `operation:read`;
- listado sin teléfono; detalle con nombre/teléfono y sin correo, `person_id`, origen, notas
  comerciales, cotización, importes ni anticipo;
- directorio de responsables sin correo y solo con membresías activas elegibles;
- materialización completa dentro de `authorized_tenant_scope`.

### 13.4 Tenancy e integridad PostgreSQL

Con al menos dos organizaciones:

- RLS cierra lecturas, inserciones y actualizaciones cruzadas por ORM y SQL;
- `WITH CHECK` impide mover filas de tenant;
- FK compuestas rechazan reserva, preparación, ítem, transición o membresía de otro tenant;
- inserción de preparación para provisional, expirada o cancelada falla por SQL directo y
  `bulk_create`;
- `QuerySet.update`, `bulk_update` y SQL directo no saltan estados, evidencia, readiness ni
  congelación de ítems;
- SQL directo que cancela con evidencia comercial válida sincroniza preparación;
- SQL directo que intenta dejar preparación activa tras cancelación falla;
- mutación de ítems en `ready` sin reapertura previa falla;
- `UPDATE`/`DELETE` de transiciones y todo `DELETE` de ítems falla para la aplicación;
- funciones trigger son invoker, tienen `search_path` fijo, no son públicas y los roles no poseen
  `BYPASSRLS` ni tablas.

### 13.5 API y contrato

- flujo HTTP: confirmada visible → inicializar → asignar → resolver checklist → listo → iniciar →
  completar;
- flujo alterno de cancelación antes y después de inicializar, durante preparación, listo,
  ejecución y después de completar;
- códigos `400/401/403/404/409`, error cross-tenant indistinguible y conflicto con representación
  solo autorizada;
- CSRF rechazado en cada `PUT`, `PATCH` y `POST`; `GET` no muta;
- replays de inicialización, creación con token, asignación y comandos;
- paginación, orden, filtros, periodo máximo y cálculo de alertas en bordes de fecha;
- OpenAPI generado, validado y probado contra serializers y respuestas reales.

### 13.6 Frontend

- navegación visible por capacidad, nunca como única defensa;
- bandeja con candidato sin iniciar, estados, filtros, conteos, vacíos, carga y error;
- detalle, directorio mínimo, edición de ítems, reapertura, bloqueos y acciones por estado;
- conflicto de revisión y cancelación concurrente sin pérdida silenciosa de texto;
- pruebas accesibles por rol, label, heading y texto; foco, teclado, `aria-live` y estados no
  comunicados solo por color;
- revisión real al menos en 1280 × 720, 768 × 1024, 390 × 844 y 320 px de ancho, sin overflow
  horizontal ni controles inaccesibles.

### 13.7 Migraciones y puerta completa

- migración desde cero sobre PostgreSQL 17 crea tablas, FK, checks, triggers, RLS y privilegios;
- reversión en base desechable elimina primero triggers sobre comercial y después tablas
  operativas; reaplicación restaura exactamente el contrato;
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
2. Usar uno-a-uno con reserva e identidad pública por `reservation_id`.
3. Inicializar explícitamente desde una reserva confirmada y sembrar baseline versionada.
4. Usar cinco estados persistidos, sin `pending` redundante.
5. Adoptar checklist base más ítems libres, sin plantillas configurables todavía.
6. Crear solo `operation:read`, `operation:manage` y `operation:execute`.
7. Exponer nombre y teléfono mediante proyección mínima sin conceder `person:read`.
8. Calcular alertas al consultar y conservar la zona capturada por la reserva.
9. Combinar servicios transaccionales, revisión optimista, FK compuestas, checks, triggers y RLS.
10. Mantener la cancelación en comercial y reflejarla atómicamente sin señales Django.

### 14.2 Alternativas no recomendadas para 5.2

- agregar campos operativos a `commercial.Reservation`;
- varias preparaciones para una reserva sin reprogramación aprobada;
- creación automática al confirmar, que acoplaría disponibilidad operativa con cierre comercial;
- señales Django o sincronización eventual mediante worker;
- copiar persona, correo, notas comerciales, cotización, importes o anticipo;
- conceder `person:read` a `operations` o acceso operativo a `finance`;
- adoptar los siete nombres de capacidad sugeridos cuando tres expresan la matriz real;
- modelar secciones, hitos, dependencias, subtareas y plantillas como un gestor de proyectos;
- alertas persistidas o estados cambiados por el reloj;
- cancelar desde operaciones o reactivar una reserva cancelada;
- borrar ítems y perder por qué dejaron de aplicar.

### 14.3 Decisiones que requieren aprobación expresa del propietario

Antes de implementar debe aprobarse, como mínimo:

1. el nuevo módulo y su dependencia unidireccional de comercial;
2. inicialización explícita frente a automática;
3. nombres y semántica de los cinco estados;
4. los siete ítems base, su obligatoriedad, `not_applicable` y vencimientos de 7/1 días;
5. las tres capacidades y la matriz de cinco roles;
6. la exposición operacional de nombre y teléfono vivo sin `person:read`;
7. la regla de cancelación incluso después de iniciar o completar, conservando evidencia previa;
8. el trigger de sincronización instalado sobre la tabla comercial y el ADR requerido por su
   impacto transversal;
9. rutas, payloads, códigos de error y ventana visual de siete días;
10. el alcance de historial mínimo frente a una auditoría de cambios más detallada.

La aprobación de esta especificación no debe inferirse de la creación del archivo.

### 14.4 Riesgos

- el trigger sobre `commercial_reservation` crea acoplamiento de esquema que exige orden de
  migración, reversión y pruebas cuidadosas;
- el teléfono es dato personal legítimamente útil, pero amplía la exposición frente a 5.1.1 y
  requiere pruebas negativas estrictas;
- una baseline única puede no cubrir todos los tipos de salón; `not_applicable` mitiga sin resolver
  todavía plantillas por organización;
- la inicialización explícita puede omitirse si la bandeja no destaca claramente candidatos;
- la cancelación posterior a completar es fiel al estado comercial actual, pero necesita copy muy
  claro para no negar que la ejecución ocurrió;
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
