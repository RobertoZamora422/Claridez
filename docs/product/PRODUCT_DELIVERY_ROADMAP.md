# Claridez — Roadmap completo de entrega

- **Versión:** 1.0
- **Estado:** fuente maestra de secuencia y estado de entrega
- **Fecha de corte:** 3 de agosto de 2026
- **Destino:** [Blueprint maestro del producto funcional](PRODUCT_BLUEPRINT.md)

Este roadmap conserva el historial real y ordena el trabajo pendiente hasta el producto funcional
terminado. «Completada» significa implementada y validada dentro del alcance indicado; no presume
despliegue. «Siguiente» identifica la única etapa que debe planificarse a continuación. «Pendiente»
no autoriza implementación. «Requiere investigación» exige resolver únicamente las decisiones
externas o difíciles de revertir antes de su parte afectada. «Diferida» no bloquea el producto
funcional.

`docs/architecture/INITIALIZATION_ROADMAP.md` es evidencia histórica limitada a la inicialización y
al primer flujo vertical. Ya no gobierna la secuencia general.

## I0 — Gobierno documental

**Identificador y nombre:** I0 — Gobierno documental e independencia.

**Estado:** Completada.

**Objetivo:** Crear el repositorio propietario de Claridez, su gobierno, marca, línea base y registro
de decisiones sin heredar implementación de otros proyectos.

**Alcance obligatorio:** Git independiente; `AGENTS.md`, README, contribución y seguridad; copias de
marca; línea base v0.1; ADR iniciales; UTF-8, LF y enlaces relativos.

**Exclusiones:** Dependencias, aplicación, infraestructura externa, datos reales y módulos
funcionales.

**Dependencias:** Fuentes oficiales de marca y autorización del propietario.

**Resultado visible:** Repositorio documental privado, coherente y auditable.

**Criterio verificable de finalización:** Fuentes creadas, hashes de marca verificados, enlaces y
codificación correctos, sin secretos ni historial ajeno.

**Riesgos principales:** Confundir documentos de marca, producto y arquitectura; copiar decisiones
no verificadas de RFM Core.

**Siguiente etapa:** I1 — Toolchains reproducibles.

## I1 — Toolchains reproducibles

**Identificador y nombre:** I1 — Toolchains y esqueletos ejecutables.

**Estado:** Completada.

**Objetivo:** Establecer versiones, lockfiles y puertas comunes para Django y React/Vite.

**Alcance obligatorio:** Python/uv, Node/npm, backend y frontend mínimos, TypeScript estricto,
formato, lint, tipos, pruebas, build y OpenAPI temporal.

**Exclusiones:** PostgreSQL activo, dominio, despliegue, CI y proveedor externo.

**Dependencias:** I0 y matriz de compatibilidad comprobada en Windows.

**Resultado visible:** Instalación reproducible y fachada raíz de comandos oficiales.

**Criterio verificable de finalización:** Lockfiles consistentes y todos los checks bootstrap
correctos con las versiones fijadas.

**Riesgos principales:** Deriva de runtimes, dependencias incompatibles y artefactos generados
versionados.

**Siguiente etapa:** I2 — Plataforma PostgreSQL local.

## I2 — Plataforma PostgreSQL local

**Identificador y nombre:** I2 — PostgreSQL, configuración y salud local.

**Estado:** Completada.

**Objetivo:** Ejecutar Django/React nativos y PostgreSQL 17 reproducible con separación de
credenciales y configuración fail-fast.

**Alcance obligatorio:** Compose solo para PostgreSQL; roles migrador, aplicación y pruebas;
`.env` local; perfiles; logs estructurados; `/health` y `/ready`.

**Exclusiones:** Staging, producción, proveedores administrados, RLS productivo y dominio.

**Dependencias:** I1 y Docker Desktop local.

**Resultado visible:** Base local verificable con privilegios mínimos y endpoints técnicos.

**Criterio verificable de finalización:** Conexión, migraciones, tests PostgreSQL, configuración
inválida y protecciones de reset comprobadas.

**Riesgos principales:** Usar credenciales privilegiadas en aplicación, borrar el volumen por error
o presentar salud como readiness.

**Siguiente etapa:** I3 — Spike de aislamiento multiempresa.

## I3 — Aislamiento multiempresa

**Identificador y nombre:** I3 — Spike de tenancy y decisión RLS.

**Estado:** Completada históricamente; código experimental eliminado.

**Objetivo:** Elegir con evidencia una estrategia de aislamiento antes de crear datos privados
productivos.

**Alcance obligatorio:** Dos organizaciones, aplicación tenant-aware, RLS, transacciones,
conexiones reutilizadas, SQL/bulk, relaciones, benchmark y amenazas.

**Exclusiones:** Reutilizar el spike como código productivo o adoptar un tenant global.

**Dependencias:** I2 y PostgreSQL 17 real.

**Resultado visible:** ADR 0009 acepta aplicación tenant-aware más RLS como defensa en profundidad.

**Criterio verificable de finalización:** Matriz experimental aprobada, base desechable eliminada y
evidencia histórica conservada.

**Riesgos principales:** Tratar RLS como autorización o contaminar conexiones con contexto de
sesión.

**Siguiente etapa:** I4 — Identidad, organizaciones y autorización.

## I4 — Identidad, organizaciones y autorización

**Identificador y nombre:** I4 — Base multiempresa productiva.

**Estado:** Completada.

**Objetivo:** Implementar identidad local, sesiones, organizaciones, membresías, capacidades,
contexto tenant y primera tabla RLS.

**Alcance obligatorio:** `User`, `Organization`, `Membership`, `OrganizationSettings`, sesiones,
CSRF, recuperación/verificación local, último propietario, siete capacidades y
`authorized_tenant_scope`.

**Exclusiones:** OIDC, MFA, correo productivo, invitaciones, administración privilegiada HTTP y
módulos funcionales.

**Dependencias:** I3 y ADR 0009–0011.

**Resultado visible:** Login y selección de organización con autorización backend-first y RLS
productivo.

**Criterio verificable de finalización:** Matriz completa, sesiones, concurrencia del último
propietario, pruebas negativas con dos tenants y migraciones desde cero aprobadas.

**Riesgos principales:** Confundir permisos Django con capacidades, confiar en organization ID del
cliente o abrir acciones privilegiadas sin MFA.

**Siguiente etapa:** I5.1 — Flujo comercial inicial.

## I5.1 — De consulta a reserva confirmada

**Identificador y nombre:** I5.1 — Flujo comercial y agenda de espacio único.

**Estado:** Completada.

**Objetivo:** Entregar el primer flujo vertical desde persona y solicitud hasta reserva confirmada o
cancelada.

**Alcance obligatorio:** Personas/revisiones, solicitudes, cotizaciones/versiones/líneas,
disponibilidad, aceptación, reserva provisional, confirmación, cancelación, dinero canónico y web.

**Exclusiones:** Catálogo, contratos, pagos, cuentas por cobrar, costos, múltiples espacios,
reprogramación y operación.

**Dependencias:** I4, especificación 5.1 y ADR 0012.

**Resultado visible:** Equipo comercial ejecuta el flujo completo responsive con agenda concurrente.

**Criterio verificable de finalización:** API, frontend, snapshots, RLS, GiST, dinero, CSRF,
concurrencia y OpenAPI probados.

**Riesgos principales:** Solapamientos bajo carrera, mutación de versiones emitidas o exposición de
datos personales.

**Siguiente etapa:** I5.1C — Endurecimiento y mantenibilidad.

## I5.1C — Endurecimiento, mantenibilidad y CI

**Identificador y nombre:** I5.1C — Cierre 5.1.1 y consolidación 5.1.2.

**Estado:** Completada.

**Objetivo:** Cerrar privacidad e integridad comercial y separar responsabilidades sin cambiar el
contrato funcional.

**Alcance obligatorio:** Representaciones mínimas, defensas PostgreSQL, servicios comerciales por
caso de uso, frontend por features y workflow de CI fijado.

**Exclusiones:** Nuevas entidades, endpoints, reglas de negocio, despliegue y protección remota de
rama.

**Dependencias:** I5.1 y pruebas de caracterización.

**Resultado visible:** Superficies públicas estables, código más cohesivo y CI versionada.

**Criterio verificable de finalización:** Checks locales, contrato preservado, cobertura mejorada y
workflow con calidad, PostgreSQL y auditoría.

**Riesgos principales:** Refactorizar comportamiento por accidente o presentar CI local como
ejecución remota.

**Siguiente etapa:** I5.2 — Preparación operativa.

## I5.2 — De reserva confirmada a evento preparado

**Identificador y nombre:** I5.2 — Preparación y ejecución operativa inicial.

**Estado:** Completada y validada localmente; cutover de un entorno destino no ejecutado.

**Objetivo:** Convertir cada confirmación en trabajo operativo trazable hasta completar o cancelar.

**Alcance obligatorio:** Preparación uno-a-uno, baseline de siete ítems, ítems libres, responsables,
revisiones, cinco estados, transiciones, coordinación atómica, guardián PostgreSQL, RLS, API y web.

**Exclusiones:** Plantillas configurables, proveedores, inventario, archivos, postevento, pagos y
reprogramación.

**Dependencias:** I5.1C, especificación 5.2, ADR 0013 y cutover documentado.

**Resultado visible:** Bandeja y detalle operativo desde confirmación hasta evento completado.

**Criterio verificable de finalización:** 139 pruebas no integración, 34 integración PostgreSQL y 13
frontend en la línea base consolidada; OpenAPI, privacidad, concurrencia, RLS y migraciones
correctos.

**Riesgos principales:** Ejecutar 5.1 y 5.2 a la vez, perder el contexto RLS al commit o exponer
teléfono/notas en listados y estados terminales.

**Siguiente etapa:** P6 — Configuración del negocio, sedes y catálogo.

## P6 — Configuración del negocio, sedes y catálogo

**Identificador y nombre:** P6 — Configuración funcional y catálogo comercial.

**Estado:** Completada y validada localmente; despliegue y cutover de un entorno destino no
ejecutados.

**Objetivo:** Permitir que una organización configure su operación real y cotice desde un catálogo
versionado sin perder líneas ni reservas históricas.

**Alcance obligatorio:** Datos funcionales del negocio; sedes y espacios con un default para el
histórico; tipos de evento; servicios, productos, paquetes y precios; vigencias; activación lógica;
uso en nuevas cotizaciones; administración responsive; capacidades y RLS.

**Exclusiones:** Inventario físico, compras, impuestos, facturación electrónica, constructor web,
planes de Claridez y disponibilidad avanzada.

**Dependencias:** I5.2; ADR para sustituir el espacio implícito y preservar la exclusión concurrente;
reglas de versionado/backfill y matriz de capacidades de la etapa.

**Resultado visible:** Un administrador configura sedes y oferta; comercial cotiza con catálogo y
las versiones emitidas siguen inmutables.

**Criterio verificable de finalización:** CRUD autorizado sin borrado histórico, cotización completa
desde catálogo/ad hoc, backfill de espacio default, dos tenants, concurrencia, OpenAPI y web
responsive. La puerta local observada cerró con 144 pruebas no integración, 40 integración
PostgreSQL y 16 frontend; migraciones, RLS, GiST/advisory lock por espacio, guardián 5.2,
OpenAPI y builds correctos. La validación visual adicional cubrió 375×812 y 1440×900 sin
desbordamiento horizontal. La auditoría postimplementación cerró por PostgreSQL los bypasses de
ORM bulk/SQL directo sobre revisiones y equivalencia de composición de paquetes.

**Riesgos principales:** Romper la exclusión de agenda, reescribir precios emitidos, duplicar
productos o convertir sedes en configuración sin uso real.

**Siguiente etapa:** P7 — CRM y seguimiento comercial.

## P7 — CRM y seguimiento comercial

**Identificador y nombre:** P7 — Personas, interesados, clientes y seguimiento.

**Estado:** Completada y validada localmente tras el cierre correctivo; no desplegada.

**Objetivo:** Gestionar de forma completa la relación comercial desde captación hasta resultado y
recompra.

**Alcance obligatorio:** Bandeja de oportunidades; etapas y motivos; interacciones; tareas y
próximos contactos; responsables; fuentes; búsqueda/deduplicación; historial; consentimiento;
vistas de interesado y cliente; indicadores de seguimiento.

**Exclusiones:** Automatización avanzada con IA, campañas masivas, soporte omnicanal completo y
facturación.

**Dependencias:** P6 y ADR 0015 aceptado; el contrato técnico provisional de privacidad,
consentimiento y retención queda delimitado sin inventar una política legal.

**Resultado visible:** Comercial dispone de bandeja CRM, búsqueda y deduplicación, oportunidad real
basada en `EventRequest`, vista integral de persona, timeline, interacciones minimizadas, tareas,
próximos contactos, consentimiento e indicadores. Propietario y administrador pueden ejecutar la
fusión lógica autorizada sin reescribir la evidencia histórica.

**Criterio verificable de finalización:** Ninguna oportunidad activa carece de estado visible;
interacciones y tareas son trazables; deduplicación y fusión son seguras; permisos conjuntivos,
búsqueda, dos tenants y backfill honesto están probados. La puerta local observada cerró con 149
pruebas no integración, 43 integración PostgreSQL y 17 frontend en su primer cierre. El cierre
correctivo del 3 de agosto sustituyó los accesos ORM de CRM a `people` y `commercial` por puertos
inmutables; cerró unicidad y búsqueda de contactos actuales e históricos; habilitó correcciones de
evidencia dentro del conjunto canónico; aplicó la precedencia de revocación de ADR 0015; persistió
la razón de cancelación sin revisiones vacías; ordenó tareas por una única fecha operativa; y
reemplazó UUID/revisiones manuales en la fusión web por búsqueda y selección. La puerta final pasó
con 154 pruebas no integración, 48 integración PostgreSQL y 18 frontend; cubrió migraciones desde
cero, desde P6 y desde P7 previo al cierre correctivo, FORCE RLS, ORM, SQL directo, bulk,
concurrencia, idempotencia, historial, privacidad, regresión 5.1/5.2/P6, OpenAPI y build. La
validación visual real previa cubrió 1440×900 y 390×844 sin desbordamiento horizontal; la navegación
móvil mantiene objetivos de 44 px. `npm run audit` no encontró vulnerabilidades conocidas en
Python ni npm.

**Riesgos principales:** La política legal definitiva de retención, anonimización y eliminación
sigue diferida; no debe confundirse el registro técnico de consentimiento con una conclusión
jurídica. Renombrar físicamente las tablas históricas de persona requiere un corte futuro explícito.
Un entorno que ya contenga correos actuales duplicados o no canónicos debe auditarlos antes de
aplicar la migración correctiva; la migración falla cerrada y no elige arbitrariamente una persona
propietaria del contacto.

**Siguiente etapa:** P8 — Agenda y reservas avanzadas.

## P8 — Agenda y reservas avanzadas

**Identificador y nombre:** P8 — Disponibilidad, bloqueos, reprogramación y cancelación completa.

**Estado:** Pendiente.

**Objetivo:** Operar calendario real por sede y espacio preservando historia y coordinación
transversal.

**Alcance obligatorio:** Disponibilidad por espacio; bloqueos internos; ventanas de montaje y
desmontaje; vistas día/semana/mes; reserva temporal; reprogramación con historial; cancelación con
consecuencias; exportación de calendario básica; concurrencia PostgreSQL.

**Exclusiones:** Calendario personal genérico, asignación de inventario detallada y sincronización
bidireccional con proveedores no evaluados.

**Dependencias:** P6, contratos vigentes de 5.1/5.2 y ADR de concurrencia/cutover multi-espacio.

**Resultado visible:** El equipo agenda varios espacios, bloquea indisponibilidad y reprograma sin
doble reserva ni pérdida de evidencia.

**Criterio verificable de finalización:** Solapamientos y carreras rechazados, reprogramación
coordina comercial/operación, zona horaria y buffers correctos, calendario accesible y migraciones
ensayadas.

**Riesgos principales:** Deadlocks, intervalos ambiguos, cambios históricos silenciosos y
descoordinación con preparación/documentos.

**Siguiente etapa:** P9 — Contratos, documentos y archivos.

## P9 — Contratos, documentos y archivos

**Identificador y nombre:** P9 — Evidencia contractual y documental.

**Estado:** Pendiente; requiere investigación legal y de proveedores antes de firma electrónica.

**Objetivo:** Crear, aceptar y conservar contratos y documentos versionados vinculados al evento.

**Alcance obligatorio:** Plantillas/versiones; variables autorizadas; contrato por reserva;
aceptación y evidencia; archivos privados; PDF server-side; checksum; permisos; retención; portal de
lectura/descarga; análisis de malware.

**Exclusiones:** Asesoría legal, facturación electrónica, firma avanzada no validada y editor libre
de documentos o sitios.

**Dependencias:** P8; revisión legal ecuatoriana de aceptación/firma/retención; selección de
almacenamiento, malware y PDF; ADR de archivos y proveedor.

**Resultado visible:** Comercial emite un contrato consistente y el cliente accede a una copia
verificable sin exponer archivos ajenos.

**Criterio verificable de finalización:** Plantilla y PDF reproducibles, versión emitida inmutable,
URLs temporales, malware y límites probados, evidencia legal aprobada y aislamiento de archivos con
dos tenants.

**Riesgos principales:** Prometer validez legal no comprobada, URLs predecibles, PII en metadatos o
regeneración que altere evidencia.

**Siguiente etapa:** P10 — Cobros y cuentas por cobrar.

## P10 — Cobros y cuentas por cobrar

**Identificador y nombre:** P10 — Pagos de clientes, saldos y cartera.

**Estado:** Pendiente.

**Objetivo:** Controlar el dinero que cada salón recibe de sus clientes y el saldo de cada evento.

**Alcance obligatorio:** Obligaciones y vencimientos; anticipos, abonos y pagos externos; métodos y
referencias; asignaciones; ajustes/reversos; devoluciones registradas; saldo; antigüedad de cartera;
recibos/estado de cuenta; migración de constancias 5.1; capacidades y auditoría.

**Exclusiones:** Cobro de suscripciones de Claridez, custodia de fondos, conciliación bancaria
automática, facturación electrónica y contabilidad formal.

**Dependencias:** P9; reglas monetarias y de cancelación; ADR para integridad, reversos,
concurrencia y migración de evidencia histórica.

**Resultado visible:** Finanzas conoce qué debía cobrarse, qué recibió el salón, qué se aplicó y qué
saldo queda por cliente y evento.

**Criterio verificable de finalización:** `Decimal` y redondeo probados, saldo canónico sin edición
destructiva, reintentos idempotentes, recibo verificable, permisos por rol y dos tenants.

**Riesgos principales:** Doble registro, sobreasignación concurrente, confundir constancia con pago
real o mezclar cartera del salón con suscripción SaaS.

**Siguiente etapa:** P11 — Costos, gastos, flujo y rentabilidad.

## P11 — Costos, gastos, flujo y rentabilidad

**Identificador y nombre:** P11 — Control financiero operativo del negocio.

**Estado:** Pendiente.

**Objetivo:** Mostrar cuánto cuesta, cuánto genera y cuán rentable es cada evento, sede y periodo.

**Alcance obligatorio:** Costos directos planificados/reales; gastos variables y recurrentes;
categorías; movimientos de caja operativos; presupuestos; asignaciones; flujo; márgenes y
rentabilidad; cierres de periodo operativos; trazabilidad y exportación.

**Exclusiones:** Libro mayor, balances contables certificados, impuestos, declaraciones, nómina y
facturación electrónica.

**Dependencias:** P10, P6 y reglas aprobadas de reconocimiento, asignación, redondeo y corrección.

**Resultado visible:** Propietario y finanzas comparan ingreso, costo y resultado real por evento y
periodo desde una sola verdad.

**Criterio verificable de finalización:** Fórmulas backend documentadas y probadas, ningún float,
totales reconciliables, cambios auditados, filtros temporales/moneda correctos y reportes con datos
representativos.

**Riesgos principales:** Presentar contabilidad formal, doble contar gastos, alterar periodos
cerrados o calcular resultados diferentes en frontend.

**Siguiente etapa:** P12 — Proveedores, recursos e inventario.

## P12 — Proveedores, recursos e inventario

**Identificador y nombre:** P12 — Capacidad física y abastecimiento operativo.

**Estado:** Pendiente.

**Objetivo:** Saber qué proveedores y recursos existen, dónde están y cómo se asignan a eventos.

**Alcance obligatorio:** Proveedores/contactos; servicios suministrados; mobiliario/equipos;
existencias; ubicaciones; movimientos; reservas por evento; mantenimiento/indisponibilidad;
compras/gastos vinculados; alertas de faltantes; historial.

**Exclusiones:** Marketplace, e-commerce, logística avanzada, nómina y contabilidad de inventario
formal.

**Dependencias:** P11, P8 y reglas de unidades, valoración operativa, concurrencia y responsables.

**Resultado visible:** Operaciones asigna recursos disponibles y finanzas relaciona su costo sin
hojas separadas.

**Criterio verificable de finalización:** Movimientos balanceados, no sobreasignación bajo carrera,
trazabilidad por evento/sede, activación lógica y aislamiento probado.

**Riesgos principales:** Existencias negativas, unidades incompatibles, borrado de historial y
mezcla entre catálogo vendible y activo físico.

**Siguiente etapa:** P13 — Operación avanzada.

## P13 — Operación avanzada

**Identificador y nombre:** P13 — Preparación, ejecución y cierre ampliados.

**Estado:** Pendiente.

**Objetivo:** Extender 5.2 para coordinar distintos tipos de evento, recursos, incidencias y cierre
sin convertir Claridez en gestor genérico de proyectos.

**Alcance obligatorio:** Plantillas operativas versionadas por organización/tipo; montaje y
desmontaje; asignación de recursos/proveedores; incidencias; cambios autorizados durante ejecución;
cierre postevento; archivos/evidencias; coordinación de reprogramación; métricas operativas.

**Exclusiones:** Proyectos libres, dependencias arbitrarias, turnos/nómina y automatización con IA.

**Dependencias:** P12, P9, P8 y preservación de estados/transiciones/revisiones 5.2 mediante ADR si
se amplía su máquina de estados.

**Resultado visible:** Cada evento usa una preparación adecuada, recursos confirmados y cierre
trazable incluso ante incidencias autorizadas.

**Criterio verificable de finalización:** Plantillas no alteran históricos, coordinación atómica,
edición/concurrencia segura, anexos privados, flujo de incidencia explícito y web accesible.

**Riesgos principales:** Romper el guardián 5.2, crear un sistema genérico de tareas o permitir
correcciones sin auditoría.

**Siguiente etapa:** P14 — Formularios, comunicaciones y portal.

## P14 — Formularios, comunicaciones y portal

**Identificador y nombre:** P14 — Experiencia externa del cliente.

**Estado:** Pendiente; requiere investigación de correo, WhatsApp y antiabuso.

**Objetivo:** Captar consultas y mantener al cliente informado sin exponer el workspace interno.

**Alcance obligatorio:** Formulario público; consentimiento; antiabuso; propuestas/contratos
compartidos; portal seguro; documentos; agenda resumida; pagos/saldo; mensajes y recordatorios;
preferencias; plantillas; estados de entrega; reintentos y auditoría.

**Exclusiones:** Constructor libre, campañas avanzadas, chatbot con IA, app nativa y acceso general
de proveedores.

**Dependencias:** P13, P10 y P9; proveedores evaluados; ADR del primer proceso asíncrono, outbox,
retención y autenticación del cliente.

**Resultado visible:** Un interesado consulta y un cliente sigue su evento, documentos y saldo desde
una superficie segura y clara.

**Criterio verificable de finalización:** Consentimiento y rate limit probados, enlaces/portal con
alcance mínimo, entregas idempotentes/observables, unsubscribe donde aplique, accesibilidad y dos
tenants.

**Riesgos principales:** Spam, costos o bloqueo del proveedor, fuga por enlaces, suplantación del
cliente y datos sensibles en mensajes/logs.

**Siguiente etapa:** P15 — Analítica, reportes y exportaciones.

## P15 — Analítica, reportes y exportaciones

**Identificador y nombre:** P15 — Centro de control e indicadores.

**Estado:** Pendiente.

**Objetivo:** Convertir la verdad transaccional completa en decisiones comerciales, operativas y
financieras verificables.

**Alcance obligatorio:** Dashboards por rol; embudo; ocupación; operación; cartera; flujo;
rentabilidad; inventario; definiciones de métricas; periodos/zona/moneda; reportes guardados;
CSV/XLSX/PDF según necesidad; exportaciones asíncronas y auditadas.

**Exclusiones:** Data warehouse anticipado, BI arbitrario, predicciones con IA y métricas sin dueño
o definición.

**Dependencias:** P14 y todos los dominios fuente; presupuestos de consulta y ADR si se adopta una
plataforma analítica separada.

**Resultado visible:** Cada perfil ve prioridades y resultados consistentes y puede exportar solo
su ámbito autorizado.

**Criterio verificable de finalización:** Métricas reconciliadas con casos fuente, periodos y bordes
probados, rendimiento con volumen, exportación minimizada y accesibilidad de gráficos/tablas.

**Riesgos principales:** Segunda verdad de cálculos, consultas costosas, inferencias cross-tenant o
exportaciones con más datos que la pantalla.

**Siguiente etapa:** P16 — Administración completa.

## P16 — Administración completa

**Identificador y nombre:** P16 — Administración de organizaciones y de la plataforma.

**Estado:** Pendiente.

**Objetivo:** Completar autoservicio seguro del tenant y operación interna controlada de Claridez.

**Alcance obligatorio:** Invitaciones; gestión de miembros/perfiles; MFA; recuperación reforzada;
sesiones/dispositivos; configuración integral; políticas de retención/exportación; auditoría;
solicitudes de soporte; administración interna separada; acceso excepcional temporal y revisable;
uso técnico e incidentes.

**Exclusiones:** Monetización, planes, facturas de Claridez, soporte transversal permanente y Django
Admin sin controles equivalentes.

**Dependencias:** P15, proveedor de correo, política de privacidad/retención y ADR de acceso interno
y autenticación reforzada.

**Resultado visible:** El propietario administra su organización con MFA y Claridez soporta la
plataforma sin acceso implícito a datos privados.

**Criterio verificable de finalización:** Último propietario protegido, invitaciones/tokens
seguros, revocación efectiva, auditoría inmutable, break-glass temporal aprobado y matriz completa
probada.

**Riesgos principales:** Escalada de privilegios, soporte sin trazabilidad, bloqueo de cuentas y
retención incompatible con obligaciones legales.

**Siguiente etapa:** P17 — Staging, producción y endurecimiento final.

## P17 — Staging, producción y endurecimiento final

**Identificador y nombre:** P17 — Operación productiva y aceptación del producto funcional.

**Estado:** Pendiente; requiere investigación y selección de proveedores.

**Objetivo:** Desplegar y operar de forma recuperable el producto completo, y demostrar la
definición de terminado del Blueprint.

**Alcance obligatorio:** Proveedores y topología; dominios/TLS; secretos; CI/CD; artefactos;
staging aislado; migraciones/cutovers incluido 5.2; correo/archivos/jobs; monitoreo y alertas;
backups/PITR; restauración; runbooks; capacidad/costos; pruebas E2E, seguridad, accesibilidad y
rendimiento; aceptación productiva.

**Exclusiones:** Monetización de Claridez, expansión internacional, microservicios y certificaciones
no alcanzadas.

**Dependencias:** P16; investigación de nube, PostgreSQL, almacenamiento, correo, mensajería,
monitoreo y cumplimiento; RPO 15 minutos/RTO 4 horas; revisión de amenazas y privacidad.

**Resultado visible:** Claridez funciona en producción con usuarios autorizados, observabilidad,
respaldo y recuperación ensayada.

**Criterio verificable de finalización:** Los diez criterios de la sección 16 del Blueprint están
demostrados; staging y producción usan artefacto controlado; restore y cutovers pasan; no hay riesgo
crítico abierto; el producto funcional puede declararse terminado.

**Riesgos principales:** Proveedor o costo inadecuado, migración irreversible sin ensayo, secretos
mal gestionados, recuperación no comprobada o abrir tráfico con 5.1/5.2 incompatibles.

**Siguiente etapa:** M18 — Monetización de Claridez, deliberadamente posterior.

## M18 — Monetización de Claridez

**Identificador y nombre:** M18 — Planes y cobro de suscripciones SaaS.

**Estado:** Deliberadamente diferida; no bloquea el producto funcional.

**Objetivo:** Comercializar Claridez mediante planes, suscripciones y cobro de la plataforma cuando
exista una decisión comercial aprobada.

**Alcance obligatorio:** Planes/capacidades; trials; suscripción; facturación de Claridez; pasarela;
webhooks; reintentos; dunning; cancelación; soporte; métricas de monetización y conciliación del
proveedor.

**Exclusiones:** Pagos que el salón recibe de sus clientes —ya resueltos en P10—, marketplace,
facturación electrónica del salón y expansión internacional automática.

**Dependencias:** P17; estrategia de precios, impuestos y términos comerciales; selección de
pasarela; revisión legal/fiscal; ADR de proveedor, webhooks e idempotencia.

**Resultado visible:** Claridez puede cobrar su propia suscripción sin mezclarla con la tesorería de
las organizaciones clientes.

**Criterio verificable de finalización:** Ciclo de suscripción y fallos de pago probado end-to-end,
capacidades por plan deny-by-default, webhooks idempotentes, conciliación y soporte documentados.

**Riesgos principales:** Mezclar dominios financieros, dependencia de pasarela, cálculo fiscal no
validado y bloquear datos del cliente de forma impropia.

**Siguiente etapa:** Se determina mediante una nueva revisión de producto posterior a la
monetización; no está definida por este roadmap.
