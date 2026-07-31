# ADR 0002 — Línea base tecnológica de la aplicación

- **Estado:** Aceptado
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

Claridez necesita una base tecnológica mantenible para una aplicación web transaccional, multiempresa y orientada a flujos de negocio. En la Iteración 0 se aprueban familias de tecnologías, pero no versiones exactas ni librerías auxiliares.

## Decisiones aceptadas

- Backend con Django y Django REST Framework.
- Frontend con React, TypeScript en modo estricto y Vite.
- PostgreSQL desde desarrollo y CI hasta staging y producción.
- API REST JSON versionada bajo `/api/v1`.
- Contrato OpenAPI.
- Cliente TypeScript generado desde el contrato cuando exista una API que lo justifique.
- Los toolchains vivirán en un monorepo.

## Aspectos provisionales

Ninguno respecto de las familias principales aprobadas.

## Asuntos diferidos

- Versiones exactas de Python, Django, Django REST Framework, PostgreSQL, Node.js, React, TypeScript y Vite.
- Gestores de paquetes y herramientas de lockfile.
- Librerías de pruebas, formato, lint y tipos.
- Librerías de UI, formularios, consultas y generación OpenAPI.

Estos asuntos se resolverán en la Iteración 1 mediante una matriz de compatibilidad.

## Validación pendiente

La Iteración 1 deberá comprobar:

- Compatibilidad entre framework, librerías y runtimes.
- Estado de mantenimiento y soporte.
- Compatibilidad con herramientas de pruebas y proveedores previstos.
- Reproducibilidad en Windows y CI.

No se elegirá una versión únicamente por ser la más reciente.

## Alternativas consideradas

Se evaluaron conceptualmente otros frameworks y estilos de API, pero no fueron seleccionados porque las familias aprobadas ofrecen una base adecuada para transacciones, migraciones, contratos HTTP y una interfaz web privada. Este ADR no afirma que una alternativa sea universalmente inferior.

## Consecuencias

- El backend y el frontend tendrán toolchains diferentes dentro de un mismo repositorio.
- PostgreSQL deberá estar disponible en pruebas de integración; SQLite no representará el comportamiento productivo.
- OpenAPI será un contrato verificable, no documentación mantenida manualmente en paralelo.
- La adopción de librerías auxiliares permanece restringida hasta demostrar necesidad y compatibilidad.

## Evidencia

- [Línea base del producto v0.1](../product/PRODUCT_BASELINE.md)
- [Roadmap técnico](../architecture/INITIALIZATION_ROADMAP.md)
