# ADR 0003 — Fundamentos multiempresa

- **Estado:** Aceptado con aspectos provisionales y spike pendiente
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

Claridez será un SaaS B2B para varias empresas. El aislamiento no puede añadirse después como un filtro opcional porque afecta identidad, consultas, relaciones, pruebas, archivos y operación.

Todavía no existe evidencia técnica suficiente para adoptar PostgreSQL Row-Level Security como defensa en profundidad junto con Django.

## Decisiones aceptadas

- Claridez será multiempresa desde el inicio.
- La organización será el límite principal de aislamiento de datos privados.
- Todo dato privado deberá pertenecer a una organización.
- Los usuarios podrán pertenecer a varias organizaciones mediante membresías.
- Cualquier acceso a datos privados deberá operar en un contexto organizacional validado.
- Las pruebas de aislamiento utilizarán al menos dos organizaciones e incluirán accesos cruzados.
- Moneda y zona horaria se configurarán por organización; los valores iniciales serán USD y `America/Guayaquil`.

## Aspectos provisionales

Se registran cinco perfiles iniciales provisionales y únicamente su propósito general:

- `propietario`: referente principal de la organización y de su control general.
- `administrador`: apoyo en la administración cotidiana de la organización.
- `comercial`: trabajo relacionado con la gestión comercial.
- `operaciones`: trabajo relacionado con la preparación y ejecución operativa.
- `finanzas`: trabajo relacionado con el seguimiento económico y financiero.

No se aprueba todavía una matriz de permisos, capacidades, jerarquías ni excepciones.

## Asuntos diferidos

- Ciclo de vida de organizaciones y membresías.
- Invitaciones, suspensiones y cambios de contexto.
- Roles personalizados o capacidades por plan.
- Tratamiento de datos verdaderamente globales.
- Política de soporte con acceso transversal.

## Evidencia del spike y decisión pendiente

La Iteración 3 comparó:

1. Aislamiento aplicado explícitamente por la aplicación.
2. Aislamiento de aplicación más PostgreSQL RLS como defensa en profundidad.

La ejecución cubrió Django, transacciones, migraciones, procesos sin tenant, relaciones tenant-aware
y conexiones reutilizadas sin pool externo. La evidencia recomienda aplicación más RLS, pero la
decisión se encuentra en [ADR 0009](0009-tenant-isolation-strategy.md) con estado `Propuesto`.

RLS no está adoptado ni descartado por este ADR. El código experimental no se convierte
automáticamente en código productivo.

## Alternativas consideradas

### Base o esquema separado por organización

No se adopta en esta etapa. Podrá reevaluarse si aparecen requisitos contractuales, regulatorios o de escala que justifiquen su costo operativo.

### Filtros únicamente en la interfaz

Se descartan como mecanismo de aislamiento porque la interfaz no puede proteger por sí sola datos de API, comandos, tareas o consultas internas.

## Consecuencias

- Todo futuro diseño de datos privados deberá demostrar su pertenencia organizacional.
- La estrategia concreta de claves y relaciones requiere evidencia del spike.
- Autenticación, autorización y aislamiento se tratarán como controles relacionados pero distintos.
- La Iteración 4 no podrá comenzar hasta aprobar las estrategias de tenancy e identidad.

## Evidencia

- [Línea base del producto v0.1](../product/PRODUCT_BASELINE.md)
- [Roadmap técnico](../architecture/INITIALIZATION_ROADMAP.md)
- [Resultados del spike de tenancy](../architecture/TENANCY_SPIKE_RESULTS.md)
