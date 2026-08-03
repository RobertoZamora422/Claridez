# ADR 0015 — Límites de people/CRM y autoridad comercial P7

- **Estado:** Aceptado
- **Fecha:** 2026-08-02
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

P7 debe incorporar CRM y seguimiento comercial sin duplicar las entidades ya implementadas por
5.1. `claridez.commercial` posee actualmente `Person`, `PersonRevision`, `EventRequest`,
cotizaciones versionadas y reservas. `EventRequest` ya representa la necesidad comercial, conserva
la máquina de estados aprobada y enlaza toda la evidencia que permite determinar si una persona ha
llegado a ser cliente.

El Blueprint asigna al módulo conceptual Personas y CRM la identidad de persona, consentimiento,
interacciones y seguimiento, pero no le asigna cotizaciones emitidas ni reservas. Mover `Person`
directamente a `claridez.crm` produciría dependencias recíprocas: commercial necesitaría CRM para
la persona de `EventRequest`, mientras CRM necesitaría commercial para componer la oportunidad.
Mantener toda la identidad dentro de commercial evitaría el ciclo inmediato, pero convertiría al
módulo de solicitudes y propuestas en propietario permanente de identidad y privacidad.

La solución necesita separar identidad maestra y orquestación CRM, conservar el flujo exacto de
5.1, mantener el aislamiento de ADR 0009, evitar nuevas autoridades ambiguas sobre `EventRequest`
y permitir una migración de estado Django sin copiar ni renombrar inicialmente las tablas físicas.
También debe definir cómo fusionar personas sin reescribir solicitudes, cotizaciones, snapshots,
reservas ni evidencia de auditoría.

El propietario aprobó el plan breve, sus aclaraciones funcionales y este registro como autorización
arquitectónica para implementar P7 dentro de los límites aquí descritos.

## Decisiones aceptadas

1. **Dos módulos técnicos implementan Personas y CRM.** `claridez.people` será propietario de
   `Person`, `PersonRevision`, fusiones, alias de contacto y eventos de consentimiento.
   `claridez.crm` será propietario de interacciones, tareas, próximos contactos y composición de
   vistas CRM. Esta separación interna no crea dos módulos funcionales de producto: ambos
   implementan el límite conceptual Personas y CRM del Blueprint.

2. **La dirección de dependencias de P7 será acíclica.** La flecha significa que el consumidor
   depende del proveedor:

   ```text
   crm ─────────▶ commercial ─────────▶ people
    │                                      ▲
    └──────────────────────────────────────┘

   commercial ─▶ catalog
   crm/commercial/people ─▶ organizations e identity
   ```

   `people` no importará modelos, migraciones ni servicios de commercial o CRM. Commercial podrá
   referenciar `people.Person` y consumir su puerto público. CRM consumirá los puertos públicos de
   people y commercial. Commercial no importará CRM. La coordinación commercial/operations ya
   aprobada por ADR 0013 no se modifica ni constituye precedente para una dependencia nueva de P7.

3. **Los puertos serán estrechos y explícitos.** `people.public` resolverá identidad canónica,
   alias, deduplicación, posibilidad de escritura y consentimiento efectivo. `commercial.public`
   expondrá la proyección de `EventRequest`, su historial y la evidencia derivada de solicitudes y
   reservas. CRM compondrá ambos puertos; no consultará tablas ajenas de forma dispersa ni copiará
   estados comerciales.

4. **La migración inicial será de estado, no de datos.** La secuencia prevista será:

   ```text
   commercial.0004
       → people.0001_adopta_estado
       → commercial.0005_libera_estado
       → crm.0001
   ```

   Una operación equivalente a `SeparateDatabaseAndState` incorporará `Person` y
   `PersonRevision` al estado de people, cambiará la referencia estatal de `EventRequest` y
   retirará esos modelos del estado de commercial. Las filas, UUID, constraints, políticas RLS,
   triggers e historia permanecerán en las tablas físicas `commercial_person` y
   `commercial_personrevision` durante P7. No habrá copia de filas ni renombrado físico en esta
   etapa.

5. **`EventRequest` seguirá siendo la única oportunidad.** No se creará una entidad, tabla o
   identidad `Opportunity`. La bandeja CRM, la oportunidad integral y el historial usarán el mismo
   UUID de `EventRequest`. Commercial continuará poseyendo sus estados, origen, responsable,
   motivo de cierre, cotizaciones, versiones, snapshots y reservas. CRM podrá presentar y
   enriquecer esa información, pero no mantendrá una segunda máquina de estados ni una ruta de
   mutación alternativa.

6. **5.1 conserva su significado sin reinterpretación.** Los estados continúan siendo `new`,
   `quoted`, `accepted`, `confirmed`, `closed_lost` y `cancelled`, con las transiciones y efectos
   aprobados. Una oportunidad se considera ganada desde la primera confirmación real de una reserva
   asociada; esa evidencia no desaparece por una cancelación posterior. Se considera perdida solo
   cuando termina en `closed_lost` sin confirmación previa. La próxima acción se deriva de la tarea
   abierta aplicable más próxima y no se duplica como campo editable de `EventRequest`.

7. **Interesado y cliente serán condiciones derivadas y no etiquetas.** La existencia de una o más
   solicitudes dentro del conjunto canónico demuestra historial como interesado. La existencia de
   al menos una reserva alguna vez confirmada dentro de ese conjunto determina cliente. Ambas
   condiciones pueden coexistir: llegar a ser cliente no borra el historial de interés ni las
   oportunidades anteriores. `people` no dependerá de commercial para calcularlas; CRM las
   compondrá a partir del resolvedor de people y del puerto de evidencia de commercial.

8. **El historial de `EventRequest` será append-only y no inventará transiciones.** Los cambios
   posteriores a P7 registrarán estado, actor, fecha, origen y evidencia disponibles. El backfill
   solo reconstruirá hechos respaldados de forma determinista por timestamps, reservas,
   cotizaciones o snapshots ya existentes y registrará su procedencia. Cuando no exista evidencia
   histórica reconstruible, creará únicamente una entrada `estado existente al corte`, con la
   fecha de registro del corte y sin inventar actor, fecha efectiva, motivo ni estados intermedios.

9. **Las interacciones serán evidencia minimizada e inmutable.** Una interacción incluirá
   organización, persona canónica, `EventRequest` opcional, canal, dirección entrante o saliente,
   fecha, responsable y resumen de longitud limitada. No almacenará cuerpos completos, adjuntos ni
   transcripciones. La aplicación no podrá editar o borrar una interacción registrada. Una
   corrección creará otra entrada append-only enlazada mediante `corrects`, dentro de la misma
   organización y contexto de persona; la evidencia original permanecerá visible para auditoría
   autorizada. La integridad impedirá autofreferencias, ciclos y enlaces tenant cruzados.

10. **Las tareas mantendrán seguimiento trazable.** Una tarea tendrá persona canónica,
    `EventRequest` opcional, responsable, vencimiento o próximo contacto, estado y finalización.
    Los cambios relevantes se registrarán de forma append-only. Si una tarea se vincula a una
    solicitud histórica cuya FK de persona apunta a una persona fusionada, su persona canónica
    deberá pertenecer al mismo conjunto de fusión.

11. **La fusión será lógica, transaccional y conservadora.** Una fusión append-only enlazará una
    persona fuente con un destino canónico de la misma organización. Las relaciones históricas no
    se reasignarán ni eliminarán. Se aplicarán estas invariantes:

    - las lecturas por fuente o alias resolverán el nodo canónico y agregarán el conjunto completo;
    - las escrituras sobre una persona fusionada responderán conflicto y no se redirigirán
      silenciosamente;
    - una relación nueva deberá referenciar la persona canónica, mientras el flujo 5.1 de una
      solicitud preexistente podrá continuar sin reescribir su FK histórica;
    - los alias conservarán solo teléfono o correo normalizados y la procedencia mínima necesaria;
      búsqueda y deduplicación devolverán la persona canónica;
    - se prohibirán autofusiones, ciclos, destinos que alcancen la fuente y fusiones tenant cruzadas;
    - la misma clave idempotente con la misma fuente y destino devolverá el resultado existente;
      reutilizarla con otra orden o fusionar la fuente hacia otro destino será conflicto;
    - la transacción bloqueará en orden estable todas las personas y rutas involucradas, volverá a
      resolver las raíces y solo entonces insertará la fusión;
    - crear una relación bloqueará la persona referenciada y volverá a comprobar que siga siendo
      canónica; si la relación se confirmó antes de la fusión, quedará como historia del conjunto;
    - guardianes PostgreSQL protegerán también SQL directo, `bulk_create`, `bulk_update` y
      `QuerySet.update` en los límites aplicables;
    - los agregados usarán el conjunto de IDs sin duplicados y contarán cada solicitud, reserva,
      interacción o tarea por su propia clave primaria.

12. **El consentimiento será append-only y de negación conservadora.** Cada evento registrará
    organización, persona, propósito, canal, origen, fecha, evidencia mínima, actor y tipo de evento
    —concesión, revocación o rectificación—. Una fusión no creará, trasladará ni reinterpretará una
    concesión. Una revocación de cualquier alias prevalecerá sobre concesiones anteriores; solo una
    concesión explícita posterior sobre la persona canónica podrá restablecerla. Ausencia,
    contradicción no resuelta o evidencia insuficiente se tratarán como consentimiento no
    concedido.

13. **`sales:*` será la única autoridad de `EventRequest`.** No se crearán capacidades
    `opportunity:*`. `sales:read` por sí sola conservará únicamente la lectura comercial mínima ya
    autorizada para Operaciones y Finanzas. La bandeja CRM, la oportunidad integral y su historial
    requerirán conjuntamente `sales:read` y `person:read`. Crear, modificar o cerrar
    `EventRequest`, cambiar fuente o responsable y ejecutar el flujo de cotizaciones continuará
    requiriendo `sales:manage`. Las capacidades vigentes de reservas no serán sustituidas ni
    ampliadas por P7.

14. **Las capacidades enlazadas serán conjuntivas y no jerárquicas.** Leer una interacción exigirá
    `interaction:read` y `person:read`; registrarla exigirá `interaction:record` y `person:read`.
    `sales:read` se añadirá únicamente cuando la interacción esté vinculada a un `EventRequest`.
    Administrar tareas exigirá `task:manage` y `person:read`, más `sales:read` cuando exista ese
    vínculo. Leer consentimiento exigirá `consent:read` y `person:read`; modificarlo o revocarlo,
    `consent:manage` y `person:read`. Fusionar exigirá conjuntamente `person:merge` y
    `person:manage`, además de sesión válida, CSRF, membresía activa, razón obligatoria, revisiones
    vigentes, idempotencia, bloqueo concurrente y auditoría append-only. Ninguna capacidad implicará
    otra y la visibilidad del frontend nunca será una decisión de autorización.

15. **La matriz CRM inicial será explícita y backend-first.** Se propone:

    | Capacidad | `propietario` | `administrador` | `comercial` | `operaciones` | `finanzas` |
    | --- | :---: | :---: | :---: | :---: | :---: |
    | `person:read` | Sí | Sí | Sí | No | No |
    | `person:manage` | Sí | Sí | Sí | No | No |
    | `sales:read` | Sí | Sí | Sí | Sí | Sí |
    | `sales:manage` | Sí | Sí | Sí | No | No |
    | `interaction:read` | Sí | Sí | Sí | No | No |
    | `interaction:record` | Sí | Sí | Sí | No | No |
    | `task:manage` | Sí | Sí | Sí | No | No |
    | `consent:read` | Sí | Sí | Sí | No | No |
    | `consent:manage` | Sí | Sí | Sí | No | No |
    | `person:merge` | Sí | Sí | No | No | No |

    El conjunto de capacidades de `propietario` dejará de construirse como
    `frozenset(Capability)`. Cada capacidad vigente y cada capacidad nueva aprobada se enumerará de
    forma explícita en el perfil. Añadir una capacidad futura no la concederá automáticamente al
    propietario ni a ningún otro rol.

16. **Fusión ejecutable; anonimización y eliminación diferidas.** `person:merge` será ejecutable en
    P7 exclusivamente por `propietario` y `administrador` mediante el contrato conjuntivo de la
    decisión 14. No estará condicionada a una implementación futura de MFA. P7 no creará endpoints
    ni concederá capacidades para anonimizar o eliminar, y la fusión no podrá usarse como sustituto
    de esas operaciones.

17. **Toda la frontera seguirá siendo tenant-aware y deny-by-default.** Las tablas privadas nuevas
    incluirán `organization_id`, FK y unicidades compuestas, RLS simétrica con `ENABLE` y `FORCE`, y
    privilegios mínimos. Autorización, resolución canónica, consulta, escritura y materialización
    completa ocurrirán dentro de `authorized_tenant_scope`. IDs directos, aliases, búsqueda, bulk y
    SQL se probarán negativamente con dos organizaciones.

## Aspectos provisionales

- Los nombres físicos `commercial_person` y `commercial_personrevision` permanecerán durante P7,
  aunque la propiedad de estado Django pase a `claridez.people`.
- Los nombres finales de las tablas de fusión, alias, consentimiento, interacción, corrección y
  tarea podrán ajustarse durante implementación si conservan exactamente las propiedades y
  relaciones decididas aquí.
- El catálogo técnico inicial de propósitos, canales y fuentes de consentimiento será mínimo y
  deny-by-default. No constituirá una conclusión sobre base jurídica o suficiencia probatoria.
- La forma visible de presentar una cadena de correcciones podrá refinarse sin ocultar ni modificar
  la evidencia original.

## Asuntos diferidos

- Renombrar físicamente las tablas históricas de persona. Cualquier corte posterior deberá tener
  migración, recuperación, pruebas RLS y una decisión explícita si altera convenciones estables.
- Anonimización y eliminación ejecutables, incluida su interacción con evidencia comercial,
  reservas, obligaciones de conservación y legal hold.
- Plazos de retención, propósitos jurídicos definitivos, base legal y suficiencia de la evidencia
  de consentimiento. Hasta contar con política aprobada no habrá purga automática ni se presentará
  la conservación provisional como plazo legal.
- Deshacer una fusión o redistribuir selectivamente relaciones entre personas fusionadas.
- Correo, WhatsApp, campañas, automatización avanzada, IA, adjuntos y omnicanalidad completa.
- Capacidades personalizadas, roles adicionales y administración completa de privacidad.

## Validación observada

La implementación local de P7 demostró:

- migración desde cero mediante la creación de la base de prueba y migración dirigida desde
  `commercial.0004` sin copiar filas ni renombrar `commercial_person` o
  `commercial_personrevision`; UUID, relaciones y estado actual se conservaron, y el backfill sin
  evidencia creó solo `cutover_state` sin actor, fecha efectiva, motivo ni transición inventados;
- grafo Django sin migraciones pendientes y prueba arquitectónica que impide imports
  `people → commercial`, `people → crm`, `commercial → crm` y el acceso de consumidores al módulo
  interno `people.services` fuera de `people.public`;
- regresión completa de 5.1, 5.2 y P6, incluidas cotizaciones, snapshots, reservas, operación,
  multi-espacio y catálogo;
- dos tenants, `ENABLE` + `FORCE RLS`, FK compuestas, denegación sin scope y con IDs cruzados,
  privilegios mínimos, ORM, SQL directo y operaciones bulk;
- fusión lógica concurrente e idempotente, resolución canónica, aliases, prevención de nuevas
  relaciones con la fuente, auditoría append-only, consentimiento conservador y agregación sin
  doble conteo;
- interacciones inmutables con correcciones enlazadas, tareas con historial append-only y
  consentimiento append-only protegido también en PostgreSQL;
- matriz explícita de cinco perfiles y autorización conjuntiva; `sales:read` no concede por sí sola
  acceso CRM a Operaciones o Finanzas, y propietario ya no recibe `frozenset(Capability)`;
- contrato API/OpenAPI validado sin advertencias, 149 pruebas backend no integración, 43 integración
  PostgreSQL y 17 frontend, más build de producción y auditoría de dependencias sin vulnerabilidades
  conocidas;
- validación visual real a 1440×900 y 390×844 sin desbordamiento horizontal, con navegación móvil
  de dos filas y objetivos de 44 px. No se observaron errores de consola.

No se ejecutaron CI remoto, despliegue ni cutover sobre un entorno destino; no forman parte de esta
evidencia local.

## Alternativas consideradas

- **Mantener `Person` provisionalmente en commercial:** evita la migración inicial, pero deja
  identidad, consentimiento y privacidad bajo un propietario funcional incorrecto y obliga a un
  segundo corte posterior. Se conserva solo como alternativa de contingencia, no como dirección de
  P7.
- **Mover `Person` directamente a CRM:** rechazado porque crea `commercial → crm` por la FK y
  `crm → commercial` por `EventRequest`, o exige sustituir integridad relacional por referencias
  débiles.
- **Crear una entidad `Opportunity` relacionada con `EventRequest`:** rechazado porque representa
  dos veces la misma necesidad comercial y permite deriva de etapa, resultado y responsable.
- **Crear capacidades `opportunity:*` además de `sales:*`:** rechazado porque dos autoridades
  podrían leer o modificar la misma entidad y eludir mutuamente sus restricciones.
- **Renombrar o copiar las tablas de persona durante P7:** rechazado por riesgo innecesario para FK,
  RLS, triggers e historia; el cambio de estado permite separar propiedad sin mover filas.
- **Reasignar relaciones durante una fusión:** rechazado porque reescribiría evidencia histórica y
  podría alterar snapshots, conteos y auditoría.
- **Editar interacciones o consentimientos existentes:** rechazado porque destruiría evidencia y
  haría indistinguible una corrección de la versión originalmente registrada.
- **Inferir todas las transiciones históricas desde el estado actual:** rechazado porque produciría
  actores, fechas o secuencias no demostradas por la evidencia existente.

## Consecuencias

- La identidad maestra queda reutilizable sin convertir a CRM en dependencia de commercial ni a
  commercial en dependencia de CRM.
- Dos apps Django implementan un único módulo conceptual; esto añade puertos y una migración de
  estado, pero elimina la dependencia circular y fija propietarios claros.
- Las tablas físicas conservarán nombres heredados durante P7. Las herramientas operativas deberán
  distinguir nombre físico de propiedad de estado Django.
- La bandeja y la oportunidad integral serán deliberadamente más restrictivas que la proyección
  comercial mínima. Operaciones y Finanzas conservan su comportamiento vigente sin recibir acceso
  CRM por inferencia.
- Una persona fusionada conservará toda su evidencia y podrá tener varias solicitudes históricas;
  las consultas deberán resolver el conjunto canónico y evitar fan-out o doble conteo.
- El historial inicial podrá ser incompleto cuando el sistema no posea evidencia reconstruible. Esa
  limitación será explícita y preferible a fabricar una cronología.
- Las correcciones y revocaciones aumentarán el número de filas append-only, a cambio de mantener
  trazabilidad e inmutabilidad.
- P7 podrá registrar evidencia técnica de consentimiento, pero no resolverá por sí solo política
  legal, retención, anonimización o eliminación.

## Evidencia

- [Blueprint maestro](../product/PRODUCT_BLUEPRINT.md)
- [Roadmap de entrega](../product/PRODUCT_DELIVERY_ROADMAP.md)
- [Handoff vigente](../PROJECT_HANDOFF.md)
- [Especificación aprobada de 5.1](../product/ITERATION_5_1_COMMERCIAL_FLOW.md)
- [ADR 0001 — Monorepo y monolito modular](0001-monorepo-and-modular-monolith.md)
- [ADR 0009 — Aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0010 — Identidad local y sesiones](0010-local-identity-and-server-sessions.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)
- [ADR 0012 — Integridad comercial](0012-commercial-scheduling-and-monetary-integrity.md)
- [ADR 0013 — Coordinación comercial-operaciones](0013-commercial-operations-coordination-and-integrity.md)
- [ADR 0014 — Multi-espacio y catálogo](0014-multi-space-business-configuration-and-catalog-boundaries.md)
