# AGENTS.md

## 1. Función y alcance

Este archivo establece las reglas obligatorias para cualquier persona o agente automatizado que trabaje en Claridez. Aplica a todo el repositorio, salvo que un archivo `AGENTS.md` más específico añada reglas compatibles para una subcarpeta.

`AGENTS.md` no sustituye la documentación de producto, los ADR, la guía de contribución ni la política de seguridad. Su función es convertir sus principios esenciales en reglas operativas para cada cambio.

## 2. Identidad e independencia

- El producto se llama **Claridez**.
- Una similitud de tecnología no autoriza reutilización de implementación.
- El repositorio es privado y el software es propietario.
- No se debe crear una licencia de código abierto ni inventar términos legales.

## 3. Fuentes de verdad

Las fuentes se interpretan según su ámbito:

1. Los ADR aceptados gobiernan las decisiones arquitectónicas que registran.
2. `docs/product/PRODUCT_BLUEPRINT.md` gobierna el destino, los módulos y los límites del producto
   funcional terminado.
3. Una especificación funcional aprobada gobierna el flujo exacto que describe sin modificar
   silenciosamente las demás fuentes.
4. `docs/product/PRODUCT_DELIVERY_ROADMAP.md` gobierna estado, orden y siguiente etapa;
   `docs/PROJECT_HANDOFF.md` conserva el punto operativo de continuidad.
5. `docs/product/PRODUCT_BASELINE.md` y `docs/architecture/INITIALIZATION_ROADMAP.md` son antecedentes
   históricos y no compiten con las fuentes maestras vigentes.
6. `docs/brand/CLARIDEZ_FUNDAMENTOS_DE_MARCA.md` es la fuente principal para propósito,
   posicionamiento, personalidad y lenguaje de marca.
7. `docs/brand/CLARIDEZ_DIRECCION_VISUAL_OFICIAL.md` prevalece exclusivamente en decisiones
   visuales.

Si dos fuentes parecen contradecirse fuera de esta jerarquía, se debe detener la decisión afectada y documentar el conflicto.

## 4. Arquitectura aprobada

- Monorepo.
- Monolito modular.
- Backend: Django y Django REST Framework.
- Frontend: React, TypeScript estricto y Vite.
- PostgreSQL en desarrollo, CI, staging y producción.
- API REST JSON versionada bajo `/api/v1`.
- Contrato OpenAPI y futuro cliente TypeScript generado.
- No se utilizarán microservicios.

La matriz concreta se registra en `docs/architecture/TOOLCHAIN_COMPATIBILITY.md`. Los manifiestos y lockfiles son la fuente ejecutable de versiones; una actualización requiere verificación y documentación deliberadas.

## 5. Invariantes multiempresa

- La arquitectura multiempresa existe desde el inicio.
- Todo dato privado debe pertenecer a una organización.
- Las excepciones globales deben ser explícitas, mínimas y justificadas.
- Un usuario puede pertenecer a varias organizaciones mediante membresías.
- Ningún identificador de organización enviado por un cliente se considera confiable sin validar la membresía y el contexto activo.
- Consultas, escrituras, relaciones, archivos, cachés y futuros trabajos asíncronos deberán respetar el contexto organizacional.
- Los accesos cruzados deben probarse de forma negativa con al menos dos organizaciones.
- ADR 0009 acepta controles tenant-aware de aplicación más PostgreSQL RLS como defensa en
  profundidad. RLS no sustituye autenticación, membresía ni autorización y el rol de aplicación
  puede establecer técnicamente el GUC.
- Toda validación organizacional, consulta privada y materialización de respuesta deberá completar
  dentro de `authorized_tenant_scope`; el helper de bajo nivel del GUC no será accesible desde
  vistas, serializers ni código de dominio ordinario.

## 6. Perfiles iniciales provisionales

Los siguientes nombres y propósitos generales están aprobados de forma provisional:

- `propietario`: referente principal de la organización y de su control general.
- `administrador`: apoyo en la administración cotidiana de la organización.
- `comercial`: trabajo relacionado con la gestión comercial.
- `operaciones`: trabajo relacionado con la preparación y ejecución operativa.
- `finanzas`: trabajo relacionado con el seguimiento económico y financiero.

ADR 0011 aprueba una matriz provisional limitada a la infraestructura de identidad, configuración
y membresías de la Iteración 4. El Blueprint define familias de acceso del destino, pero no concede
capacidades ejecutables por sí solo. Cada etapa traduce su familia a capacidades atómicas y pruebas.
Está prohibido inferir jerarquías, excepciones o accesos adicionales.

## 7. Alcance del producto

- Mercado inicial: Ecuador.
- Zona horaria inicial: `America/Guayaquil`.
- Moneda inicial: USD.
- Moneda y zona horaria deberán pertenecer a la configuración de cada organización.
- El producto funcional incluye cobros recibidos de clientes, cuentas por cobrar, costos, gastos,
  flujo y rentabilidad; no ofrece contabilidad formal ni facturación electrónica.
- El cobro de suscripciones de Claridez se difiere hasta después del producto funcional.
- El Modelo de Conversión y los dominios propios forman parte de una visión posterior.
- No se implementará un constructor web libre.
- No se deben inventar procesos, entidades, estados, cálculos o reglas fuera del Blueprint, Roadmap
  y etapa aprobada.

## 8. Alcance técnico establecido

Las Iteraciones 0 a 3, la Iteración 4, la Iteración 5.1, la implementación local de la Iteración
5.2 y P6–P12 están completadas. 4.1 incorpora el usuario
global `claridez.identity.User`; 4.2 incorpora `claridez.organizations.Organization` y
`Membership` como tablas globales de control, sus servicios transaccionales y el bootstrap local;
4.3 incorpora autenticación HTTP con sesiones Django, CSRF, recuperación y verificación local. El
cierre añade la matriz provisional, contexto organizacional y `OrganizationSettings` protegido por
RLS. 5.1 incorpora `claridez.commercial`, su API y el frontend de consulta a reserva confirmada,
gobernados por `docs/product/ITERATION_5_1_COMMERCIAL_FLOW.md` y ADR 0012. 5.2 incorpora
`claridez.operations`, su API y frontend, coordinación comercial atómica, RLS, integridad y cutover,
gobernados por `docs/product/ITERATION_5_2_OPERATIONS_SPECIFICATION.md` y ADR 0013; su despliegue y
cutover sobre un entorno destino no se presumen ejecutados. P6 incorpora configuración funcional,
sedes, espacios, catálogo versionado, precios/vigencias y su integración comercial y operativa,
gobernados por ADR 0014. Su administración web no habilita membresías propietarias ni acciones
sensibles sujetas a MFA. P7 incorpora `claridez.people` como propietario de identidad de persona,
fusión, alias y consentimiento, y `claridez.crm` para interacciones, tareas y composición de vistas;
`EventRequest` continúa como única oportunidad bajo autoridad `sales:*`, conforme a ADR 0015.
P8 incorpora `claridez.scheduling` como propietario lógico de agenda y `Reservation`, conserva la
tabla física `commercial_reservation`, unifica la exclusión temporal de reservas y bloqueos,
coordina reprogramación/cancelación con operaciones y expone proyecciones inmutables hacia CRM y
commercial, conforme a ADR 0016 y su especificación funcional aprobada.
P9 incorpora `claridez.documents` como autoridad de expedientes, instrumentos, versiones emitidas,
artefactos, aceptación, archivos externos, acceso externo y retención; usa renderer canónico,
almacenamiento privado sustituible, ClamAV y ledger durable de jobs PostgreSQL conforme a ADR 0017
y ADR 0018. La disposición física no existe y finanzas permanece sin capacidades documentales.
P10 incorpora `claridez.receivables` como autoridad exclusiva de obligaciones por cobrar,
calendarios operativos de vencimientos, pagos externos declarados, aplicaciones, ajustes,
reversos, devoluciones registradas, recibos lógicos, saldo derivado y antigüedad conforme a ADR
0019. La primera confirmación de una raíz crea exactamente una obligación mediante coordinación
transaccional neutral; scheduling no importa receivables. Los hechos financieros son append-only,
tenant-aware e idempotentes y Claridez no custodia fondos ni ejecuta reembolsos.
P11 incorpora `claridez.finance` como autoridad de costos directos planificados y reales, gastos
variables y recurrentes, caja operativa propia, presupuestos, reconocimiento de ingreso operativo,
periodos y cierres conforme a ADR 0020 y su contrato funcional. Consume de P10 solo referencias y
contribuciones de caja tipadas por `receivables.public`, reconoce el ingreso base al completar la
ejecución, conserva raíz y sede históricas, y no introduce libro mayor, cuentas bancarias,
contabilidad formal ni dependencia de catálogo.
P12 incorpora `claridez.resources` como autoridad de proveedores, unidades, recursos físicos y
suministrados, ubicaciones, compras y recepciones, ledger de inventario, disponibilidad por evento,
custodia, mantenimiento e indisponibilidad conforme a ADR 0021. Amplía las consecuencias de agenda
sin sustituir la autoridad temporal de scheduling, y Finance conserva la única autoridad de costo
real, gasto y caja mediante procedencia tipada de líneas de recepción. No introduce valoración
contable de inventario, marketplace, e-commerce ni logística avanzada.
El cierre correctivo `resources.0002` separa el estado físico `available/custody/retired` de la
ocupación temporal de activos serializados; pools, activos e indisponibilidades compiten solo cuando
se solapan en el intervalo y ubicación aplicables. Comercial no recibe inventario global y solo
consulta disponibilidad contextual vinculada a una solicitud/reserva y recurso pertinentes.
Django y React/Vite se ejecutan nativamente en Windows; PostgreSQL y el perfil documental canónico
usan contenedores locales.
El Blueprint define el destino, pero no autoriza por sí solo una etapa. Hasta que el propietario
apruebe la siguiente etapa del Roadmap, no se deben crear:

- Nuevas tablas privadas, políticas RLS, capacidades, endpoints o migraciones funcionales.
- Módulos o pantallas de P13 o etapas posteriores.
- Contenedores, infraestructura, integraciones o proveedores externos.
- Cliente TypeScript generado.

Los endpoints aprobados actualmente son `GET` y `HEAD` en `/health` y `/ready`, los nueve endpoints
de autenticación de ADR 0010, las cinco operaciones organizacionales de solo lectura/contexto de
ADR 0011, las operaciones comerciales de la especificación 5.1, las operaciones de la
especificación 5.2, las operaciones funcionales P6 de ADR 0014, las operaciones P7 de personas y
CRM aprobadas por ADR 0015 y las operaciones P8 de agenda y reservas aprobadas por ADR 0016.
También están aprobadas las operaciones internas y externas de P9 bajo `/api/v1` conforme a ADR
0017–0018; el acceso externo es un intercambio acotado, no un portal completo.
P10 aprueba consultas de cartera, obligación, calendario, movimientos, pagos, estado de cuenta,
antigüedad y recibos, además de comandos explícitos para pago, aplicación, calendario, ajuste,
reverso, devolución y recibo. No existe CRUD financiero genérico, `DELETE` ni `PATCH` libre sobre
hechos consumados.
P11 aprueba consultas de capabilities, contexto de evidencia, resumen y exportación, además de
comandos explícitos para categorías, periodos/cierres, planes y baseline, evidencia y decisión,
costos/correcciones, recurrencias, gastos/asignaciones, presupuestos, caja/correcciones y ajustes de
reconocimiento/correcciones. No expone un ledger duplicado de P10 ni CRUD libre sobre hechos.
P12 aprueba consultas de capabilities, disponibilidad contextual y resumen operativo minimizado
por rol, además de comandos
explícitos para unidades/conversiones, proveedores/contactos/términos/ofertas, recursos/ubicaciones,
compras/recepciones, movimientos, requerimientos/asignaciones, ejecución, mantenimiento e
indisponibilidad y materialización financiera conjuntiva. No expone CRUD genérico, valoración de
inventario, `DELETE` ni edición destructiva de hechos consumados.
PostgreSQL local se publica solo sobre loopback. Django normal usa
`claridez_app`; las
migraciones usan `claridez_migrator`; las pruebas usan `claridez_test_runner`; y `postgres` queda
reservado al bootstrap local explícito.

`npm run auth:bootstrap` crea localmente una organización activa y su propietario mediante los
servicios aprobados. No concede privilegios técnicos. `claridez_app` no tiene `DELETE` sobre
organizaciones, membresías, `OrganizationSettings` ni las tablas comerciales salvo
`QuotationLine`, cuyo reemplazo en borrador requiere borrado controlado. Tampoco tiene `DELETE`
sobre las tablas operativas, sedes, espacios, catálogo, people ni CRM. Interacciones, fusiones,
aliases, consentimiento e historiales son append-only; las tareas solo admiten actualización
controlada. `claridez_app` tampoco tiene `DELETE` sobre tablas documentales; P9 no expone
capability, endpoint, acción web, job ni servicio de destrucción física.
`claridez_app` tampoco tiene `DELETE` ni `TRUNCATE` sobre tablas financieras; movimientos,
comandos idempotentes y recibos consumados se corrigen exclusivamente con nuevos hechos.
`claridez_app` tampoco tiene `DELETE` ni `TRUNCATE` sobre las tablas privadas de resources; sus
ledgers, recepciones, historial y correcciones son append-only o se alteran mediante comandos
controlados y hechos compensatorios conforme a ADR 0021.

El código y los scripts del spike de tenancy fueron eliminados en 4.0. Su protocolo, resultados y
modelo de amenazas se conservan como evidencia histórica; no constituyen código productivo.

## 9. Dependencias y herramientas

- Toda dependencia futura necesita una necesidad concreta y compatibilidad comprobada.
- P9 incorpora el primer proceso asíncrono real mediante un ledger durable PostgreSQL y worker
  canónico sin Redis, broker, Celery ni Dramatiq.
- El patrón outbox permanece diferido como candidato; no es código obligatorio.
- Docker se utilizará cuando aporte reproducibilidad, especialmente para PostgreSQL, pero no será requisito para cada comando local en Windows.
- No se implementará una plataforma completa de OpenTelemetry de forma anticipada.

## 10. Seguridad y datos

- Nunca se versionan secretos, credenciales, tokens, llaves privadas ni datos reales de clientes.
- Los ejemplos deben ser sintéticos y no identificables.
- Las vulnerabilidades se reportan según `SECURITY.md`.
- OWASP ASVS es una referencia y fuente progresiva de checklists, no una certificación ya alcanzada.
- La autorización debe denegar por defecto cuando una decisión no esté definida.
- Los logs futuros no deben contener secretos ni datos sensibles innecesarios.
- Las operaciones financieras de P10 y P11 usan `numeric(18,2)`, `Decimal`, cuantización `0.01` y
  `ROUND_HALF_UP`; la moneda histórica no cambia y ninguno convierte divisas.

## 11. Cambios arquitectónicos y ADR

Se requiere un ADR cuando un cambio:

- Altera una decisión aprobada.
- Introduce un componente transversal o proveedor.
- Cambia el aislamiento multiempresa.
- Introduce una dependencia operativa importante.
- Establece una convención difícil de revertir.

No se exige una especificación extensa antes de cada módulo. Blueprint, Roadmap y un plan breve son
suficientes para iniciar una etapa aprobada cuando no exista una decisión bloqueante. Las decisiones
locales y reversibles se documentan junto al código y las pruebas pertinentes.

Los ADR deben separar expresamente decisiones aceptadas, aspectos provisionales, asuntos diferidos y validaciones o spikes pendientes. No deben presentar una hipótesis como decisión definitiva.

## 12. Marca e interfaz

- La dirección visual oficial prevalece solo en materias visuales.
- Los fundamentos de marca gobiernan propósito, posicionamiento, personalidad y lenguaje.
- Las copias controladas en `docs/brand/` no se editan silenciosamente.
- Cada cambio visual futuro debe conservar claridad, jerarquía, accesibilidad y el concepto de centro de control claro.

## 13. Forma de trabajo

El ciclo permanente es:

1. Leer Blueprint, Roadmap y Handoff.
2. Confirmar el estado real del repositorio, Git, configuración, migraciones y pruebas.
3. Identificar la siguiente etapa incompleta.
4. Presentar únicamente un plan breve y las decisiones verdaderamente bloqueantes.
5. Recibir aprobación.
6. Implementar la etapa completa dentro de sus límites.
7. Ejecutar validaciones proporcionales, incluidas PostgreSQL/RLS y UI cuando apliquen.
8. Actualizar Roadmap y Handoff con evidencia observada.
9. Reportar el resultado visible, archivos, comandos, resultados y límites.
10. Indicar exactamente la siguiente etapa.

Se preserva trabajo existente no relacionado. No se realizan remotos, despliegues ni acciones
externas sin autorización explícita.

### Comandos oficiales

Desde la raíz del repositorio:

- `npm run clean`: elimina artefactos regenerables internos; admite `-- --dry-run`.
- `npm run format`: aplica formato; modifica archivos.
- `npm run format:check`: comprueba formato sin modificar.
- `npm run lint`: ejecuta lint de Python y TypeScript.
- `npm run typecheck`: ejecuta mypy/django-stubs y TypeScript estricto.
- `npm test`: ejecuta pruebas y genera cobertura.
- `npm run build`: valida Django, sintaxis, OpenAPI y el build de Vite.
- `npm run check`: ejecuta la puerta local completa sin auditorías de red.
- `npm run check:all`: añade conexión, migraciones y pruebas contra PostgreSQL real.
- `npm run audit`: audita dependencias mediante servicios externos.
- `npm run auth:bootstrap`: provisiona localmente una organización y su propietario.

Los comandos de plataforma y sus protecciones se documentan en `docs/architecture/LOCAL_PLATFORM.md`. Nunca se ejecuta `docker compose down -v` como reset normal.

Las instalaciones reproducibles son `uv --directory apps/api sync --locked` y `npm ci`.

## 14. Criterio general de finalización

Un cambio está terminado cuando cumple su alcance aprobado, respeta las fuentes de verdad, conserva
los invariantes multiempresa, no introduce secretos, supera las comprobaciones pertinentes y deja
Roadmap y Handoff coherentes con lo realmente implementado.

Los comandos oficiales deben completar correctamente y no se deben reducir controles importantes solo para hacerlos pasar. Las limitaciones reales de una herramienta se documentan antes de cambiarla o sustituirla.
