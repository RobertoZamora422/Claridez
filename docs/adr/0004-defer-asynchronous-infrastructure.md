# ADR 0004 — Diferir infraestructura asíncrona

- **Estado:** Aceptado
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

En la etapa inicial no existe todavía un proceso asíncrono funcional definido. Instalar colas y workers ahora añadiría dependencias, operación y modos de fallo sin una necesidad comprobada.

## Decisiones aceptadas

- No se instalarán Celery, Dramatiq, Redis, brokers, workers ni infraestructura de colas durante las iteraciones iniciales sin un caso real aprobado.
- El primer proceso asíncrono deberá justificar sus requisitos de entrega, reintento, orden, idempotencia y observabilidad.
- La introducción de infraestructura asíncrona requerirá una decisión arquitectónica explícita.

## Aspectos provisionales

Ninguno.

## Asuntos diferidos

- Selección de biblioteca o servicio de cola.
- Elección y diseño del patrón outbox transaccional.
- Política de reintentos, dead letters y operación de workers.
- Escalado y monitoreo de trabajos.

El patrón outbox queda documentado como candidato, no como componente adoptado.

## Validación pendiente

La evaluación comenzará cuando una especificación funcional identifique el primer proceso que deba ejecutarse fuera de la solicitud principal.

## Alternativas consideradas

### Instalar una cola desde el scaffolding

No se selecciona porque convertiría una posibilidad futura en costo presente.

### Ejecutar cualquier trabajo dentro de la solicitud HTTP

No se adopta como regla general. Cada caso futuro deberá evaluar latencia, fiabilidad y consistencia.

## Consecuencias

- El entorno inicial tendrá menos servicios y dependencias.
- No existirá una abstracción prematura de trabajos.
- La primera necesidad asíncrona deberá reservar tiempo para diseñar fiabilidad e idempotencia, no solo instalar una herramienta.

## Evidencia

- [Roadmap técnico](../architecture/INITIALIZATION_ROADMAP.md)
