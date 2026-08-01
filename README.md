# Claridez

**Gestión integral para salones y espacios de eventos.**

*Todo tu negocio, claro y bajo control.*

Claridez es una plataforma SaaS B2B multiempresa para ayudar a propietarios y administradores de salones y espacios de eventos a organizar, controlar y comprender su operación comercial, operativa y financiera.

## Estado del proyecto

El repositorio completó la **Iteración 0 — Gobierno documental**, la **Iteración 1 — Toolchains
reproducibles**, la **Iteración 2 — Plataforma local y configuración**, el spike técnico de la
**Iteración 3 — Aislamiento multiempresa** y las subiteraciones **4.0 — Gobierno y descarte**, **4.1
— Usuario primero**, **4.2 — Organizaciones y membresías**, **4.3 — Autenticación HTTP y sesiones
de servidor** y el cierre integrado de autorización y aislamiento tenant. Contiene PostgreSQL local
reproducible, identidad y sesiones locales, organizaciones, membresías, contexto organizacional y
la primera tabla privada protegida por RLS. La Iteración 4, el primer flujo vertical de la
Iteración 5.1, su endurecimiento 5.1.1, la refactorización estructural y CI de 5.1.2 y la
implementación local de 5.2 están completados. `claridez.commercial` permite registrar personas y
solicitudes, cotizar, aceptar y confirmar o cancelar reservas con agenda concurrente y RLS;
`claridez.operations` convierte cada confirmación en una preparación operativa con checklist,
responsables, estados y defensas PostgreSQL. El cutover de 5.2 no se ha desplegado.

Todavía no existen:

- Módulos financieros.
- Proveedor productivo de correo o proveedores de identidad externos.
- Despliegues o ambientes remotos.

## Decisiones aprobadas

- Repositorio privado, propietario y organizado como monorepo.
- Proyecto completamente independiente de RFM Core.
- Monolito modular; no se utilizarán microservicios.
- Backend con Django y Django REST Framework.
- Frontend con React, TypeScript estricto y Vite.
- PostgreSQL desde desarrollo hasta producción.
- API REST JSON versionada mediante `/api/v1`.
- Contrato OpenAPI y futuro cliente TypeScript generado.
- Arquitectura multiempresa desde el inicio.
- Todo dato privado deberá pertenecer a una organización.
- Los usuarios podrán pertenecer a varias organizaciones mediante membresías.
- Identidad local desacoplada con sesiones Django de servidor.
- Aislamiento tenant-aware en la aplicación más PostgreSQL RLS como defensa en profundidad.

La matriz exacta y su evidencia se documentan en [docs/architecture/TOOLCHAIN_COMPATIBILITY.md](docs/architecture/TOOLCHAIN_COMPATIBILITY.md).

## Alcance inicial

El mercado inicial es Ecuador. La zona horaria inicial es `America/Guayaquil` y la moneda inicial es USD, aunque ambas deberán configurarse por organización.

Claridez no ofrecerá contabilidad formal ni facturación electrónica en la V1. El Modelo de Conversión y los dominios propios forman parte de la visión futura, pero no serán el primer flujo funcional. Tampoco se construirá un editor web libre.

La línea base aprobada se encuentra en [docs/product/PRODUCT_BASELINE.md](docs/product/PRODUCT_BASELINE.md). No constituye una especificación funcional completa.

## Documentación

- [Índice documental](docs/README.md)
- [Línea base del producto v0.1](docs/product/PRODUCT_BASELINE.md)
- [Especificación funcional de la Iteración 5.1](docs/product/ITERATION_5_1_COMMERCIAL_FLOW.md)
- [Cierre de la Iteración 5.1.1](docs/product/ITERATION_5_1_1_HARDENING.md)
- [Mantenibilidad y CI de la Iteración 5.1.2](docs/product/ITERATION_5_1_2_MAINTAINABILITY_CI.md)
- [Especificación implementada de la Iteración 5.2](docs/product/ITERATION_5_2_OPERATIONS_SPECIFICATION.md)
- [Cutover obligatorio de la Iteración 5.2](docs/architecture/ITERATION_5_2_CUTOVER.md)
- [Roadmap técnico de inicialización](docs/architecture/INITIALIZATION_ROADMAP.md)
- [Matriz de compatibilidad de toolchains](docs/architecture/TOOLCHAIN_COMPATIBILITY.md)
- [Plataforma local y configuración](docs/architecture/LOCAL_PLATFORM.md)
- [Protocolo del spike de tenancy](docs/architecture/TENANCY_SPIKE_PROTOCOL.md)
- [Resultados del spike de tenancy](docs/architecture/TENANCY_SPIKE_RESULTS.md)
- [Modelo de amenazas del spike](docs/security/TENANCY_SPIKE_THREAT_MODEL.md)
- [Registro de decisiones arquitectónicas](docs/adr/README.md)
- [Documentos oficiales de marca](docs/brand/README.md)
- [Reglas para colaboradores y agentes](AGENTS.md)
- [Guía de contribución](CONTRIBUTING.md)
- [Política de seguridad](SECURITY.md)

## Desarrollo

Requisitos fijados:

- Python 3.13.14 y uv 0.12.0.
- Node.js 24.18.1 y npm 11.16.0.
- Docker Desktop con Docker Compose para ejecutar únicamente PostgreSQL 17.10 local.

Instalación reproducible desde la raíz:

```text
uv --directory apps/api sync --locked
npm ci
```

Preparación inicial de PostgreSQL, después de crear un `.env` local a partir de `.env.example`:

```text
npm run db:start
npm run db:prepare
npm run db:migrate
npm run db:check
npm run auth:bootstrap
```

La guía completa, perfiles y protecciones se encuentran en [docs/architecture/LOCAL_PLATFORM.md](docs/architecture/LOCAL_PLATFORM.md).

Comandos oficiales:

```text
npm run format
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
npm run check
npm run check:all
npm run audit
npm run auth:bootstrap
```

`format` modifica archivos; `check` usa la variante de formato sin escritura. `check:all` añade PostgreSQL real, conexión y migraciones. Las auditorías permanecen separadas porque consultan servicios de vulnerabilidades.

El protocolo, los resultados y el modelo de amenazas del spike se conservan como evidencia
histórica. Su código y scripts experimentales fueron descartados en 4.0; la implementación
productiva independiente comienza con `OrganizationSettings` y `authorized_tenant_scope`.

## Propiedad

Software privado y propietario.

Todos los derechos reservados.
