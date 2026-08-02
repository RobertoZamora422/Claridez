# ADR 0014 — Multi-espacio y límites de configuración funcional P6

- **Estado:** Aceptado
- **Fecha:** 2026-08-01
- **Reemplaza a:** La decisión de espacio único de ADR 0012
- **Reemplazado por:** No aplica

## Contexto

ADR 0012 resolvió la primera agenda comercial con un único espacio implícito por organización y una
exclusión GiST sobre organización e intervalo. P6 debe permitir sedes y espacios reales, incorporar
un catálogo versionado a las cotizaciones y conservar sin reinterpretación las solicitudes,
versiones emitidas, reservas y preparaciones creadas por 5.1 y 5.2.

El cambio atraviesa `claridez.organizations`, `claridez.catalog`, `claridez.commercial` y la
proyección consumida por `claridez.operations`. También modifica una invariante concurrente y el
esquema que observa el guardián diferido de ADR 0013, por lo que requiere una decisión explícita de
propiedad, migración, locks y compatibilidad.

P6 autoriza administración HTTP de configuración funcional, sedes, espacios, catálogo, paquetes,
precios y vigencias. Esa autorización no amplía las acciones sensibles de ADR 0011: no habilita
administración web de membresías propietarias, propietarios, sesiones u otras operaciones que
continúan condicionadas por MFA y una etapa posterior.

## Decisiones aceptadas

1. **Propiedad modular.** `claridez.organizations` posee la configuración funcional de la
   organización, `Venue` y `Space`. `claridez.catalog` posee tipos de evento, servicios, productos,
   paquetes, composición, revisiones, precios y vigencias. `claridez.commercial` conserva la
   solicitud, las cotizaciones, sus snapshots y la reserva; consume los otros módulos mediante
   servicios públicos estrechos. `claridez.operations` recibe sede y espacio exclusivamente desde
   la proyección comercial autorizada.
2. **Relaciones tenant-aware.** Toda tabla nueva es privada, incluye `organization_id`, usa FK y
   unicidades compuestas por organización y aplica políticas simétricas `USING`/`WITH CHECK` con
   `ENABLE` y `FORCE ROW LEVEL SECURITY`. La validación, consulta, escritura y materialización
   completas permanecen dentro de `authorized_tenant_scope` conforme a ADR 0009.
3. **Sede y espacio principales.** Cada organización tiene exactamente una sede principal activa y
   un espacio principal activo. Las organizaciones existentes reciben `Sede principal` y
   `Espacio principal` con UUIDv5 derivados de la organización. Las organizaciones nuevas los crean
   en la misma unidad transaccional que sus settings y membresía propietaria.
4. **Backfill determinista.** Toda solicitud, versión de cotización y reserva preexistente se asocia
   al espacio principal de su organización. Las versiones conservan snapshots de identificador y
   nombre de sede y espacio. Los tipos de evento textuales históricos se materializan como
   definiciones organizacionales deterministas y el texto ya capturado sigue siendo la evidencia
   histórica.
5. **Espacio en el flujo comercial.** Una solicitud nueva selecciona un espacio activo del tenant.
   Cada nueva versión captura la sede y el espacio; aceptar la versión crea la reserva para ese
   espacio exacto. Cambiar o desactivar la configuración viva no reescribe solicitudes cerradas,
   versiones emitidas, reservas ni preparaciones.
6. **Exclusión concurrente por espacio.** La defensa final pasa a una exclusión GiST sobre
   `(organization_id WITH =, space_id WITH =, event_interval WITH &&)` para reservas provisionales o
   confirmadas. Los rangos continúan siendo `[inicio, fin)` y los rangos adyacentes son compatibles.
7. **Advisory lock por espacio.** La aceptación toma un advisory lock transaccional derivado de
   organización y espacio. Aceptaciones del mismo espacio se serializan antes de llegar al índice
   GiST; espacios distintos no comparten ese lock. La exclusión PostgreSQL sigue siendo la defensa
   final ante carreras.
8. **Compatibilidad con 5.2.** `EventPreparation` continúa identificado uno-a-uno por reserva y no
   duplica sede ni espacio. La proyección operativa agrega los snapshots comerciales. El guardián de
   ADR 0013 sigue comprobando confirmación/cancelación y agregado operativo; no se elimina, relaja ni
   usa para orquestar el backfill P6.
9. **Orden de migración y cutover.** El esquema de sedes, espacios y catálogo se crea primero; luego
   se añaden referencias anulables, se adquiere un lock de tabla sobre reservas, se ejecuta el
   backfill por organización, se comprueban cardinalidad y coherencia, se sustituye la exclusión y
   finalmente las referencias pasan a ser obligatorias. El procedimiento exige procesos 5.2, no
   admite un escritor 5.1 después del cambio y conserva el cutover obligatorio de ADR 0013 para un
   entorno que aún no lo haya ejecutado.
10. **Catálogo e historia.** El catálogo usa identidades estables, revisiones append-only, precios
    con vigencias no solapadas y composición explícita de paquetes. Al cotizar, el backend copia
    descripción, unidad, precio, referencia de revisión y composición aplicables a la línea. Las
    líneas ad hoc siguen permitidas y una versión emitida nunca consulta el catálogo vivo para
    reconstruir su historia.
11. **Capacidades P6.** Propietario y administrador gestionan configuración, sedes, espacios,
    catálogo y precios. Comercial consulta y usa el catálogo activo al cotizar, sin modificarlo.
    Operaciones consulta definiciones operativas mínimas y finanzas consulta valores autorizados.
    Las capacidades son backend-first y deny-by-default; ocultar controles en React es solo una
    adaptación de presentación.
12. **Frontera MFA de ADR 0011.** Los endpoints P6 aceptan sesión autenticada, CSRF y capacidades
    funcionales atómicas. No se crean endpoints de mutación de membresías, propietarios o seguridad
    sensible. P6 no constituye aceptación temporal del riesgo ni reemplaza el requisito de MFA para
    esas acciones.

## Aspectos provisionales

- Los nombres visibles `Sede principal` y `Espacio principal` son valores iniciales editables; sus
  UUID y su relación histórica permanecen estables.
- USD sigue siendo la única moneda funcional de cotización en P6, aunque la configuración conserve
  la propiedad organizacional del código de moneda.

## Asuntos diferidos

- Bloqueos internos, montaje/desmontaje, reprogramación y disponibilidad avanzada de P8.
- Inventario físico, proveedores, compras y costos de P12.
- Campos legales, fiscales, bancarios, contratos y documentos.
- Administración web de membresías, propietarios, MFA y sesiones de P16.

## Validación observada

La puerta local demostró migración desde el esquema 5.2 con una reserva confirmada y su agregado
operativo, backfill UUIDv5, ida/vuelta en la base de pruebas, dos organizaciones, aislamiento RLS,
FK tenant-aware, privilegios mínimos, carreras en el mismo y en distintos espacios, snapshots
inmutables, compatibilidad del guardián, OpenAPI y build. `npm run check:all` cerró con 144 pruebas no
integración, 37 integración PostgreSQL y 16 frontend. La revisión web adicional cubrió 375×812 y
1440×900 sin desbordamiento horizontal. El cutover de un entorno desplegado permanece sin ejecutar
hasta que exista ese entorno y autorización externa.

## Alternativas consideradas

- **Mantener exclusión por organización:** rechazada porque impediría eventos simultáneos en
  espacios distintos.
- **Derivar el espacio desde configuración viva:** rechazada porque reescribiría el significado de
  cotizaciones y reservas históricas.
- **Copiar sede y espacio a operations:** rechazada porque duplicaría propiedad y permitiría deriva;
  la proyección comercial ya es el puerto aprobado.
- **Crear un tenant o espacio global para históricos:** rechazado por ADR 0003 y 0009.
- **Administrar P6 desde Django Admin o abrir membresías en la misma pantalla:** rechazado porque
  eludiría la matriz funcional y ampliaría silenciosamente ADR 0011 sin MFA.

## Consecuencias

- Dos espacios de una organización pueden reservar intervalos simultáneos; un mismo espacio no.
- Las migraciones y servicios comerciales incorporan una referencia obligatoria adicional y deben
  conservar orden de locks y errores genéricos.
- El catálogo vivo puede evolucionar sin cambiar cotizaciones emitidas.
- La administración funcional se vuelve visible y útil sin abrir todavía administración sensible
  de identidad o membresías.
- Cualquier despliegue futuro debe respetar tanto el cutover 5.2 pendiente como el orden de migración
  multi-espacio aquí decidido.

## Evidencia

- [Blueprint maestro](../product/PRODUCT_BLUEPRINT.md)
- [Roadmap de entrega](../product/PRODUCT_DELIVERY_ROADMAP.md)
- [Especificación 5.1](../product/ITERATION_5_1_COMMERCIAL_FLOW.md)
- [Especificación 5.2](../product/ITERATION_5_2_OPERATIONS_SPECIFICATION.md)
- [ADR 0009 — Aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)
- [ADR 0012 — Integridad de agenda comercial](0012-commercial-scheduling-and-monetary-integrity.md)
- [ADR 0013 — Coordinación comercial-operaciones](0013-commercial-operations-coordination-and-integrity.md)
