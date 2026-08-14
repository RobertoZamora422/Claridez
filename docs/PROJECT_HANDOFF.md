# Claridez — Handoff del proyecto

- **Fecha de corte:** 13 de agosto de 2026
- **Etapa funcional activa:** ninguna; P9 está completada y validada localmente
- **Siguiente etapa:** P10 — Cobros y cuentas por cobrar; pendiente de plan y aprobación

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
- Web: autenticación, selector organizacional, agenda responsive diaria/semanal/mensual con
  filtros y carriles/listas, políticas, bloqueos, reprogramación guiada, cancelación, historia y
  exportación; solicitudes/cotizaciones/reservas, operación, configuración/catálogo y CRM con
  bandeja, persona integral, timeline, interacciones, tareas, consentimiento y fusión; backoffice
  documental y experiencia externa mínima responsive para lectura, descarga y aceptación.

No existen aún los módulos de P10 en adelante. No hay módulos financieros ni portal completo, ni
proveedores productivos de almacenamiento/correo/identidad, staging o producción.

## Estado exacto

- I0–I4, I5.1, 5.1.1, 5.1.2, I5.2, P6, P7, P8 y P9: completadas y validadas localmente.
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
- El navegador real comprobó el enlace documental inválido en viewport normal y 390×844: falló
  cerrado sin revelar documento ni organización y sin errores de consola. También comprobó que la
  ruta interna conserva el inicio de sesión normal; los flujos autenticados completos quedan
  cubiertos por las pruebas HTTP y de componentes, no se presentan como recorrido manual.
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
- Comportamiento exacto implementado: especificaciones 5.1, 5.2 y P8; P9 se rige por ADR
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
5. Especificaciones 5.1/5.2/P8 y ADR aplicables, incluidos ADR 0016–0018; P10 no puede redefinir la
   evidencia comercial, documental o de agenda ya cerrada.
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

P9 está cerrada localmente. La siguiente etapa del Roadmap es **P10 — Cobros y cuentas por cobrar**.
Antes de implementarla corresponde revisar las fuentes maestras y presentar únicamente su plan
breve y decisiones realmente bloqueantes; P10 no está autorizada por este cierre.

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
- Se observó el run remoto de calidad 22 fallido sobre `36e41ef` por tres suppressions de mypy
  innecesarias en Linux. El cierre focalizado las eliminó y pasó los gates locales completos; no se
  ha observado todavía un run remoto verde ni existe ambiente desplegado.

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
