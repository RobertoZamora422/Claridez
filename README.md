# Claridez

**Gestión integral para salones y espacios de eventos.**

*Todo tu negocio, claro y bajo control.*

Claridez es una plataforma SaaS B2B multiempresa para ayudar a propietarios y administradores de salones y espacios de eventos a organizar, controlar y comprender su operación comercial, operativa y financiera.

## Estado del proyecto

El repositorio se encuentra en la **Iteración 0 — Gobierno documental**. En esta etapa solo se establecen la línea base del producto, las reglas de colaboración, las decisiones arquitectónicas aprobadas y las fuentes oficiales de marca.

Todavía no existen:

- Código de aplicación.
- Entidades o migraciones de dominio.
- Dependencias de backend o frontend.
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

Las versiones exactas del stack se decidirán en la Iteración 1 después de comprobar compatibilidad entre frameworks, librerías, herramientas de pruebas y proveedores previstos.

## Alcance inicial

El mercado inicial es Ecuador. La zona horaria inicial es `America/Guayaquil` y la moneda inicial es USD, aunque ambas deberán configurarse por organización.

Claridez no ofrecerá contabilidad formal ni facturación electrónica en la V1. El Modelo de Conversión y los dominios propios forman parte de la visión futura, pero no serán el primer flujo funcional. Tampoco se construirá un editor web libre.

La línea base aprobada se encuentra en [docs/product/PRODUCT_BASELINE.md](docs/product/PRODUCT_BASELINE.md). No constituye una especificación funcional completa.

## Documentación

- [Índice documental](docs/README.md)
- [Línea base del producto v0.1](docs/product/PRODUCT_BASELINE.md)
- [Roadmap técnico de inicialización](docs/architecture/INITIALIZATION_ROADMAP.md)
- [Registro de decisiones arquitectónicas](docs/adr/README.md)
- [Documentos oficiales de marca](docs/brand/README.md)
- [Reglas para colaboradores y agentes](AGENTS.md)
- [Guía de contribución](CONTRIBUTING.md)
- [Política de seguridad](SECURITY.md)

## Desarrollo

Los toolchains y comandos oficiales se definirán en la Iteración 1. Hasta entonces no deben añadirse dependencias, esqueletos de aplicación ni comandos supuestamente oficiales.

## Propiedad

Software privado y propietario.

Todos los derechos reservados.
