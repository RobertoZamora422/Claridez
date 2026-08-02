# Roadmap técnico de inicialización

- **Estado de la Iteración 0:** completada documentalmente el 31 de julio de 2026
- **Alcance:** preparación técnica hasta habilitar el primer flujo vertical

Este roadmap ordena la inicialización del producto. No es un cronograma comercial ni una especificación funcional.

## Principios de ejecución

- Cada iteración debe ser pequeña, verificable y tener un criterio de salida.
- No se prolongará la preparación de infraestructura indefinidamente.
- No se adelantarán componentes cuya necesidad todavía no exista.
- Una iteración posterior no comienza hasta resolver las decisiones que la bloquean.
- No se realizarán despliegues o acciones externas sin autorización explícita.

## Iteración 0 — Gobierno documental

### Alcance

- Inicializar Git local sin historial ajeno.
- Crear documentos raíz de gobierno.
- Crear estructura y ADR iniciales.
- Incorporar copias controladas de marca.
- Registrar la línea base del producto v0.1 y la jerarquía documental.

### Exclusiones

- Dependencias.
- Código de aplicación.
- Entidades o migraciones.
- Workflows, remotos, commits y proveedores externos.

### Criterio de salida

- Árbol documental completo.
- UTF-8 y LF verificados.
- Enlaces relativos válidos.
- Hashes de marca coincidentes.
- Ausencia básica de secretos.
- Estado Git local informado y sin commit.

## Iteración 1 — Toolchains

**Estado:** completada técnicamente el 31 de julio de 2026.

### Alcance

- Proponer y verificar una matriz de versiones compatibles.
- Crear esqueletos mínimos de `apps/api` y `apps/web`.
- Activar TypeScript estricto.
- Crear lockfiles.
- Añadir comandos oficiales de formato, lint, tipos, pruebas y build.
- Generar y validar un esquema OpenAPI técnico sin endpoints funcionales.

### Restricciones

- No elegir versiones solamente por ser las más recientes.
- No crear entidades del dominio.
- No instalar PostgreSQL ni requerir una conexión activa en las comprobaciones bootstrap.
- No definir todavía el artefacto productivo del backend.

### Criterio de salida

- Compatibilidad documentada.
- Instalación reproducible.
- Backend y frontend mínimos construyen y ejecutan sus pruebas técnicas.
- OpenAPI se genera y valida como artefacto temporal ignorado.

## Iteración 2 — Plataforma local

**Estado:** completada técnicamente el 31 de julio de 2026.

### Alcance

- PostgreSQL reproducible.
- Configuración validada y ambientes separados.
- Secretos fuera de Git.
- Endpoints técnicos de salud.
- Base verificable para futura CI, sin crear workflows en esta iteración.

### Restricciones

- Sin despliegue externo.
- Docker se usará cuando aporte reproducibilidad, sin obligar a ejecutar cada comando local dentro de un contenedor en Windows.

### Criterio de salida

- Entorno local reconstruible.
- PostgreSQL real utilizado por pruebas de integración.
- Configuración inválida falla de forma explícita.
- Los comandos aprobados dejan una base reproducible para futura CI.

## Iteración 3 — Spike de tenancy

**Estado:** completada técnicamente el 31 de julio de 2026; estrategia aceptada en ADR 0009 durante
4.0.

### Alcance

- Comparar aislamiento de aplicación frente a aplicación más PostgreSQL RLS.
- Usar al menos dos organizaciones.
- Probar lecturas y escrituras cruzadas.
- Probar relaciones tenant-aware.
- Probar pooling, transacciones, migraciones, comandos, tareas y conexiones reutilizadas.
- Documentar resultados y recomendación mediante ADR.

### Restricciones

- El código del spike no se convierte automáticamente en código productivo.
- No se adopta RLS antes de observar evidencia suficiente.

### Criterio de salida

- Resultados reproducibles.
- Riesgos y limitaciones documentados.
- Estrategia de aislamiento aprobada antes de modelar datos privados productivos.

### Resultado observado

- 36 pruebas experimentales aprobadas contra PostgreSQL 17 real.
- La base desechable fue eliminada al finalizar.
- La evidencia sustentó la aceptación de aplicación tenant-aware más RLS en ADR 0009.
- Ningún modelo, migración o helper del spike se considera productivo.
- El código y los scripts experimentales se eliminaron en 4.0; el protocolo, los resultados y el
  modelo de amenazas permanecen como evidencia histórica.

## Iteración 4 — Identidad, organizaciones y autorización

**Estado:** completada, incluidas 4.0 — Gobierno y descarte, 4.1 — Usuario primero, 4.2 —
Organizaciones y membresías, 4.3 — Autenticación HTTP y sesiones de servidor y el cierre integrado
de autorización, contexto organizacional y RLS.

### Condición de entrada

- Estrategias de identidad, organizaciones, autorización y tenancy aprobadas mediante ADR 0009,
  ADR 0010 y ADR 0011.

### Alcance

- Implementar la opción de identidad seleccionada.
- Establecer organizaciones y membresías.
- Incorporar la matriz provisional de ADR 0011 sin tratarla como contrato de módulos futuros.
- Aplicar aislamiento y denegación por defecto.

### Resultado de 4.1

- `claridez.identity.User` se implementó como usuario global basado en `AbstractUser`, sin campos
  tenant.
- La migración inicial se validó desde cero, en reversión y en nueva migración sobre PostgreSQL
  desechable.
- El hash de sesión incorpora `security_version` y conserva `SECRET_KEY_FALLBACKS`.
- No se crearon organizaciones, membresías, RLS, endpoints ni frontend.

### Resultado de 4.2

- `claridez.organizations` incorpora únicamente `Organization` y `Membership` como tablas globales
  de control, sin RLS.
- La creación atómica siempre incorpora un primer propietario activo.
- Los servicios bloquean `Organization` y después la membresía afectada para proteger al último
  propietario bajo concurrencia.
- La relación usuario-organización es única y puede reactivarse después de revocación sin crear una
  nueva fila ni cambiar `joined_at`.
- El bootstrap local es transaccional, idempotente por organización y usa advisory lock.
- No se crearon endpoints, capacidades, `OrganizationSettings`, tenancy productivo ni frontend.

### Resultado de 4.3

- La API expone CSRF, login, logout, usuario actual, cambio y recuperación de contraseña y
  verificación de correo bajo `/api/v1/auth/`.
- Las sesiones Django vencen de forma absoluta ocho horas después del login y no se renuevan por
  actividad ni por el cambio de contraseña de la sesión actual.
- `django-axes` protege el login por combinación de correo canónico e IP observada directamente,
  con cinco fallos y enfriamiento de 15 minutos.
- El correo permanece limitado al backend de consola local y al backend en memoria de pruebas.
- No se implementaron selección de organización, capacidades, autorización por membresía,
  `OrganizationSettings`, tenancy productivo, RLS, frontend, MFA ni OIDC.

### Resultado del cierre integrado

- La matriz exacta de siete capacidades de ADR 0011 se aplica sin jerarquías implícitas y con
  denegación por defecto.
- `authorized_tenant_scope` es el único límite para datos privados; revalida actor, organización,
  membresía y capacidad y usa contexto PostgreSQL local a la transacción.
- `OrganizationSettings` es la primera entidad privada, con una fila por organización, USD y
  `America/Guayaquil` iniciales y RLS `ENABLE` más `FORCE`.
- Se exponen únicamente listado organizacional, consulta/selección de contexto y lecturas de
  settings y membresías. No existen escrituras privilegiadas HTTP.
- Las pruebas negativas cubren dos organizaciones, ORM, SQL, bulk, relaciones, scopes anidados,
  conexiones reutilizadas, concurrencia y privilegios.

### Criterio de salida

- Identidad y recuperación evaluadas según la opción elegida.
- Cambio de contexto organizacional sin mezcla de datos.
- Accesos cruzados rechazados mediante pruebas.
- Autorización mínima respaldada por una especificación aprobada.

## Iteración 5 — Primer flujo vertical funcional

**Estado:** 5.1 completada, cerrada mediante el endurecimiento 5.1.1 y estructuralmente consolidada
mediante mantenibilidad y CI en 5.1.2; 5.2 implementada y validada localmente, con cutover del
entorno destino pendiente de despliegue.

### Condición de entrada

- Repositorio, toolchains, PostgreSQL, tenancy, identidad, organizaciones y autorización establecidos.
- Especificación funcional separada y aprobada.

### Resultado de 5.1

- `claridez.commercial` incorpora personas con historial, solicitudes, cotizaciones versionadas y
  reservas provisionales o confirmadas.
- La agenda protege un espacio implícito por organización mediante rangos `[)` y exclusión GiST;
  las provisionales vencen a las 48 horas.
- La confirmación conserva una constancia de anticipo externo o una excepción autorizada, sin
  procesar pagos ni crear cuentas por cobrar.
- Ocho capacidades funcionales se añaden de forma explícita a la matriz provisional.
- La API REST y la aplicación React ejecutan el flujo completo con RLS, CSRF y contexto
  organizacional.
- La especificación implementada está en
  [Iteración 5.1 — De consulta a reserva confirmada](../product/ITERATION_5_1_COMMERCIAL_FLOW.md).
- El cierre de autorización, integridad histórica y marca está en
  [Iteración 5.1.1 — Endurecimiento](../product/ITERATION_5_1_1_HARDENING.md).

### Resultado de 5.1.2

- Los casos de uso de `claridez.commercial.services` se separaron por responsabilidad conservando
  una superficie pública única y compatible.
- `App.tsx` quedó como composición; las pantallas, formularios y comandos viven por funcionalidad.
- GitHub Actions ejecutará calidad, PostgreSQL 17 y auditoría con toolchains y acciones fijados.
- No cambiaron modelos, migraciones, contratos HTTP, reglas de dominio, autorización ni interfaz.
- La arquitectura y los checks están documentados en
  [Iteración 5.1.2 — Mantenibilidad y CI](../product/ITERATION_5_1_2_MAINTAINABILITY_CI.md).

### Criterio de salida

La salida de 5.1 exige reglas, estados, permisos, API, frontend, migraciones y pruebas de
concurrencia y aislamiento coherentes con su especificación funcional.

### Resultado de 5.2

- `claridez.operations` incorpora una preparación uno a uno por reserva confirmada, siete ítems
  base, ítems libres y transiciones append-only.
- La confirmación y cancelación comerciales se coordinan atómicamente sin señales Django; ADR 0013
  limita el trigger transversal a guardián diferido del estado final y la migración implementada
  `operations/0002_commercial_operations_guardian` lo instala como constraint trigger diferible.
- Las cinco etapas operativas, revisión optimista, responsables, privacidad condicionada del
  teléfono, RLS, claves tenant-aware y reglas de readiness se aplican en backend y PostgreSQL.
- La API de comandos y la vista React cubren bandeja, detalle, checklist, asignación, listo, inicio y
  finalización sin `DELETE` ni un sistema genérico de proyectos.
- El backfill y el cutover con indisponibilidad controlada están implementados y documentados; su
  ejecución sobre el entorno destino sigue siendo obligatoria antes de aceptar tráfico.
- La especificación y evidencia local están en
  [Iteración 5.2 — De reserva confirmada a evento preparado](../product/ITERATION_5_2_OPERATIONS_SPECIFICATION.md).

## Decisiones transversales diferidas

- Infraestructura asíncrona y patrón outbox: al primer proceso asíncrono real.
- Métricas y trazas distribuidas: cuando los logs y el seguimiento de errores no sean suficientes.
- Proveedores de staging y producción: antes de preparar esos ambientes.
- Modelo de Conversión y dominios propios: después de validar los flujos internos prioritarios.
