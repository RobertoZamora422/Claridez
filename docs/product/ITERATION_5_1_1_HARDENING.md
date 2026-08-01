# Iteración 5.1.1 — Endurecimiento y cierre del flujo comercial

- **Estado:** implementada
- **Fecha:** 31 de julio de 2026
- **Módulo:** `claridez.commercial`

Esta subiteración cierra brechas de autorización, integridad PostgreSQL, consistencia histórica e
identidad visual encontradas al auditar 5.1. No amplía el flujo comercial ni modifica su matriz de
capacidades.

## Hallazgos y correcciones

### Datos personales

Las respuestas de cotizaciones incluían los snapshots completos de la persona para todo actor con
`sales:read`. Esto permitía que `operations` y `finance`, sin `person:read`, recuperaran nombre,
teléfono y correo. La base de datos sigue conservando el snapshot íntegro, pero la representación
HTTP y de servicios ahora entrega `person: {restricted: true}` cuando el actor no tiene
`person:read`.

Solicitudes, cotizaciones, reservas y disponibilidad se probaron para los cinco roles. Las
respuestas estructuradas de `operations` y `finance` no contienen esos tres datos personales; los
tres roles con `person:read` los reciben normalmente. La matriz de capacidades no cambió. Los
campos de texto libre pueden contener información introducida por un usuario y no se someten a
clasificación automática en esta iteración.

### Integridad monetaria

La migración `commercial/0003_hardening_5_1_1` añade el constraint
`commercial_quoteline_subtotal_product`. PostgreSQL exige ahora:

```text
line_subtotal = ROUND(quantity * unit_price, 2)
line_total = line_subtotal - discount_amount
```

Se conserva la validación existente de cantidades e importes no negativos y del descuento máximo.
El backend continúa usando `Decimal` y `ROUND_HALF_UP`; para los valores decimales admitidos, la
función `ROUND(numeric, 2)` de PostgreSQL aplica el mismo redondeo de mitades. Las pruebas cubren
ORM, `bulk_create`, SQL directo y agregados aparentemente consistentes construidos sobre una
multiplicación incorrecta.

### Coherencia de reservas

La misma migración crea un trigger `BEFORE INSERT OR UPDATE` que exige que cada reserva:

- se vincule con una versión aceptada;
- use la solicitud de la cotización a la que pertenece esa versión;
- conserve exactamente el intervalo `[inicio, fin)` del snapshot;
- conserve la zona horaria del snapshot.

La función es invoker, fija su `search_path`, no usa `SECURITY DEFINER` y no concede ejecución a
`PUBLIC`. Las FK compuestas tenant-aware y la exclusión GiST continúan siendo defensas separadas.
La aceptación actualiza versión y solicitud y crea la provisional dentro de un savepoint atómico;
si el horario se solapa, las tres operaciones se revierten.

### Revisiones sin cambios

`PATCH` de personas y solicitudes adopta semántica idempotente: responde `200` con la
representación actual cuando solo se envía `revision` o cuando los valores son iguales después de
normalización. No incrementa `revision`, no altera `updated_at` y, para personas, no crea
`PersonRevision` artificial.

### Identidad visual

El frontend usa los SVG del paquete oficial incluido en `docs/Claridez_Brand_Assets_v1.0`; ya no dibuja
ni aproxima un símbolo mediante CSS. El favicon proviene del mismo paquete oficial. Inter y Plus
Jakarta Sans se cargan localmente desde dependencias FontSource fijadas en el lockfile, limitadas al
subconjunto latino. El título HTML identifica el producto como centro de control comercial.

`Brand.tsx` concentra la selección de logotipo horizontal e isotipo según el fondo. `App.tsx`
conserva el flujo y la accesibilidad existentes; no se añadieron pantallas ni módulos.

## Migración y reversibilidad

`0003_hardening_5_1_1` depende de las migraciones publicadas de 5.1 y no las modifica. Su reversión
elimina el trigger y su función y retira el constraint monetario; su reaplicación los reconstruye.
No concede privilegios adicionales al rol de aplicación.

## Alcance de pruebas

La cobertura dirigida incluye los cinco roles, dos organizaciones, servicios y HTTP, `PATCH`
idempotente, ORM, bulk, SQL directo, redondeo, inmutabilidad, coherencia de reservas y dos
aceptaciones concurrentes. La validación de cierre observada fue:

- `npm run check`: `129` pruebas backend y `3` frontend, tipado, lint, OpenAPI y builds correctos;
- `npm run check:all`: PostgreSQL 17 en UTF-8, sin migraciones pendientes, las mismas pruebas
  locales y `29` integraciones PostgreSQL correctas;
- `npm run audit`: sin vulnerabilidades conocidas en Python ni npm;
- migración `0003` aplicada desde el estado actual, revertida a `0002` y reaplicada; la base
  efímera de integración aplicó todas las migraciones desde cero;
- revisión interactiva en `1280 × 720` y `390 × 844`: sin desbordamiento horizontal, navegación
  responsive, labels y estados textuales presentes, activos y fuentes locales cargados, y consola
  sin errores ni advertencias de aplicación;
- `git diff --check` y validación estricta de UTF-8/LF correctos.

Estas comprobaciones no sustituyen la defensa backend-first.

## Exclusiones y deuda técnica

Se mantienen fuera operación, finanzas, pagos, cuentas por cobrar, contratos, catálogo, múltiples
espacios, reprogramación, portal público, notificaciones e infraestructura remota.

`services.py` y `App.tsx` siguen siendo archivos amplios. En 5.1.1 se extrajo solo la identidad de
marca porque era un límite cohesivo y necesario; dividir servicios por agregado y la interfaz por
pantalla queda como refactor futuro, antes de ampliar el módulo, para evitar mezclarlo con cambios
funcionales de este cierre.
