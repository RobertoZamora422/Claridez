# ADR 0016 — Propiedad de scheduling e integridad temporal P8

- **Estado:** Propuesto
- **Fecha:** 2026-08-06
- **Reemplaza a:** No aplica; si se acepta, amplía ADR 0012–0015 y sustituye únicamente la
  propiedad y la exclusión temporal provisionales que ADR 0012 y ADR 0014 difirieron para P8
- **Reemplazado por:** No aplica

## Contexto

Claridez ya permite aceptar una cotización, crear una `Reservation` provisional, confirmar o
cancelar la reserva y coordinar su `EventPreparation`. La tabla física
`commercial_reservation` impide solapamientos entre reservas provisionales y confirmadas mediante
una exclusión GiST por organización, espacio e intervalo del evento. El vencimiento se materializa
actualmente cuando un servicio Django lo ejecuta.

P8 debe añadir agenda diaria, semanal y mensual, montaje, desmontaje, buffers, bloqueos internos,
reservas temporales, reprogramación e historial sin debilitar los contratos de 5.1, 5.2, P6 o P7.
Una reserva y un bloqueo deben competir mediante una sola defensa temporal PostgreSQL. Además, la
reprogramación debe preservar evidencia comercial y operativa, y seguir siendo íntegra si una
escritura omite los servicios mediante ORM bulk o SQL directo.

La decisión modifica una propiedad modular ya aceptada y una convención transversal de integridad;
por ello requiere ADR. Mientras este ADR permanezca `Propuesto`, no autoriza implementación.

## Decisiones propuestas para aprobación

### 1. Propiedad modular y compatibilidad física

1. `claridez.scheduling` será propietario de disponibilidad, políticas temporales, bloqueos,
   reservas temporales y confirmadas, reprogramaciones, cancelaciones de reserva e historial de
   agenda.
2. `Reservation` se adoptará mediante una migración de estado de Django. No se copiarán filas ni se
   renombrará inicialmente `commercial_reservation`; el nombre físico se conserva durante P8 para
   reducir el riesgo de cutover y mantener las FK existentes.
3. `claridez.commercial` conservará `EventRequest`, `Quotation`, `QuotationVersion`, sus snapshots,
   sus estados y la evidencia comercial aceptada. La relación de la reserva con
   `QuotationVersion` dejará de ser uno-a-uno y pasará a ser protegida de muchos-a-uno únicamente
   para que una cadena de reprogramación pueda referenciar la misma versión aceptada inmutable.
   El guardián de snapshot de P6 seguirá exigiendo que la raíz coincida con la cotización; una
   sucesora solo podrá diferir en sede, espacio y horario mediante el evento canónico de
   reprogramación. Esta es la única relajación expresa de aquel contrato.
4. `claridez.operations` conservará `EventPreparation`, sus ítems y transiciones. Extenderá su
   máquina de estados para representar una preparación sustituida por reprogramación.
5. `claridez.catalog` no será consultado para reconstruir una reserva o preparación histórica.
   Solo alimentará nuevas cotizaciones según P6.
6. `claridez.crm` consumirá proyecciones inmutables de `scheduling.public`; no importará sus modelos
   ORM. `claridez.organizations` conservará sedes, espacios, membresías, configuración y zona
   horaria organizacional, y scheduling los referenciará mediante claves tenant-aware.
7. Los coordinadores transaccionales dependerán de puertos públicos estrechos. Ningún módulo
   obtendrá autoridad sobre entidades de otro módulo por importar su modelo.

### 2. Tiempo y ocupación

1. Todo intervalo de evento y de ocupación será `tstzrange` finito, no vacío y canónico
   semiabierto `[inicio, fin)`. Dos intervalos adyacentes no se solapan. No se admiten límites
   abiertos ni infinitos.
2. Cada reserva capturará por separado el intervalo del evento, montaje, desmontaje, buffer previo,
   buffer posterior y la zona IANA empleada al convertir la hora local. La ocupación se calculará
   como `[inicio - montaje - buffer_previo, fin + desmontaje + buffer_posterior)`.
3. Las políticas configurables pertenecerán a scheduling por espacio; sus valores se copiarán como
   snapshot a cada nueva reserva. Cambiar una política no moverá compromisos existentes.
4. Una hora local inexistente o ambigua se rechazará. No habrá corrección silenciosa ni elección
   implícita de `fold`. Cambiar después la zona de la organización no moverá instantes ya capturados.

### 3. Reserva, bloqueo y proyección temporal única

1. `Reservation` y `ScheduleBlock` serán entidades de dominio distintas. Una reserva deriva de una
   cotización aceptada; un bloqueo expresa indisponibilidad interna y exige razón, alcance y actor.
2. `ScheduleAllocation` será la proyección actual por espacio utilizada por una única exclusión
   GiST. Cada fila tendrá exactamente un origen: reserva o objetivo de bloqueo. No será una segunda
   fuente de verdad ni tendrá endpoints de escritura propios.
3. La exclusión usará organización, espacio e intervalo ocupado con un indicador persistido
   `is_blocking`; no contendrá `now()`, `transaction_timestamp()` ni otro predicado temporal volátil.
4. Un guardián diferido comprobará al commit equivalencia exacta entre dominio, último evento
   canónico y asignación: origen, tenant, espacio, intervalo, revisión y condición bloqueante.
5. El rol `claridez_app` podrá leer, insertar y actualizar asignaciones solamente como efecto de
   comandos de dominio; no tendrá `DELETE`, `TRUNCATE` ni autoridad para editar historia. Los
   triggers y guardianes harán fallar también una escritura directa que no deje el agregado
   equivalente al commit.

### 4. Expiración bajo el lock del espacio

1. Toda operación que pueda crear, confirmar, sustituir o competir con una asignación tomará un
   advisory lock transaccional derivado de `(organization_id, space_id)`. Si intervienen varios
   espacios, los locks se tomarán en orden total por UUID.
2. Una función PostgreSQL invocada por los triggers de las rutas de escritura relevantes tomará el
   mismo lock, localizará reservas provisionales del espacio con
   `hold_expires_at <= transaction_timestamp()`, agregará el evento canónico de expiración y hará
   no bloqueante su asignación antes de comprobar o insertar la nueva ocupación.
3. La disponibilidad y los servicios invocarán la misma operación, pero la corrección no dependerá
   exclusivamente de que Django la haya llamado primero. Un `INSERT` o `UPDATE` directo que intente
   crear competencia temporal pasará por el mismo lock y saneamiento; una escritura incompleta
   fallará en el guardián diferido.
4. Confirmación y expiración bloquearán espacio y reserva en el mismo orden y compararán contra el
   mismo `transaction_timestamp()`. En el límite exacto, `hold_expires_at <=` hace ganar a la
   expiración; nunca podrán confirmarse y expirar ambas.

### 5. Cadena e idempotencia de reprogramación

1. Cada reserva tendrá `root_reservation_id` no nulo. La raíz se referenciará a sí misma y tendrá
   `predecessor_id` nulo; toda sucesora tendrá un único predecesor directo y la misma raíz.
2. Una unicidad parcial de `predecessor_id` impondrá como máximo una sucesora directa. Un guardián
   recursivo diferido impedirá ciclos, raíces ajenas, cadenas partidas y cambios de raíz, y exigirá
   la misma organización, `EventRequest` y `QuotationVersion` en toda la cadena.
3. Habrá como máximo una reserva en `provisional` o `confirmed` por raíz y, adicionalmente, por
   `EventRequest`. Una cotización aceptada originará como máximo una raíz, aunque todas las
   sucesoras la referencien. Los índices parciales y la exclusión temporal protegerán tanto el
   concepto vigente como su ocupación.
4. `rescheduled` será terminal. La predecesora solo podrá alcanzarlo si, en la misma transacción,
   existen su única sucesora, la asignación equivalente y el evento canónico que relaciona ambas.
   El fallo de cualquier paso revertirá toda la operación.
5. La sucesora conservará la misma `QuotationVersion` y la misma referencia de evidencia de
   confirmación inmutable. Una reprogramación provisional conservará el plazo original del hold;
   una confirmada no reemitirá ni modificará la cotización cuando el actor declare que las
   condiciones comerciales no cambiaron.
6. El evento canónico tendrá unicidad por organización, tipo de comando y clave de idempotencia,
   junto con hash del payload. La misma clave y payload devolverán el resultado ya creado; la misma
   clave con otro payload fallará. Esa unicidad, el lock de raíz y los guardianes protegen también
   SQL directo y carreras.

### 6. Autoridad única del historial

1. `ScheduleEvent` será la única bitácora append-only de scheduling. Registrará creación de hold,
   confirmación, expiración, reprogramación, cancelación, creación y liberación/cancelación de
   bloqueo, y procedencia de backfill o cutover.
2. Cada comando de scheduling producirá un solo evento canónico. El evento de reprogramación
   registra simultáneamente la predecesora y la sucesora; no se duplicará esa transición en otra
   bitácora de agenda.
3. `EventRequestHistory` seguirá siendo historia comercial de la oportunidad y
   `PreparationTransition` historia operativa. Podrán referenciar o componer el evento de
   scheduling, pero no serán autoridades alternativas sobre el horario.
4. Reservas, bloqueos, asignaciones, calendarios y vistas CRM serán estado vigente o proyecciones
   derivadas. `ScheduleEvent` no admitirá `UPDATE` ni `DELETE`, tampoco mediante SQL directo.

### 7. Efecto operativo de reprogramar

1. Solo podrán reprogramarse reservas `provisional` o `confirmed`. Una confirmada exigirá una
   preparación `preparing` o `ready`; se rechazarán `in_progress`, `completed`, `cancelled`,
   `expired` y `rescheduled`.
2. La preparación anterior pasará a `rescheduled`, será terminal y quedará enlazada con la reserva
   sucesora. El estado y la causa se añadirán a la máquina y a los guardianes PostgreSQL de 5.2.
3. La nueva preparación se construirá desde el snapshot de la misma cotización aceptada y desde el
   nuevo snapshot horario. No consultará el catálogo vigente ni copiará estados resueltos,
   declaraciones de listo, transiciones completadas o evidencia de ejecución.
4. Un ítem libre será exactamente un `PreparationItem` con `baseline_key IS NULL`. Se podrán
   trasladar título, sección, posición relativa, obligatoriedad y notas; quedará `pending`, sin
   fecha de resolución, nota de estado ni vencimiento, con un nuevo `client_request_id` y un vínculo
   `carried_from_item_id`. El responsable se conservará solo si su membresía continúa activa,
   pertenece al tenant y posee `operation:manage`.
5. Reserva anterior, preparación anterior, nueva reserva, nueva preparación, ítems, asignaciones y
   eventos se modificarán en una sola transacción. Un rollback restaurará íntegramente el estado
   anterior.

### 8. CRM, autorización y aislamiento

1. Para una tarea CRM abierta asociada a `EventRequest`, `requires_schedule_review` será una
   condición derivada. Será verdadera cuando el último evento de reserva aplicable y no originado
   por cutover sea igual o posterior en tiempo a la última revisión registrada en
   `FollowUpTaskHistory`.
2. Scheduling expondrá por `scheduling.public` una proyección inmutable con el último evento
   aplicable. CRM no cambiará automáticamente fecha, estado, revisión, próxima acción ni historia
   de la tarea.
3. Se incorporarán capacidades atómicas para gestionar bloqueos, reprogramar y exportar agenda; se
   reutilizarán `availability:read`, `reservation:confirm`, `reservation:cancel`, `sales:manage`,
   `operation:manage` y `venue:manage` donde el contrato sea conjuntivo.
4. Toda tabla privada nueva tendrá claves compuestas tenant-aware, RLS habilitado y `FORCE RLS`.
   Autenticación, sesión, CSRF, organización activa, membresía activa y capacidad se validarán
   dentro de `authorized_tenant_scope`; RLS seguirá siendo defensa en profundidad.

### 9. Migración y cutover

1. La adopción de propiedad, la sustitución de la exclusión vigente y la instalación de guardianes
   requerirán procedimiento de cutover con lock de mantenimiento, preflight, backfill determinista,
   comprobaciones y rollback antes de aceptar tráfico.
2. Cada reserva existente será su propia raíz. Montaje, desmontaje y buffers históricos se
   completarán con cero; se registrará `cutover_snapshot` con procedencia y momento observado, sin
   inventar transiciones anteriores.
3. Los holds ya vencidos se expirarán como transición real durante el cutover antes de crear las
   asignaciones. Una divergencia no reparable de forma determinista, un solapamiento o una cadena
   incoherente abortará toda la migración.
4. Se distinguirán: procedimiento documentado y ensayado; ejecución local en una base desechable;
   y ejecución futura en un entorno destino. Ningún ensayo local permitirá afirmar que ocurrió un
   cutover productivo.

### 10. Infraestructura y contratos previos

1. P8 no introducirá cola, worker, broker, Redis, Celery, Dramatiq ni sincronización externa. La
   expiración será transaccional y determinista; una automatización futura requerirá una necesidad
   observada y otra decisión.
2. Los endpoints vigentes de disponibilidad, confirmación y cancelación conservarán sus contratos
   de 5.1 y 5.2 y delegarán en scheduling/coordinación. No se relajarán las restricciones de
   cancelación operativa ni se reemitirá una cotización de forma implícita.

## Aspectos provisionales

- Los nombres físicos `ScheduleAllocation`, `ScheduleBlock`, `ScheduleBlockTarget`,
  `SpaceSchedulePolicy` y `ScheduleEvent`, así como los nombres exactos de constraints, índices,
  funciones SQL y rutas REST nuevas, son descriptivos hasta aprobar este ADR y la especificación.
- El nombre físico `commercial_reservation` se conserva en P8. Un eventual renombrado posterior
  requerirá evaluación separada y no forma parte del cutover inicial.

## Asuntos diferidos

- Sincronización bidireccional con Google Calendar, Outlook u otros proveedores.
- Calendario personal genérico, inventario detallado y capacidad fraccional dentro de un espacio.
- Procesamiento periódico asíncrono de expiraciones; la corrección transaccional definida aquí es
  suficiente para P8.
- Cambios comerciales durante una reprogramación. Si cambian precio, alcance o condiciones, se
  deberá crear una nueva revisión comercial mediante un flujo futuro explícito; P8 no lo simula.

## Validación pendiente

Antes de aceptar la implementación deberán superarse pruebas de servicios, API, permisos, RLS,
SQL directo, ORM bulk, migraciones y concurrencia PostgreSQL real. En especial: confirmación contra
expiración en el límite, dos holds, hold contra bloqueo, bloqueo contra confirmación, dos
reprogramaciones de la misma raíz, reprogramaciones cruzadas entre dos espacios, cancelación contra
reprogramación y rollback completo de la coordinación operativa. También deberán validarse
OpenAPI, regresión 5.1/5.2/P6/P7 y la interfaz a 1440×900 y 390×844.

## Alternativas consideradas

- **Mantener `Reservation` en commercial:** descartado porque dividiría la autoridad sobre agenda,
  bloqueos y reprogramaciones, y obligaría a sostener dos defensas temporales.
- **Copiar reservas a una tabla nueva:** descartado por duplicar identidad, exigir conciliación y
  aumentar el riesgo de cutover sin aportar valor funcional.
- **Actualizar fecha y espacio de la misma reserva:** descartado porque reescribe evidencia y hace
  imposible reconstruir la agenda comprometida originalmente.
- **Una exclusión para reservas y otra para bloqueos:** descartado porque dos exclusiones no
  arbitran carreras entre tipos distintos de ocupación.
- **Predicado `hold_expires_at > now()` en la exclusión:** descartado porque los predicados de
  índices y constraints deben ser inmutables y no liberarían físicamente una asignación vencida.
- **Expirar solo desde Django:** descartado porque SQL directo y operaciones bulk podrían conservar
  bloqueos vencidos o divergir de la proyección.
- **Trigger que inventa todo el agregado omitido:** descartado. Los triggers materializan la
  expiración determinista y rechazan incoherencia; la orquestación normal continúa explícita en
  servicios.
- **Modificar tareas CRM al reprogramar:** descartado porque altera intención e historia del usuario
  y crea una transición ficticia.
- **Infraestructura asíncrona anticipada:** descartada porque no existe una necesidad que justifique
  su coste operativo.

## Consecuencias

- Scheduling obtiene una autoridad modular única y una defensa temporal común para reservas y
  bloqueos.
- La adopción sin copia conserva identidad y FK, pero exige migraciones de estado y cutover
  cuidadosamente ensayados.
- La cadena append-only aumenta trazabilidad y permite reintentos seguros, a costa de guardianes
  PostgreSQL recursivos y coordinación transaccional adicional.
- Las lecturas pueden materializar expiraciones vencidas; por tanto, disponibilidad deja de ser una
  consulta puramente pasiva, aunque continúa siendo idempotente.
- La historia comercial y operativa se preserva sin convertirse en una segunda historia de agenda.
- El bloqueo ordenado por espacio reduce deadlocks, pero todas las rutas de escritura, incluidas las
  internas, deben respetar el mismo protocolo.
- Este documento no autoriza código mientras su estado sea `Propuesto`.
