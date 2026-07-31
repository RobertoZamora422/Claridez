# ADR 0003 — Fundamentos multiempresa

- **Estado:** Aceptado con aspectos provisionales
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

Claridez será un SaaS B2B para varias empresas. El aislamiento no puede añadirse después como un filtro opcional porque afecta identidad, consultas, relaciones, pruebas, archivos y operación.

La Iteración 3 produjo evidencia técnica para decidir si PostgreSQL Row-Level Security debía
acompañar los controles tenant-aware de Django. ADR 0009 registra la estrategia aceptada.

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

ADR 0011 aprueba una matriz provisional limitada a la infraestructura de la Iteración 4. No es el
contrato definitivo de permisos de módulos futuros.

## Asuntos diferidos

- Ciclos de vida no definidos expresamente para organizaciones y membresías.
- Invitaciones y registro público.
- Roles personalizados o capacidades por plan.
- Tratamiento de datos verdaderamente globales.
- Política de soporte con acceso transversal.

## Evidencia del spike y decisión adoptada

La Iteración 3 comparó:

1. Aislamiento aplicado explícitamente por la aplicación.
2. Aislamiento de aplicación más PostgreSQL RLS como defensa en profundidad.

La ejecución cubrió Django, transacciones, migraciones, procesos sin tenant, relaciones tenant-aware
y conexiones reutilizadas sin pool externo. La estrategia de aplicación tenant-aware más RLS como
defensa en profundidad fue aceptada en [ADR 0009](0009-tenant-isolation-strategy.md).

El código experimental no se convierte automáticamente en código productivo y se elimina en la
subiteración 4.0 después de conservar su protocolo, resultados y modelo de amenazas.

## Alternativas consideradas

### Base o esquema separado por organización

No se adopta en esta etapa. Podrá reevaluarse si aparecen requisitos contractuales, regulatorios o de escala que justifiquen su costo operativo.

### Filtros únicamente en la interfaz

Se descartan como mecanismo de aislamiento porque la interfaz no puede proteger por sí sola datos de API, comandos, tareas o consultas internas.

## Consecuencias

- Todo futuro diseño de datos privados deberá demostrar su pertenencia organizacional.
- La estrategia concreta de claves y relaciones deberá implementar ADR 0009 y demostrar sus
  invariantes en PostgreSQL.
- Autenticación, autorización y aislamiento se tratarán como controles relacionados pero distintos.
- La aceptación de las estrategias de tenancy e identidad habilita únicamente la subiteración que
  el propietario autorice de forma expresa.

## Evidencia

- [Línea base del producto v0.1](../product/PRODUCT_BASELINE.md)
- [Roadmap técnico](../architecture/INITIALIZATION_ROADMAP.md)
- [Resultados del spike de tenancy](../architecture/TENANCY_SPIKE_RESULTS.md)
- [ADR 0009 — Estrategia de aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0010 — Identidad local y sesiones de servidor](0010-local-identity-and-server-sessions.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)
