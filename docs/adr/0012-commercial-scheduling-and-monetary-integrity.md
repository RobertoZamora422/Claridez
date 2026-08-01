# ADR 0012 — Integridad de agenda y cotizaciones comerciales

- **Estado:** Aceptado
- **Fecha:** 2026-07-31
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

El primer flujo funcional debe impedir reservas incompatibles bajo concurrencia, preservar las
versiones emitidas y validar importes incluso ante ORM bulk o SQL directo, sin introducir múltiples
espacios ni un módulo financiero.

## Decisiones aceptadas

- Cada organización tiene un espacio implícito y sus reservas usan `tstzrange` con límites `[)`.
- PostgreSQL habilita `btree_gist` y aplica una exclusión GiST por organización y solapamiento solo
  a reservas `provisional` o `confirmed`.
- La aceptación toma un advisory lock transaccional derivado de la organización. Esto serializa
  únicamente las inserciones del espacio único y evita deadlocks simétricos del índice GiST; la
  exclusión continúa siendo la defensa final.
- Todas las relaciones privadas disponen de FK compuestas por `organization_id` y clave destino,
  además de RLS forzado conforme a ADR 0009.
- Versiones emitidas y terminales, líneas asociadas y revisiones de persona son inmutables en
  PostgreSQL. Triggers adicionales restringen transiciones de solicitud y reserva.
- Los cálculos canónicos se realizan en backend con `Decimal` y `ROUND_HALF_UP`. Checks por línea y
  versión más un trigger de agregados impiden cantidades, descuentos o totales inconsistentes.
- La comprobación de agregados se ejecuta inmediatamente al emitir. No se usa constraint trigger
  diferido porque `authorized_tenant_scope` restaura el GUC local antes del commit externo y una
  función invoker diferida no conservaría un contexto RLS confiable.
- Las funciones de trigger no son `SECURITY DEFINER`, fijan un `search_path` seguro y revocan
  ejecución a `PUBLIC`. El rol normal conserva solo el DML necesario.

## Consecuencias

- Dos aceptaciones concurrentes para intervalos solapados dejan exactamente una reserva activa.
- Los rangos adyacentes son válidos sin lógica especial en aplicación.
- Reemplazar líneas requiere `DELETE` únicamente sobre `commercial_quotationline`; no se concede
  borrado sobre el resto de tablas comerciales.
- Una futura agenda con espacios múltiples requerirá un ADR que reemplace la clave de exclusión.

## Asuntos diferidos

- Múltiples espacios, buffers de montaje/desmontaje y reprogramación.
- Impuestos, pagos, cuentas por cobrar y cualquier libro financiero.
- Un job asíncrono de vencimiento; en 5.1 se evalúa oportunistamente en los puntos del flujo.
