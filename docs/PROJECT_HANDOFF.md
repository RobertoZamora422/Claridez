# Claridez — Handoff del proyecto

- **Fecha de corte:** 3 de agosto de 2026
- **Etapa funcional activa:** ninguna; P7 cerró su corrección y está completada localmente
- **Siguiente etapa:** P8 — Agenda y reservas avanzadas

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
- PostgreSQL 17 en todos los ambientes; localmente solo PostgreSQL usa Docker.
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
- `claridez.commercial`: solicitudes como única oportunidad, historial comercial append-only,
  cotizaciones versionadas con catálogo/ad hoc, disponibilidad por espacio y reservas.
- `claridez.crm`: composición mediante puertos públicos estrechos; identidad y oportunidades usan
  proyecciones inmutables, y consentimiento usa valores serializados sin exponer ORM ni
  `QuerySet`; vistas integrales, interacciones inmutables, correcciones enlazadas por conjunto
  canónico que conservan su oportunidad, tareas con historial, próxima acción determinista e
  indicadores.
- `claridez.operations`: preparación uno-a-uno, checklist, responsables, ejecución, transiciones y
  coordinación atómica con comercial.
- Web: autenticación, selector organizacional, agenda, solicitudes/cotizaciones/reservas,
  operación, configuración/catálogo y CRM responsive con bandeja, persona integral, timeline,
  interacciones, tareas, consentimiento y fusión mediante búsqueda y selección, sin UUID ni
  revisiones manuales.

No existen aún los módulos de P8 en adelante. No hay módulos financieros, contratos/archivos,
portal, proveedores productivos de correo/identidad, staging ni producción.

## Estado exacto

- I0–I4, I5.1, 5.1.1, 5.1.2, I5.2, P6 y P7: completadas y validadas localmente.
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
- `npm run check:all` pasó con los toolchains fijados: 154 pruebas no integración, 50 integración
  PostgreSQL y 19 frontend, además de OpenAPI y builds. Incluye dos tenants, SQL directo, bulk,
  concurrencia, revisiones, migraciones correctivas y RLS. Este cierre no planificó ni implementó
  P8 y no hay etapa funcional autorizada en ejecución. `npm run audit` no encontró vulnerabilidades
  conocidas en Python ni npm.

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
- Comportamiento exacto implementado: especificaciones 5.1 y 5.2.
- Destino funcional completo y secuencia: Blueprint y Roadmap.

## Decisiones diferidas

- Proveedores de staging/producción, correo, WhatsApp, archivos, malware y observabilidad.
- MFA productiva, OIDC y `ExternalIdentity`; identidad/autorización siguen siendo locales.
- Infraestructura asíncrona y outbox hasta el primer proceso real.
- Política legal detallada de privacidad, retención, aceptación contractual y firma.
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
5. Especificaciones 5.1/5.2 y ADR aplicables; para P8, revisar además ADR 0012–0015 y los contratos
   de agenda, reservas, operación, multi-espacio y CRM ya implementados.
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

## Próximo trabajo autorizado

Está autorizado preparar, a partir del estado real, un plan breve de **P8 — Agenda y reservas
avanzadas** y señalar solo decisiones bloqueantes. Su implementación requiere una nueva aprobación.
El plan debe conservar las exclusiones concurrentes, snapshots, reservas, coordinación 5.2,
multi-espacio y evidencia CRM existentes sin adelantar documentos, cobros ni integraciones
externas.

## Riesgos actuales

- Un despliegue futuro debe ejecutar el cutover 5.2 completo; no admite convivencia 5.1/5.2.
- Ese despliegue debe respetar también el orden multi-espacio, la adopción de estado P7 y las
  comprobaciones de ADR 0014–0015.
- Antes de desplegar la migración correctiva P7 se deben auditar correos actuales duplicados o no
  canónicos del entorno destino. La migración falla cerrada en esos casos y no reasigna evidencia
  de contacto de manera automática.
- Acciones privilegiadas de membresías continúan sin UI productiva y no deben abrirse sin MFA.
- Correo es local; recuperación/verificación externas no están listas para clientes reales.
- La política legal definitiva de retención, anonimización y eliminación de personas sigue
  diferida; P7 no concede capacidades ni endpoints para ejecutarlas.
- Proveedores, privacidad/retención y firma requieren investigación antes de sus etapas.
- No se ha observado una ejecución remota de CI ni existe ambiente desplegado.

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
