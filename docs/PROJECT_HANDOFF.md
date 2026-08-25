# Claridez — Handoff del proyecto

- **Fecha de corte:** 25 de agosto de 2026
- **Etapa funcional activa:** ninguna; P12 está cerrada localmente bajo ADR 0021
- **Siguiente etapa:** implementación de P13 — Operación avanzada; arquitectura y contrato
  aprobados, implementación todavía pendiente de aprobación explícita

## Qué es Claridez

Claridez es un SaaS B2B privado, propietario y multiempresa para la gestión integral de salones y
espacios de eventos. Centraliza comercial, agenda, operación, documentos, cobros, costos, recursos
y analítica. Es completamente independiente de RFM Core.

El destino funcional está en [PRODUCT_BLUEPRINT.md](product/PRODUCT_BLUEPRINT.md) y la secuencia
vigente en [PRODUCT_DELIVERY_ROADMAP.md](product/PRODUCT_DELIVERY_ROADMAP.md). Este Handoff no los
duplica: registra cómo continuar desde el checkout real.

## Arquitectura y estructura actual

- Monorepo y monolito modular.
- Backend Django 5.2/DRF bajo `apps/api`, API JSON `/api/v1` y OpenAPI generado.
- Frontend React 19, TypeScript estricto y Vite bajo `apps/web`.
- PostgreSQL 17 en todos los ambientes; localmente PostgreSQL, ClamAV y el worker documental
  canónico usan Docker/Compose.
- Sesiones Django de servidor y CSRF; autorización backend-first por capacidades.
- Datos privados dentro de `authorized_tenant_scope` y RLS `ENABLE` + `FORCE`.
- `docs/product`: destino, roadmap y contratos funcionales.
- `docs/adr`: decisiones arquitectónicas aceptadas.
- `docs/architecture`: plataforma, toolchains, evidencia histórica y cutover.
- `docs/brand`: copias oficiales de marca; no editar silenciosamente.
- `tools/clean_workspace.py`: limpieza segura de artefactos regenerables.

## Módulos implementados

- `claridez.identity`: usuario global, sesiones, contraseñas, correo local y Axes.
- `claridez.organizations`: organizaciones, membresías, settings, sedes, espacios, capacidades y
  scope tenant.
- `claridez.catalog`: tipos de evento, servicios, productos, paquetes, revisiones, precios y
  vigencias.
- `claridez.people`: identidad maestra de persona, revisiones, búsqueda, aliases, fusión lógica y
  consentimiento append-only; contactos actuales e históricos con propiedad canónica única por
  tenant bajo un advisory lock transaccional común; conserva las tablas físicas históricas de
  persona.
- `claridez.commercial`: solicitudes como única oportunidad, historial comercial append-only y
  cotizaciones versionadas con catálogo/ad hoc; conserva la autoridad de la evidencia comercial y
  delega agenda y reservas mediante el puerto público de scheduling.
- `claridez.scheduling`: propietario lógico de `Reservation` sobre la tabla física conservada
  `commercial_reservation`; políticas temporales, disponibilidad, holds, reservas confirmadas,
  bloqueos, reprogramación por sucesora, cancelación, asignación temporal unificada, expiración
  determinista, historia canónica append-only y exportación iCalendar.
- `claridez.crm`: composición mediante puertos públicos estrechos; identidad y oportunidades usan
  proyecciones inmutables, y consentimiento usa valores serializados sin exponer ORM ni
  `QuerySet`; vistas integrales, interacciones inmutables, correcciones enlazadas por conjunto
  canónico que conservan su oportunidad, tareas con historial, próxima acción determinista e
  indicadores.
- `claridez.operations`: preparación uno-a-uno, checklist, responsables, ejecución, transiciones y
  coordinación atómica con comercial.
- `claridez.documents`: plantillas/versiones; expediente por raíz; instrumentos y emisiones
  inmutables; snapshot contractual y artefacto PDF con hashes separados; aceptación propia;
  grants/challenges externos; archivos privados; retención/holds; integridad, malware y jobs
  durables PostgreSQL mediante puertos estrechos.
- `claridez.receivables`: obligación única por raíz confirmada, snapshot comercial, calendario
  operativo versionado, pagos externos declarados, aplicaciones, ajustes, reversos, devoluciones,
  recibos lógicos, estado de cuenta, saldo derivado y antigüedad; ledger append-only con
  idempotencia, locks, guardianes PostgreSQL, RLS y puertos inmutables.
- `claridez.finance`: proyección económica mínima, costos directos planificados/reales, evidencia y
  baseline operativa, gastos variables/recurrentes con asignaciones, presupuestos, caja operativa,
  reconocimiento, periodos y cierres; hechos y correcciones append-only, sede histórica, RLS,
  idempotencia y locks internos deterministas.
- `claridez.resources`: proveedores y contactos canónicos existentes, términos/ofertas con
  historia, unidades y conversiones, recursos suministrados y físicos, ubicaciones, compras y
  recepciones, activos serializados, movimientos/saldos, requerimientos/faltantes,
  reservas/asignaciones/capacidad, custodia, mantenimiento e indisponibilidad; ledger append-only,
  RLS, idempotencia, locks y guardianes PostgreSQL.
- Web: autenticación, selector organizacional, agenda responsive diaria/semanal/mensual con
  filtros y carriles/listas, políticas, bloqueos, reprogramación guiada, cancelación, historia y
  exportación; solicitudes/cotizaciones/reservas, operación, configuración/catálogo y CRM con
  bandeja, persona integral, timeline, interacciones, tareas, consentimiento y fusión; backoffice
  documental y experiencia externa mínima responsive para lectura, descarga y aceptación; cartera,
  vencimientos, movimientos, pagos, correcciones, devoluciones, recibos y estado de cuenta para
  roles financieros, con resumen acotado para comercial; control financiero operativo con
  baseline, variación, gastos, caja, presupuesto, margen, rentabilidad, cierres y exportación;
  proveedores, recursos, existencias/ubicaciones, movimientos, compras/recepciones,
  asignación/disponibilidad por evento y mantenimiento/indisponibilidad, con faltantes y conflictos
  explícitos.

No existe aún implementación funcional de P13 en adelante. No hay contabilidad formal ni portal
completo, ni proveedores productivos de almacenamiento/correo/identidad, staging o producción.

## Estado exacto

- I0–I4, I5.1, 5.1.1, 5.1.2, I5.2 y P6–P12: completadas y validadas localmente.
- ADR 0021 gobierna la implementación P12 cerrada localmente. ADR 0022 y
  `P13_ADVANCED_OPERATIONS_SPECIFICATION.md` formalizan la arquitectura y el contrato P13; P13
  continúa sin modelos, migraciones, capabilities ejecutables, servicios, endpoints ni frontend.
- El guardián PostgreSQL y el procedimiento de cutover 5.2 están implementados y probados
  localmente.
- El cutover de 5.2 sobre un entorno destino, el cierre real de tráfico y la reapertura no se han
  ejecutado.
- La consolidación del 1 de agosto incorpora limpieza oficial, contrato operativo coherente y las
  tres fuentes maestras.
- P6 incorpora configuración funcional, sedes/espacios, catálogo versionado, paquetes explícitos,
  precios con vigencias y su uso real en comercial, agenda y proyección operativa.
- La auditoría postimplementación P6 añadió integridad PostgreSQL para impedir por ORM bulk o SQL
  directo cabezales sin historia coherente, revisiones arbitrarias y composición divergente.
- `CatalogItemRevision.package_components` es el snapshot histórico canónico; las filas
  `PackageComponent` son su proyección relacional obligatoriamente equivalente al commit.
- P7 separa propiedad de estado entre `claridez.people` y `claridez.crm` sin ciclos; adopta
  `Person`/`PersonRevision` sin copiar filas ni renombrar `commercial_person*`, y conserva
  `EventRequest` como única oportunidad bajo autoridad `sales:*`.
- Interesado y cliente son condiciones derivadas; cliente exige evidencia de una primera reserva
  confirmada y no elimina el historial previo. Interacciones, consentimiento e historial comercial
  son append-only; las correcciones enlazan nueva evidencia y el backfill no inventa transiciones.
- La fusión lógica autorizada para propietario y administrador conserva FKs históricas, aliases,
  auditoría, resolución canónica, idempotencia y agregación sin doble conteo. Anonimización y
  eliminación siguen sin capacidades ni endpoints.
- El cierre correctivo P7 elimina consultas/importaciones ORM directas desde CRM hacia `people` y
  `commercial`; conserva aliases al cambiar contactos; impide reutilización actual o histórica;
  corrige interacciones y consentimientos dentro de fusiones encadenadas; aplica la revocación
  efectiva de ADR 0015; persiste razones de cancelación; evita revisiones vacías; y ordena toda
  próxima acción por `next_contact_at` o, en su ausencia, `due_at`.
- El cierre focalizado final serializa con un advisory lock transaccional común por organización
  toda escritura de teléfono o correo en `commercial_person` y
  `people_personcontactalias`; los UUID de organización se bloquean en orden estable y luego se
  comprueban de nuevo valores actuales e históricos. Los casos concurrentes cubren
  `QuerySet.update` contra SQL directo para teléfono y `bulk_update` contra `save()` ORM para
  correo; la operación rival recibe `23505` y se conserva un solo propietario canónico.
- La corrección de una interacción vinculada, aunque la evidencia original pertenezca a una persona
  fuente ya fusionada, conserva el `event_request_id` original y registra la nueva evidencia sobre
  la persona canónica. El navegador real validó 1440×900 y 390×844 con búsqueda, selección,
  inversión de dirección, resumen, conflicto por revisión obsoleta, nueva confirmación, mensajes,
  scroll y ausencia de overflow horizontal; no fue necesario cambiar CSS.
- P8 adopta `Reservation` mediante migración de estado sin copiar filas ni renombrar
  `commercial_reservation`. Una única exclusión GiST sobre `ScheduleAllocation` protege
  organización, espacio e intervalo `[)` para reservas y bloqueos. Las cadenas tenant-aware,
  equivalencia de proyección, expiración determinista, idempotencia e historia `ScheduleEvent`
  append-only están protegidas por constraints, triggers, privilegios, advisory locks ordenados y
  `ENABLE` + `FORCE RLS`.
- La reprogramación crea una reserva sucesora en la misma transacción, conserva evidencia
  comercial y coordina `EventPreparation`: la anterior queda terminal, la nueva baseline nace del
  snapshot aceptado y solo los ítems libres permitidos se trasladan pendientes con procedencia.
  CRM deriva “requiere revisión” desde una proyección inmutable sin mutar tareas ni importar ORM de
  scheduling.
- P9 separa `ContractualRecord`, `ContractualInstrument`, `IssuedInstrumentVersion`,
  `GeneratedArtifact` y `AcceptanceEvidence`. La cotización aceptada es la única fuente comercial;
  el snapshot semántico y el PDF exacto tienen SHA-256 distintos y ninguna aceptación se transfiere
  a otros bytes. Reprogramación/cancelación solo se consumen desde scheduling y no alteran P8.
- El renderer canónico usa WeasyPrint 69.0 dentro de Debian 12/Python 3.13.14 fijados por digest,
  fuentes/assets fijados y fetcher fail-closed. El spike repitió un PDF realista de 1.060.929 bytes
  con SHA-256 `93ee73e8fdddcf87d47a5fd1860e38b79cac95260dfb0964731ec44ffcb23d66` y bloqueó HTTP/`file://`.
- El puerto de almacenamiento privado incluye filesystem local y adaptador S3-compatible
  create-only. ClamAV 1.4.6/firma 28087 distinguió limpio, EICAR y timeout; solo `clean` permite
  descargar uploads externos PDF/JPEG/PNG. `DocumentJob` implementa `SKIP LOCKED`, leases,
  at-least-once, idempotencia, backoff, retries y fallo terminal append-only.
- P9 aplica nueve capabilities documentales propias. Propietario/administrador tienen la matriz
  completa; comercial recibe la superficie aprobada; operaciones solo lectura/descarga con
  relación `EventPreparation` real; finanzas no recibe capacidades documentales. No existe
  destrucción física ni capability interna para aceptar por el cliente.
- Ocho migraciones documentales pasan desde cero y desde P8 final sin backfill ficticio. Las 22
  tablas privadas tienen `ENABLE` + `FORCE RLS`, FKs tenant-aware y privilegios mínimos; pruebas
  con `claridez_app`, ORM, bulk, SQL directo y dos tenants bloquean acceso cruzado.
- `npm run check:all` pasó el 13 de agosto con los toolchains fijados: 194 pruebas API no
  integración, 72 de integración PostgreSQL y 23 frontend, además de locks, formato, lint, tipos,
  migraciones, OpenAPI y builds. `npm run audit` terminó sin vulnerabilidades conocidas tras
  actualizar `pypdf` a 6.15.0; `git diff --check` se repite en el cierre final.
- CI #23, run `31757547140`, fue observado exitosamente sobre
  `dab6b7ea367ce3d80dd375f1c41f048d5a9d9906`: completó Calidad, PostgreSQL 17 y Auditoría de
  dependencias. Esta evidencia no afirma staging, producción, despliegue ni cutover.
- El navegador real comprobó el enlace documental inválido en viewport normal y 390×844: falló
  cerrado sin revelar documento ni organización y sin errores de consola. También comprobó que la
  ruta interna conserva el inicio de sesión normal; los flujos autenticados completos quedan
  cubiertos por las pruebas HTTP y de componentes, no se presentan como recorrido manual.
- P10 materializa exactamente una obligación por `(organization_id, root_reservation_id)` desde la
  primera confirmación y copia moneda, subtotal, descuentos, total, versión y términos estructurados
  existentes de la `QuotationVersion` aceptada. Un coordinador neutral ejecuta pago de anticipo,
  confirmación, obligación, aplicación y consecuencias P8 en una transacción; waiver confirma y
  crea obligación sin inventar pago. Ese coordinador consume P10 exclusivamente mediante
  `claridez.receivables.public`: el puerto encapsula idempotencia, validación y registro del pago,
  creación/obtención de obligación, aplicación y finalización, y devuelve DTO congelados sin ORM ni
  `.pk` externos. Reprogramar conserva la raíz y cancelar solo marca revisión.
- El calendario de cobranza es operativo, parcial y versionado; nunca deduce vencimientos de fecha
  de evento, confirmación, aceptación o documento. La antigüedad conserva días exactos y clasifica
  vigente, 1–30, 31–60, 61–90, más de 90 y sin vencimiento con fecha local organizacional.
- `ReceivedPayment` y `PaymentApplication` son hechos distintos. El excedente queda sin aplicar;
  ajustes, reversos completos y devoluciones externas son contramovimientos append-only. El saldo
  se reconstruye como obligación original más ajustes netos, menos aplicaciones vigentes, más
  importes reabiertos por devoluciones; los reversos anulan el efecto exacto de su objetivo.
- Las confirmaciones 5.1 coherentes `external_deposit` se adoptan una vez por raíz como pago
  `legacy_5_1_confirmation` con evidencia `internal_report` y se aplican a la obligación. Waivers no
  crean pago; datos incoherentes quedan en revisión y todos los campos originales permanecen como
  evidencia histórica no autoritativa para saldo.
- P10 expone nueve capabilities propias. Propietario, administrador y finanzas reciben la matriz
  completa; comercial solo `receivables:read_summary` bajo relación real; operaciones no recibe
  acceso. Sesión, CSRF, membresía, scope tenant, capability y relación siguen siendo requisitos
  conjuntivos.
- La plataforma documental incorpora archivos privados y artefactos generados genéricos por
  puerto estrecho para comprobantes y PDF de recibos, reutilizando object storage, hash, cuarentena,
  malware, renderer y jobs P9. `receivables` conserva toda semántica financiera; el PDF no crea
  pago ni saldo y no se fabrican expedientes contractuales.
- Cinco migraciones de receivables y dos extensiones documentales cubren instalación desde cero y
  P9 final. Preflight, backfill determinista, verificación y guardianes diferidos preservan raíces
  reprogramadas/canceladas, no inventan fechas y resisten ORM, bulk, SQL directo y `claridez_app`.
- `npm run check:all` pasó el 17 de agosto con 207 pruebas API no integración, 81 de integración
  PostgreSQL y 25 frontend, además de locks, formato, lint, tipos, migraciones, OpenAPI y builds.
  `npm run audit` no encontró vulnerabilidades conocidas tras actualizar el lock transitivo de
  `sqlparse` a 0.6.0 y `git diff --check` fue correcto. La
  validación real de Cartera a 390×844 observó 390 px de viewport y 375 px de contenido, sin
  desbordamiento horizontal. Todo es evidencia local; no afirma CI remota nueva ni despliegue.
- El cierre focalizado P10 del 22 de agosto retiró de `claridez.application` los imports directos de
  `receivables.errors`, `models`, `money` y `services`, y corrigió el import de error en la vista
  comercial para usar el puerto público. Un guard AST rechaza futuras dependencias productivas
  externas distintas de `claridez.receivables.public`. Las pruebas dirigidas cerraron con 20 casos
  API/capabilities y 8 casos PostgreSQL P10; `npm run check:all` pasó con 208 pruebas API no
  integración, 81 de integración PostgreSQL y 25 frontend, además de migraciones sin cambios,
  formato, lint, tipos, OpenAPI y builds correctos. No cambió la ruta, payload, capabilities,
  transacción, locks, guardianes, migraciones ni frontend visible.
- El cierre de seguridad posterior actualizó exclusivamente Django de 5.2.16 a 5.2.17, sin
  upgrades colaterales en `uv.lock`. `npm run check:all` completó con 208 pruebas API, 25 pruebas
  frontend y 81 pruebas de integración PostgreSQL aprobadas; `npm run audit` no encontró
  vulnerabilidades en Python ni en el workspace web.
- P11 establece `claridez.finance` como autoridad exclusiva del control financiero operativo. Una
  venta aceptada es evidencia económica comercial; P10 conserva obligación y cobro; la entrada de
  caja se clasifica desde sus contribuciones tipadas; el ingreso base solo nace cuando operations
  evidencia `execution_completed`. Los pagos no se convierten en ingreso y finance no copia
  movimientos de receivables ni crea un ledger paralelo.
- La última revisión que ganó realmente el lock de la preparación antes de `execution_started` se
  captura como baseline inmutable. PostgreSQL rechaza toda inserción posterior, aunque use
  `published_at` retrodatado y llegue por ORM, bulk o SQL con `claridez_app`. `operations.public`
  expone DTO congelado de inicio/finalización y permite lock externo solo para esa invariante;
  finance usa advisory locks propios y deterministas para sus demás comandos. La proyección
  económica comercial excluye PII, notas y detalle innecesario.
- `root_reservation_id` conserva la identidad estable ante reprogramaciones. Cada costo real y cada
  asignación de gasto a evento congela el `venue_id` de su hecho económico; una reprogramación
  posterior no los traslada. El ingreso se atribuye a la sede de la reserva que alcanzó
  `execution_completed`.
- Periodos cerrados no se reabren ni reescriben. Los hechos tardíos conservan fecha económica y se
  registran en el siguiente periodo abierto como ajuste explícito de periodo anterior. Una fuente
  P10 pertenece al snapshot solo si su tipo e identificador exactos quedaron en sus referencias;
  un timestamp anterior no prueba inclusión. Los cierres conservan cutoffs, referencias y hashes,
  sin `SourcePeriodRegistration` ni índice espejo.
- Gastos manuales y recurrentes comparten `ExpenseOccurrence` con procedencia explícita;
  asignaciones, costos, caja, reconocimiento y correcciones son hechos tipados. Los ajustes de
  reconocimiento no implementan penalidades, anticipos perdidos, créditos ni deber de devolución.
  No existe dependencia de catálogo, libro mayor, cuenta bancaria, FX ni contabilidad formal.
- La caja de un gasto conserva importes explícitos por cada scope asignado; no prorratea. Salidas,
  recuperaciones y correcciones recomprueban suma exacta y límites por scope bajo un lock interno
  del gasto. Overview y CSV conservan raíz/sede/periodo y reconcilian con el flujo global.
- P11 añade doce capabilities. Propietario, administrador y finanzas reciben la matriz completa;
  operaciones solo `finance:submit_evidence`; comercial no recibe acceso financiero. Las 20 tablas
  privadas usan FKs tenant-aware, `ENABLE` + `FORCE RLS`, privilegios mínimos e inmutabilidad; la
  API solo expone consultas y comandos explícitos, sin `DELETE`, `PATCH` libre ni CRUD de hechos.
- El cierre correctivo del 23 de agosto sincronizó 88 paquetes Python con el lock y 253 paquetes
  npm; `npm ci` reportó cero vulnerabilidades. El reset protegido y la migración desde cero
  aplicaron todo el historial hasta `finance.0005`; la prueba P10-final→P11 confirmó
  rollback/reaplicación. La puerta aprobó 217 pruebas API no integración con 76% de cobertura, 28
  frontend y una repetición completa de 91 integraciones PostgreSQL, además de locks, migraciones
  sin cambios, formato, lint, mypy sobre 300 archivos, TypeScript, OpenAPI sin warnings y build
  Vite. La primera pasada integró 90/91 por un deadlock transitorio P8 hold↔block; la prueba aislada
  y la repetición completa 91/91 pasaron sin cambios P8. Las nuevas pruebas observaron SQL
  retrodatado, carrera publicación↔inicio, commits P10 tardíos de pago/devolución y caja de gasto
  multievento/multisede con salida, recuperación, corrección, filtros y CSV. La evidencia es local;
  no incluye navegador manual, CI remota, despliegue ni cutover de un entorno destino.
- La comprobación correctiva migró hasta `finance.0005` y ejecutó después
  `tools/local_database.py prepare`. La política explícita por clase de tabla preservó
  `SELECT/INSERT` sin `UPDATE/DELETE/TRUNCATE` para `claridez_app` en las 20 tablas privadas
  finance; la conexión y una consulta normal con el rol de aplicación continuaron operativas.
- P12 establece `claridez.resources` como autoridad de proveedores, recursos, abastecimiento e
  inventario operativo. `SupplierContact` solo enlaza `Person` canónicas existentes; operaciones y
  finanzas no reciben `person:manage`. Las unidades base son canónicas y quedan inmutables tras el
  primer hecho; `catalog.unit_label` continúa descriptivo. `supplied_service`, `consumable`,
  `reusable_pool` y `serialized_asset` tienen reglas separadas de disponibilidad y faltantes.
- `StockMovement` es la autoridad append-only de cantidad en unidad base: entradas y devoluciones
  suman, salidas restan sin negativo, ajustes declaran dirección/razón, traslados usan dos piernas
  atómicas y correcciones compensan sin reescribir. La confirmación `goods_received` crea en la
  misma transacción una única entrada física tenant-aware; `service_fulfilled` no crea stock y los
  serializados cuadran recepción, movimiento y unidades individuales. Guardianes diferidos,
  exclusiones GiST, advisory/row locks y proyecciones protegidas cubren ORM, bulk y SQL directo.
- Resources usa exclusivamente `[starts_at, ends_at)` de scheduling. Cancelación y expiración
  liberan capacidad en la misma transacción, y la reprogramación coordina sucesora, consecuencias
  Operations y asignaciones P12 seleccionadas; los hechos físicos ejecutados no se trasladan.
  Finance incorpora procedencia `resources_receipt` y `FinancialSourceReference` cerrada a
  `resources_receipt_line`, con cardinalidad 0..1 hacia costo real o gasto y sin caja automática.
  La dependencia física de esquema es `finance.0006` → `resources.0001`; los dominios se coordinan
  por DTO inmutables y puertos públicos estrechos.
- El cierre correctivo del 24 de agosto añadió `resources.0002`: `reusable_pool` calcula capacidad
  solo contra reservas/custodias e indisponibilidades solapadas en intervalo y ubicación; los
  activos serializados conservan únicamente estado físico `available/custody/retired`, mientras
  asignaciones e indisponibilidades gobiernan la ocupación temporal. Reservas disjuntas coexisten,
  GiST y guardianes rechazan solapamientos, y cerrar mantenimiento no reescribe el estado físico ni
  elimina otras restricciones temporales.
- Comercial ya no recibe disponibilidad global en `resources/overview`; consulta únicamente un
  recurso relacionado con una solicitud y su reserva vigente mediante un DTO público inmutable de
  scheduling. Contextos, recursos y organizaciones no relacionados fallan cerradamente.
- P12 añade quince capabilities atómicas. Propietario y administrador reciben la matriz completa;
  comercial solo `resource:read_availability`; operaciones y finanzas reciben exactamente sus
  capacidades explícitas de ADR 0021. `purchase:materialize_finance` exige además
  `finance:record_actuals` o `finance:allocate_expenses`, según el destino. Las 23 tablas privadas
  resources usan FKs tenant-aware, `ENABLE` + `FORCE RLS`, privilegios mínimos, idempotencia y
  ausencia de `DELETE/TRUNCATE` para hechos/ledgers.
- La puerta correctiva repetida `npm run check:all` aprobó 236 pruebas API no integración en
  452,35 s, 30 pruebas frontend en 13 archivos y 102 integraciones PostgreSQL en 1726,46 s; también
  aprobó locks, migraciones sin cambios, formato, lint, mypy sobre 318 archivos, TypeScript, system
  checks, OpenAPI sin warnings y build Vite. Una primera pasada integró 101/102 por un deadlock
  transitorio de la prueba P8 hold↔block; la prueba pasó 3/3 aislada y la repetición completa
  102/102 sin cambios P8. La auditoría del cierre inicial permaneció sin vulnerabilidades conocidas.
  La evidencia es local; no incluye navegador manual, CI remota, commit, push, despliegue ni
  cutover.
- Los verificadores locales de cutover 5.2 y P8 devolvieron `status=ok`; el de scheduling observó
  cuatro organizaciones y tres reservas sintéticas/locales. No se ejecutó cutover sobre un entorno
  destino. El navegador real validó 1440×900 y 390×844: día, semana, mes, filtros, creación y
  conflicto de bloqueo, liberación, hold, confirmación, reprogramación, comparación, consecuencias
  operativas, cancelación, historia, `.ics`, teclado y scroll sin overflow horizontal ni errores de
  consola.

## Decisiones cerradas

- Independencia, monorepo, monolito modular y tecnologías: ADR 0001–0002.
- Multiempresa, PostgreSQL y configuración local: ADR 0003 y 0006–0008.
- Aplicación tenant-aware más RLS y scope transaccional: ADR 0009.
- Identidad local y sesiones de servidor: ADR 0010.
- Organizaciones, membresías, último propietario y autorización: ADR 0011.
- Agenda/dinero comercial y coordinación comercial-operaciones: ADR 0012–0013.
- Multi-espacio, configuración funcional, catálogo, backfill y frontera MFA de P6: ADR 0014.
- Propiedad `people`/CRM, autoridad comercial, historial, fusión, consentimiento y capacidades P7:
  ADR 0015.
- Propiedad de scheduling, defensa temporal unificada, cadenas, expiración, historia, locks y
  cutover: ADR 0016.
- Dominio documental único, expediente contractual por raíz, instrumentos/versiones, aceptación,
  acceso externo, autorización conjuntiva y retención sin destrucción física: ADR 0017.
- Entorno canónico de render, checksums separados, almacenamiento privado, uploads externos,
  malware y primer mecanismo asíncrono durable: ADR 0018.
- Autoridad de `claridez.receivables`, obligación por primera confirmación de raíz, coordinación
  transaccional, ledger append-only, saldo derivado, migración 5.1 y capacidades P10: ADR 0019.
- Autoridad de `claridez.finance`, reconocimiento operativo, sede histórica, baseline, hechos
  tardíos, cierres, locks y frontera estricta con P10: ADR 0020.
- Autoridad de `claridez.resources`, unidades, recepción/inventario, capacidad concurrente,
  consecuencias de scheduling y procedencia financiera P12: ADR 0021; implementado localmente.
- Autoridad de operación avanzada, planes/snapshots, fases, incidencias, cambios, ventanas de
  recursos, cierre postevento y su integridad con 5.2/Scheduling/Resources: ADR 0022; arquitectura
  aceptada, aún no implementada.
- Comportamiento exacto implementado: especificaciones 5.1, 5.2, P8 y contrato funcional P11. El
  contrato funcional P13 está aprobado como fuente previa a implementación; P9 se rige por ADR
  0017–0018, Roadmap y el plan consolidado aprobado.
- Destino funcional completo y secuencia: Blueprint y Roadmap.

## Decisiones diferidas

- Proveedores de staging/producción, correo, WhatsApp, almacenamiento y malware gestionado;
  dimensionamiento/observabilidad productivos del renderer y worker.
- MFA productiva, OIDC y `ExternalIdentity`; identidad/autorización siguen siendo locales.
- P9 implementa el ledger durable PostgreSQL y runner canónico; dimensionamiento y una eventual
  cola/broker externos continúan abiertos detrás del puerto operativo.
- Datos legales obligatorios, representación, política de materialidad, política detallada de
  privacidad/retención, mecanismos de atribución superiores y firma electrónica acreditada. El
  método base se identifica únicamente como aceptación electrónica propia.
- Facturación electrónica, contabilidad formal, aplicaciones nativas, marketplace, IA avanzada,
  expansión internacional y constructor web libre.
- Planes y cobro de suscripciones de Claridez, posteriores al producto funcional.
- Penalidades por cancelación, pérdida de anticipos, obligación jurídica de devolver, créditos a
  favor, aplicación de sobrepagos a otros eventos, consecuencias contractuales de revisar
  vencimientos y retención jurídica definitiva de comprobantes/recibos. P10 no automatiza ninguna.
- Conciliación bancaria, ejecución real de reembolsos, conversión de moneda, facturación
  electrónica, libro mayor, cuentas bancarias y contabilidad formal.

## Fuentes de verdad y precedencia

1. `AGENTS.md` define reglas operativas obligatorias.
2. Los ADR aceptados gobiernan su decisión arquitectónica concreta.
3. `PRODUCT_BLUEPRINT.md` gobierna el destino y los límites del producto terminado.
4. Las especificaciones funcionales aprobadas gobiernan el flujo exacto que describen.
5. `PRODUCT_DELIVERY_ROADMAP.md` gobierna estado, orden y siguiente etapa.
6. Este Handoff resume el estado observado; debe actualizarse al cerrar cada etapa.
7. `PRODUCT_BASELINE.md` e `INITIALIZATION_ROADMAP.md` son antecedentes históricos.
8. Fundamentos de marca gobiernan propósito/lenguaje y Dirección Visual solo materias visuales.

Si dos fuentes se contradicen fuera de su ámbito, se detiene únicamente la decisión afectada y se
resuelve antes de implementarla.

## Lectura inicial obligatoria

1. `AGENTS.md`.
2. `docs/product/PRODUCT_BLUEPRINT.md`.
3. `docs/product/PRODUCT_DELIVERY_ROADMAP.md`.
4. `docs/PROJECT_HANDOFF.md`.
5. Especificaciones 5.1/5.2/P8/P11 y ADR aplicables, incluidos ADR 0016–0021; P12 no puede redefinir
   la evidencia comercial, documental, de agenda, cartera o control financiero ya cerrada.
6. Código, migraciones, pruebas, Git y configuración ejecutable; nunca confiar solo en documentos.

## Entorno y comandos oficiales

Requisitos fijados:

- Python 3.13.14 y uv 0.12.0.
- Node.js 24.18.1 y npm 11.16.0.
- Docker Desktop/Compose y PostgreSQL 17.10 según `compose.yaml`.
- `.env` local válido creado desde `.env.example`; nunca versionarlo.

Instalación/sincronización:

```text
uv --directory apps/api sync --locked
npm ci
```

Puertas desde la raíz:

```text
npm run clean
npm run format
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
npm run check
npm run check:all
npm run audit
```

`clean` preserva entornos, dependencias, `.env`, bases, secretos y archivos del usuario. `check:all`
requiere PostgreSQL local preparado. `audit` usa servicios de red. No ejecutar
`docker compose down -v` como reset normal.

El perfil documental local se opera con `npm run documents:start|status|logs|stop`; su runbook de
render, almacenamiento, backup/restauración, malware y jobs está en
[DOCUMENT_PLATFORM.md](architecture/DOCUMENT_PLATFORM.md).

## Modelo permanente de trabajo

1. Leer Blueprint, Roadmap y Handoff.
2. Confirmar Git, código, migraciones, configuración y pruebas reales.
3. Identificar la siguiente etapa incompleta del Roadmap.
4. Presentar solo un plan breve y decisiones verdaderamente bloqueantes.
5. Recibir aprobación de implementación.
6. Implementar la etapa completa sin adelantar la siguiente.
7. Ejecutar validaciones proporcionales, incluidas PostgreSQL/RLS y UI cuando apliquen.
8. Actualizar Roadmap y Handoff según lo observado.
9. Reportar el resultado visible y los límites reales.
10. Indicar exactamente la etapa siguiente.

No se exige una especificación extensa antes de cada módulo. Un ADR se reserva para decisiones
transversales, irreversibles o relacionadas con datos, seguridad, infraestructura, concurrencia o
límites arquitectónicos. Una nota corta de etapa puede aclarar contratos reversibles cuando haga
falta.

## Próximo trabajo

P12 — Proveedores, recursos e inventario está cerrada localmente bajo ADR 0021. ADR 0022 y el
contrato funcional breve ya formalizan P13 sin implementarla. El siguiente paso exacto es recibir
aprobación explícita para la **implementación de P13 — Operación avanzada** antes de crear modelos,
migraciones, capabilities ejecutables, servicios, endpoints o frontend P13.

## Riesgos actuales

- Un despliegue futuro debe ejecutar el cutover 5.2 completo; no admite convivencia 5.1/5.2.
- Ese despliegue debe respetar también el orden multi-espacio, las adopciones de estado P7/P8 y las
  comprobaciones de ADR 0014–0016. P8 exige preflight, ventana sin tráfico, respaldo, verificadores
  5.2/P8 y rollback documentado; el ensayo local no sustituye esa autorización operativa.
- Antes de desplegar la migración correctiva P7 se deben auditar correos actuales duplicados o no
  canónicos del entorno destino. La migración falla cerrada en esos casos y no reasigna evidencia
  de contacto de manera automática.
- Acciones privilegiadas de membresías continúan sin UI productiva y no deben abrirse sin MFA.
- Correo es local; recuperación/verificación externas no están listas para clientes reales.
- La política legal definitiva de retención, anonimización y eliminación de personas sigue
  diferida; P7 no concede capacidades ni endpoints para ejecutarlas.
- Antes de desplegar P9 se debe seleccionar y ensayar el almacenamiento/backup productivo, operar
  scanner y worker con observabilidad, fijar secretos estables y aprobar las políticas jurídicas
  aplicables. La disposición física permanece ausente, no meramente deshabilitada.
- Antes de desplegar P10 se debe ejecutar el preflight sobre confirmaciones 5.1 reales, verificar
  cardinalidades e importes, respaldar, bloquear tráfico durante el cutover y revisar toda evidencia
  clasificada como incoherente. La migración local no prueba los datos de un entorno destino.
- Antes de desplegar P11 se deben verificar moneda/configuración por organización, rangos de
  periodos, cutoffs de receivables, raíces/sedes históricas y ausencia de cierres productivos
  incompatibles; se requiere respaldo y ensayo de migración P10-final. La validación local no prueba
  datos ni operación de un entorno destino.
- El run remoto 22 falló históricamente sobre `36e41ef`; CI #23, run `31757547140`, fue observado
  verde sobre `dab6b7ea367ce3d80dd375f1c41f048d5a9d9906`. No existe evidencia de staging,
  producción, despliegue ni cutover.

## Reporte de cierre obligatorio

Cada etapa debe cerrar con:

1. diagnóstico y alcance aprobado;
2. resultado visible para el usuario;
3. archivos creados, modificados y eliminados;
4. migraciones, contratos y decisiones afectadas;
5. comandos exactos y resultados observados, separando pruebas dirigidas, suite completa, CI y
   despliegue;
6. seguridad, tenancy, concurrencia, privacidad y compatibilidad verificadas;
7. limitaciones, riesgos y validaciones omitidas;
8. Roadmap y Handoff actualizados;
9. siguiente etapa exacta y si requiere aprobación o investigación.

## Cómo actualizar este Handoff

Al finalizar una etapa, cambiar fecha, etapa activa/siguiente, módulos, estado, decisiones y riesgos
solo con evidencia del checkout y de las validaciones ejecutadas. Enlazar nuevas fuentes sin copiar
su contenido completo. Mover la etapa completada en el Roadmap, registrar allí su resultado y dejar
una sola siguiente etapa. Ejecutar
formato, enlaces, UTF-8/LF y puertas oficiales antes de entregar la actualización.
