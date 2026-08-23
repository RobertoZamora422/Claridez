# P11 — Contrato funcional breve de control financiero operativo

## 1. Propósito y límites

P11 permite a propietario, administrador y finanzas registrar y comparar costos, gastos,
presupuestos, caja y rentabilidad operativa por evento, sede y periodo. `claridez.finance` es su
autoridad. P10 permanece como única autoridad de cobros y cuentas por cobrar.

No incluye catálogo de costos, proveedores, inventario, compras P12, cuentas bancarias,
conciliación, libro mayor, impuestos, nómina, facturación electrónica ni contabilidad formal.

## 2. Identidades y evidencia externa

- La raíz de reserva identifica el evento de forma estable.
- La sede de cada costo real y porción de gasto vinculada al evento se captura al registrar el
  hecho y no cambia por reprogramaciones posteriores.
- El ingreso usa la sede de la reserva completada.
- La venta se obtiene de la proyección económica mínima de la cotización aceptada.
- El inicio y fin de ejecución se obtienen de proyecciones mínimas de operations.
- El flujo P10 se obtiene de contribuciones tipadas; no se copian pagos o devoluciones.

## 3. Flujos

### 3.1 Preparar y congelar costo planificado

1. Finanzas publica una revisión con raíz, sede, moneda, razón y líneas de categoría/importe.
2. La publicación bloquea la preparación concreta y comprueba que no haya iniciado.
3. La última revisión publicada antes o al inicio es la baseline del evento.
4. Después del inicio, otra publicación falla. Los importes posteriores se registran como reales o
   correcciones tipadas.

### 3.2 Registrar costo directo real

1. Finanzas registra raíz, sede histórica, categoría, importe, moneda, fecha económica, evidencia y
   razón; o Operaciones somete evidencia con esos datos.
2. La sede debe pertenecer a la historia de la raíz.
3. Una decisión financiera aprobatoria materializa exactamente un costo por evidencia; rechazar no
   afecta resultados.
4. El costo y sus correcciones son append-only.

### 3.3 Registrar gasto

1. Una ocurrencia real declara tipo variable/recurrente y procedencia manual/recurrente.
2. La ocurrencia incluye porciones explícitas que suman exactamente el importe.
3. Cada porción apunta a negocio, sede o evento; una porción de evento exige raíz y sede histórica.
4. Una regla recurrente solo crea resultados al materializar una ocurrencia única para su fecha.
5. Las correcciones enlazan una ocurrencia y conservan asignación explícita.

### 3.4 Presupuestar

Finanzas publica revisiones append-only por periodo y sede opcional. Cada revisión contiene líneas
por categoría. El presupuesto no altera resultados ni caja y no se publica sobre periodos cerrados.

### 3.5 Registrar caja P11

1. Una salida enlaza un costo o gasto real exacto.
2. Una recuperación enlaza una salida P11 exacta.
3. Los límites netos se comprueban bajo locks deterministas.
4. Una corrección enlaza el movimiento exacto. No se aceptan objetivos P10 ni movimientos libres.

### 3.6 Ajustar reconocimiento

Solo una raíz completada admite ajuste. La razón debe pertenecer al catálogo cerrado de medición,
omisión o duplicidad; una razón de cancelación, penalidad, anticipo, crédito o devolución falla
cerradamente. El ajuste no altera P10 ni caja.

### 3.7 Cerrar periodo

1. Los periodos son meses completos no solapados.
2. El cierre calcula la respuesta backend, separa operación ordinaria y ajustes anteriores, fija
   cutoff/hash/referencias P10 y guarda un snapshot inmutable.
3. Un periodo cerrado no se reabre ni acepta nuevos hechos ordinarios.
4. Un hecho tardío conserva periodo económico y se registra en el primer periodo posterior abierto
   como ajuste anterior.
5. Consultar un cierre devuelve el snapshot; consultar la vida del evento incluye hechos tardíos y
   muestra la reconciliación.

## 4. Capacidades

| Capacidad | Propietario | Administrador | Comercial | Operaciones | Finanzas |
| --- | --- | --- | --- | --- | --- |
| `finance:read` | Sí | Sí | No | No | Sí |
| `finance:manage_categories` | Sí | Sí | No | No | Sí |
| `finance:plan_costs` | Sí | Sí | No | No | Sí |
| `finance:record_actuals` | Sí | Sí | No | No | Sí |
| `finance:submit_evidence` | Sí | Sí | No | Sí | Sí |
| `finance:allocate_expenses` | Sí | Sí | No | No | Sí |
| `finance:manage_recurring` | Sí | Sí | No | No | Sí |
| `finance:record_cash` | Sí | Sí | No | No | Sí |
| `finance:manage_budgets` | Sí | Sí | No | No | Sí |
| `finance:adjust_recognition` | Sí | Sí | No | No | Sí |
| `finance:close_period` | Sí | Sí | No | No | Sí |
| `finance:export` | Sí | Sí | No | No | Sí |

Operaciones necesita además `operation:manage` y una relación real con la preparación para someter
evidencia. La API, no React, decide todas las capacidades.

## 5. Fórmulas y presentación

Se aplican las fórmulas y signos de ADR 0020. Todo importe JSON se representa como decimal con dos
posiciones. Los reportes declaran moneda, zona, periodo, filtros y si cada importe es ordinario o
ajuste anterior. La rentabilidad porcentual es `null` cuando el ingreso reconocido no es positivo.

La variación de costo de evento es:

```text
variacion_costo = costo_directo_real_neto - baseline_planificada
```

El frontend presenta resultados del backend y no recalcula fórmulas.

## 6. API funcional

La superficie vive bajo `/api/v1/organizations/{organization_id}/finance/` y ofrece:

- capabilities y contexto mínimo de evidencia;
- overview por periodo, sede o raíz;
- comandos explícitos e idempotentes para categorías, periodos, planes, evidencias/decisiones,
  costos, correcciones, reglas/ocurrencias, gastos/asignaciones, presupuestos, caja,
  reconocimiento y cierre;
- exportación CSV con los mismos filtros y permisos del overview.

No hay `DELETE`, `PATCH` libre ni CRUD genérico de hechos.

## 7. Errores cerrados relevantes

- recurso o tenant no disponible: `404` sin revelar existencia;
- capability ausente: `403`;
- payload/moneda/escala/periodo/asignación inválidos: `400`;
- retry divergente, periodo cerrado, baseline iniciada, doble materialización o concurrencia:
  `409`;
- consecuencia de cancelación no autorizada: `409 cancellation_consequence_not_authorized`.

## 8. Criterio de aceptación

P11 queda aceptada cuando migraciones, puertos, dominio, API, OpenAPI y web demuestran instalación
desde cero y migración desde P10; dos tenants; RLS/privilegios; ORM, bulk y SQL directo;
concurrencia e idempotencia; reprogramación entre sedes; baseline antes/después del inicio; hechos
tardíos y cierres; redondeo; exportación; y regresiones P10, P8 y operations sin catálogo, P12,
duplicación P10 o contabilidad formal.
