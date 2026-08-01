# Iteración 5.1 — De consulta a reserva confirmada

- **Estado:** implementada
- **Fecha:** 31 de julio de 2026
- **Módulo:** `claridez.commercial`

Esta especificación describe el primer flujo vertical funcional de Claridez tal como quedó
implementado. Gobierna únicamente el registro del interesado, la solicitud, la disponibilidad, la
cotización, su aceptación y la reserva.

## Flujo y entidades

```text
Person → EventRequest → Quotation → QuotationVersion → Reservation
  └── PersonRevision       └── QuotationLine
                 QuotationSequence
```

- `Person` es privada por organización y única por teléfono ecuatoriano E.164. `revision` aplica
  control optimista y cada creación o cambio genera un `PersonRevision` inmutable. `client` se
  deriva de haber alcanzado alguna vez una reserva confirmada, aunque después se cancele.
- `EventRequest` conserva persona, tipo normalizado en texto, intervalo, zona horaria capturada,
  invitados, necesidad, notas, origen y membresía comercial responsable.
- `Quotation` es única y estable por solicitud. `QuotationSequence` produce
  `COT-AAAA-NNNNNN` por organización y año.
- `QuotationVersion` captura snapshots de organización, persona y solicitud. Es editable solo en
  `draft`; `QuotationLine` se crea directamente, sin catálogo.
- `Reservation` vincula una versión aceptada con su intervalo `[inicio, fin)` y conserva tanto la
  provisional como cualquier confirmación, vencimiento o cancelación posterior.

Todas las entidades anteriores incluyen `organization_id`, UUID, marcas temporales y relaciones
tenant-aware. No existen borrados HTTP.

## Estados y transiciones

`EventRequest`:

```text
new → quoted → accepted → confirmed → cancelled
  └──────────────┴──────→ closed_lost
accepted → quoted                 (solo por vencimiento provisional)
```

`confirmed → closed_lost` está prohibido en servicios y PostgreSQL. `closed_lost` significa una
oportunidad perdida antes de confirmar; `cancelled` significa que existió una confirmación.

`QuotationVersion`: `draft → issued → accepted`; una emitida anterior puede quedar `superseded` o
`withdrawn`. Emitidas y terminales preservan snapshots y líneas inmutables.

`Reservation`: `provisional → confirmed | expired | cancelled`; `confirmed → cancelled`.
`expired` y `cancelled` son terminales.

## Disponibilidad y vencimiento

- Hay un solo espacio reservable implícito por organización.
- Provisionales y confirmadas bloquean el intervalo; vencidas y canceladas no bloquean.
- Una exclusión GiST sobre `(organization_id WITH =, event_interval WITH &&)`, habilitada con
  `btree_gist`, es la defensa final concurrente. El comando de aceptación se serializa por
  organización con un advisory lock transaccional para evitar deadlocks simétricos de GiST; los
  rangos adyacentes son compatibles.
- La provisional vence a las 48 horas. La evaluación transaccional e idempotente ocurre en agenda,
  lecturas de solicitud/cotización/reserva, antes de aceptar, confirmar o cancelar y antes de las
  escrituras comerciales que pueden depender de disponibilidad.
- Antes de aceptar o confirmar, la evaluación se confirma en una transacción propia para que un
  error posterior del comando no revierta el vencimiento. Al vencer, la reserva pasa a `expired`,
  deja de bloquear y la solicitud vuelve de `accepted` a `quoted` si no existe otra activa; la
  versión aceptada y su evidencia permanecen.

La zona horaria se toma de `OrganizationSettings` y se captura en solicitud, versión y reserva;
PostgreSQL guarda instantes conscientes.

## Cotización y dinero

- Moneda única `USD`, sin impuestos.
- Cantidad con tres decimales; importes y descuentos fijos por línea con dos.
- El backend calcula con `Decimal` y `ROUND_HALF_UP`:
  `line_subtotal = round(quantity × unit_price)`, `line_total = line_subtotal - discount`, y suma
  líneas para subtotal, descuento total y total.
- PostgreSQL valida cantidades positivas, importes no negativos, descuento no mayor al subtotal y
  coherencia de totales. Un trigger inmediato comprueba agregados al emitir.
- El trigger es inmediato, no diferido: el GUC de RLS es local al `authorized_tenant_scope` y se
  restaura antes del commit externo, por lo que una comprobación diferida no tendría un contexto
  tenant confiable. Las funciones son invoker, no `SECURITY DEFINER`, y se revoca `EXECUTE` a
  `PUBLIC`.
- Solo la última versión emitida, vigente y correspondiente a la revisión actual de la solicitud
  puede aceptarse. La aceptación es una constancia interna con actor, fecha, canal y nota; no es
  firma contractual.

## Confirmación y constancia del anticipo

Confirmar exige una provisional vigente y una de estas evidencias:

1. Anticipo recibido externamente: monto `> 0` y `≤ total`, fecha/hora informada, referencia,
   membresía que confirma y fecha de registro en Claridez.
2. Excepción: razón obligatoria, membresía autorizadora y fecha de autorización.

Claridez registra una constancia operativa: no procesa una transacción. No existen método de pago,
recibo, conciliación, devolución, cuenta por cobrar ni historial financiero en 5.1. La evidencia de
confirmación queda inmutable; una cancelación agrega actor, fecha y razón sin eliminarla.

## Capacidades de 5.1

| Capacidad | owner | administrator | commercial | operations | finance |
|---|:---:|:---:|:---:|:---:|:---:|
| `person:read` | ✓ | ✓ | ✓ | — | — |
| `person:manage` | ✓ | ✓ | ✓ | — | — |
| `sales:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `sales:manage` | ✓ | ✓ | ✓ | — | — |
| `availability:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `reservation:confirm` | ✓ | ✓ | ✓ | — | ✓ |
| `reservation:cancel` | ✓ | ✓ | — | — | — |
| `reservation:waive_deposit` | ✓ | ✓ | — | — | — |

Estas capacidades se exigen en backend y no se derivan de los permisos de infraestructura de la
Iteración 4. El frontend solo adapta la presentación.

## API REST

Todas las rutas privadas comienzan con `/api/v1/organizations/{organization_id}/`.

| Recurso | Operaciones |
|---|---|
| Personas | `GET/POST people/`, `GET/PATCH people/{id}/`, `GET people/{id}/revisions/` |
| Solicitudes | `GET/POST event-requests/`, `GET/PATCH event-requests/{id}/` |
| Disponibilidad | `GET availability/?from=&to=` |
| Cotizaciones | `POST event-requests/{id}/quotations/`, `GET quotations/{id}/`, `POST quotations/{id}/versions/`, `PUT quotations/{id}/versions/{version}/` |
| Comandos de cotización | `POST .../issue/`, `POST .../accept/` |
| Comandos de solicitud | `POST event-requests/{id}/close/` |
| Reservas | `GET reservations/{id}/`, `POST .../confirm/`, `POST .../cancel/` |
| Capacidades | `GET commercial/capabilities/` |

Crear, consultar y editar borradores son operaciones ordinarias. Emitir, aceptar, cerrar,
confirmar y cancelar son comandos explícitos, idempotentes cuando la transición ya alcanzó el mismo
resultado. Todos los `POST`, `PUT` y `PATCH` requieren sesión y CSRF. Una organización ajena y un
UUID inexistente producen el mismo error genérico.

## Frontend

La aplicación React conserva login y recuperación, selección organizacional y añade navegación
base, agenda semanal, solicitudes, creación/selección inline de persona, detalle comercial, editor
de líneas, versionado, emisión, aceptación, confirmación y cancelación. No añade dashboard ni
módulos vacíos.

La interfaz usa la dirección visual oficial, responde en escritorio y móvil, mantiene labels,
foco visible, navegación por teclado, estados expresados en texto y estados reales de carga, error
y vacío. El layout evita desbordamiento horizontal y usa navegación inferior en móvil.

## Tenancy, migraciones y validación

Las migraciones crean las ocho tablas, `btree_gist`, constraints, FK compuestas, triggers de
estado/historial/agregados, políticas RLS `ENABLE` + `FORCE` y privilegios mínimos. Solo
`QuotationLine` concede `DELETE` al rol de aplicación porque reemplazar líneas de un borrador lo
requiere; las demás tablas comerciales no conceden borrado.

La cobertura incluye estados, teléfono, duplicados, revisiones optimistas y concurrentes, dinero,
snapshots, SQL directo, bulk, RLS con dos organizaciones, FK cruzadas, rangos solapados/adyacentes,
vencimiento, dos aceptaciones concurrentes, capacidades, flujo HTTP completo, CSRF, OpenAPI y
frontend.

## Exclusiones mantenidas

Quedan fuera múltiples espacios, montaje, reprogramación, contratos, catálogo, PDF, firma,
impuestos, pagos, cuentas por cobrar, devoluciones, costos, rentabilidad, formulario público,
WhatsApp/correo automatizados, archivos, operación, proveedores y notificaciones asíncronas.
