# Claridez

**Gestión integral para salones y espacios de eventos.**

*Todo tu negocio, claro y bajo control.*

Claridez es una plataforma SaaS B2B multiempresa para ayudar a propietarios y administradores de salones y espacios de eventos a organizar, controlar y comprender su operación comercial, operativa y financiera.

## Estado del proyecto

El repositorio completó la **Iteración 0 — Gobierno documental** y la **Iteración 1 — Toolchains reproducibles**. Contiene esqueletos técnicos mínimos de backend y frontend, sin módulos funcionales ni entidades del dominio.

Todavía no existen:

- Flujos funcionales de aplicación.
- Entidades o migraciones de dominio.
- Configuración de proveedores externos.
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

La matriz exacta y su evidencia se documentan en [docs/architecture/TOOLCHAIN_COMPATIBILITY.md](docs/architecture/TOOLCHAIN_COMPATIBILITY.md).

## Alcance inicial

El mercado inicial es Ecuador. La zona horaria inicial es `America/Guayaquil` y la moneda inicial es USD, aunque ambas deberán configurarse por organización.

Claridez no ofrecerá contabilidad formal ni facturación electrónica en la V1. El Modelo de Conversión y los dominios propios forman parte de la visión futura, pero no serán el primer flujo funcional. Tampoco se construirá un editor web libre.

La línea base aprobada se encuentra en [docs/product/PRODUCT_BASELINE.md](docs/product/PRODUCT_BASELINE.md). No constituye una especificación funcional completa.

## Documentación

- [Índice documental](docs/README.md)
- [Línea base del producto v0.1](docs/product/PRODUCT_BASELINE.md)
- [Roadmap técnico de inicialización](docs/architecture/INITIALIZATION_ROADMAP.md)
- [Matriz de compatibilidad de toolchains](docs/architecture/TOOLCHAIN_COMPATIBILITY.md)
- [Registro de decisiones arquitectónicas](docs/adr/README.md)
- [Documentos oficiales de marca](docs/brand/README.md)
- [Reglas para colaboradores y agentes](AGENTS.md)
- [Guía de contribución](CONTRIBUTING.md)
- [Política de seguridad](SECURITY.md)

## Desarrollo

Requisitos fijados:

- Python 3.13.14 y uv 0.12.0.
- Node.js 24.18.1 y npm 11.16.0.
- PostgreSQL 17 como objetivo inicial; su plataforma local se incorporará en la Iteración 2.

Instalación reproducible desde la raíz:

```text
uv --directory apps/api sync --locked
npm ci
```

Comandos oficiales:

```text
npm run format
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
npm run check
npm run audit
```

`format` modifica archivos; `check` usa la variante de formato sin escritura. Las auditorías permanecen separadas porque consultan servicios de vulnerabilidades.

## Propiedad

Software privado y propietario.

Todos los derechos reservados.
