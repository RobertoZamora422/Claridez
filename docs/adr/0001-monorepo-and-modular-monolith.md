# ADR 0001 — Monorepo y monolito modular

- **Estado:** Aceptado
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

Claridez comienza como un producto SaaS B2B completamente nuevo. Necesita integrar flujos comerciales, operativos y financieros con alta integridad transaccional, pero todavía no existe evidencia que justifique complejidad distribuida.

El proyecto debe conservar límites internos claros sin convertir cada área potencial en un servicio desplegable independiente.

## Decisiones aceptadas

- Claridez utilizará un único repositorio privado y propietario organizado como monorepo.
- La arquitectura inicial será un monolito modular.
- No se utilizarán microservicios.
- Backend y frontend podrán desplegarse como procesos diferentes sin convertir el dominio en servicios distribuidos.
- Claridez será completamente independiente de RFM Core.
- No se copiarán de RFM Core código, migraciones, estructura interna, historial ni configuración.

## Aspectos provisionales

- Los límites internos concretos de los módulos se definirán a partir de flujos funcionales aprobados.
- La estructura detallada bajo `apps/api` y `apps/web` se comprobará en la Iteración 1.

## Asuntos diferidos

- La extracción futura de un componente solo se evaluará ante necesidades comprobadas de escala, seguridad, operación o autonomía de equipos.

## Validación pendiente

Ninguna para adoptar la estructura general. Los límites de módulos requerirán validación funcional posterior.

## Alternativas consideradas

### Repositorios separados

No se seleccionan porque aumentarían la coordinación de contratos, versiones y cambios transversales durante la etapa inicial.

### Microservicios

No se seleccionan porque introducirían red, consistencia distribuida, observabilidad y operación adicionales sin una necesidad demostrada.

## Consecuencias

- Los cambios coordinados de API, frontend y documentación pueden revisarse juntos.
- Las transacciones del dominio pueden mantenerse dentro de PostgreSQL.
- La modularidad deberá protegerse mediante dependencias internas claras y pruebas, no mediante fronteras de red.
- La ausencia de microservicios no autoriza acoplamiento indiscriminado.

## Evidencia

- [Línea base del producto v0.1](../product/PRODUCT_BASELINE.md)
- [Roadmap técnico](../architecture/INITIALIZATION_ROADMAP.md)
