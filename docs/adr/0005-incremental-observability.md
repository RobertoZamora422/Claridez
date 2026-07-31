# ADR 0005 — Observabilidad incremental

- **Estado:** Aceptado
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

Claridez necesitará comprender fallos y comportamiento productivo, pero una plataforma completa de telemetría distribuida sería prematura antes de existir aplicaciones, tráfico o servicios distribuidos.

## Decisiones aceptadas

La observabilidad comenzará con:

- Logs estructurados.
- Un identificador de correlación por solicitud.
- Contexto técnico suficiente para investigar errores sin registrar secretos ni datos sensibles innecesarios.
- Seguimiento de errores cuando exista una aplicación ejecutable y se seleccione una opción compatible.

La auditoría de acciones de negocio sensibles será un mecanismo distinto de los logs operativos y se especificará cuando corresponda.

## Aspectos provisionales

- El formato exacto de logs y campos de correlación se definirá con el backend mínimo.
- El proveedor o herramienta de seguimiento de errores no está seleccionado.

## Asuntos diferidos

- Métricas de aplicación y negocio.
- Trazas distribuidas.
- OpenTelemetry como plataforma completa.
- Dashboards, alertas, SLI y SLO.

Estos elementos se incorporarán según necesidades comprobadas y antes de asumir compromisos operativos que los requieran.

## Validación pendiente

- Comprobar que la correlación funciona entre frontend y API cuando ambos esqueletos existan.
- Revisar que logs y errores no expongan secretos, PII ni información financiera sensible.
- Evaluar métricas y trazas cuando los logs dejen preguntas operativas relevantes sin respuesta.

## Alternativas consideradas

### Plataforma completa desde el inicio

No se selecciona porque aún no existen componentes ni flujos que justifiquen su complejidad.

### No incorporar observabilidad hasta producción

No se selecciona porque los identificadores de correlación y logs estructurados son más seguros y consistentes cuando se diseñan desde la base ejecutable.

## Consecuencias

- La primera aplicación ejecutable deberá incluir una base pequeña y estructurada de logs.
- No se prometerá capacidad de métricas o trazas antes de implementarla.
- La evolución de observabilidad responderá a riesgos y preguntas reales.

## Evidencia

- [Roadmap técnico](../architecture/INITIALIZATION_ROADMAP.md)
