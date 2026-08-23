# ADR 0020 — Autoridad financiera operativa, reconocimiento e integridad de cierres

- **Estado:** Aceptado
- **Fecha:** 2026-08-22
- **Reemplaza a:** No aplica; amplía ADR 0016 y ADR 0019 sin sustituir sus autoridades
- **Reemplazado por:** No aplica

## Contexto

P10 cerró la autoridad exclusiva de obligaciones, pagos externos, aplicaciones, ajustes,
devoluciones y reversos de cuentas por cobrar. P11 debe incorporar costos, gastos, flujo operativo,
presupuestos y rentabilidad sin copiar ese historial, convertir cobros en ingreso ni presentar
contabilidad formal.

La agenda conserva una raíz estable a través de reprogramaciones, pero un evento puede cambiar de
sede. P11 necesita distinguir esa identidad estable de la sede histórica de cada hecho. También
necesita fijar qué plan se compara con lo real, reconocer el ingreso desde ejecución comprobada y
registrar hechos tardíos sin reabrir periodos cerrados.

## Decisiones aceptadas

### 1. Autoridad y fronteras

1. Se crea `claridez.finance` como autoridad exclusiva P11 de categorías financieras operativas,
   costos directos planificados y reales, gastos reales variables y recurrentes, asignaciones,
   presupuestos, movimientos de caja propios de P11, reconocimiento operativo, rentabilidad y
   cierres operativos.
2. `claridez.receivables` conserva autoridad exclusiva sobre obligación, calendario de cobro,
   pago, aplicación, ajuste P10, reverso, devolución, recibo, saldo y antigüedad.
3. P11 consume proyecciones inmutables de P10. No copia movimientos P10, no crea otro ledger y no
   materializa `SourcePeriodRegistration` por defecto.
4. Un pago recibido no es ingreso reconocido. Una aplicación tampoco es caja. P11 no cambia saldo,
   pago, devolución ni consecuencia de cancelación de P10.
5. P11 no consulta catálogo para inferir costos. Un precio comercial no es costo.
6. P11 no incluye proveedores, inventario, cuentas bancarias, conciliación, libro mayor,
   impuestos, nómina, facturación electrónica ni estados contables; esas ausencias no se modelan
   como entidades deshabilitadas.

### 2. Proyecciones intermodulares mínimas

1. `commercial.public` expone una proyección económica P11 específica, mínima e inmutable, con
   organización, versión aceptada, moneda, total y fecha de aceptación. No se reutiliza el snapshot
   documental/comercial con PII, notas, necesidades o líneas.
2. `operations.public` expone evidencia inmutable de `execution_started` y
   `execution_completed`, incluidos reserva, raíz, transición y fecha, sin ORM, `QuerySet` ni
   `EventPreparation`.
3. `scheduling.public` expone la historia mínima de reserva y sede de una raíz. No ofrece ni se
   inventa un lock global de raíz para P11.
4. `receivables.public` expone una referencia mínima de obligación y contribuciones de caja P10
   tipadas: pago, reverso de pago, devolución y reverso de devolución. Cada contribución conserva
   identificador, dirección, importe, moneda, fecha económica y fecha de registro. Aplicaciones y
   ajustes de obligación tienen efecto de caja cero y no se exportan como contribuciones.
5. Los puertos devuelven DTO congelados y valores materializados dentro de
   `authorized_tenant_scope`; no comparten modelos ORM.

### 3. Venta, obligación, cobro, caja e ingreso

1. La venta confirmada es el total de la cotización aceptada que originó la obligación de la primera
   confirmación de la raíz.
2. La obligación es el derecho de cobro P10 y puede variar por hechos explícitos P10 sin alterar por
   sí sola el ingreso P11.
3. El cobro es `ReceivedPayment`; su aplicación decide qué deuda reduce, no si existe caja o
   ingreso.
4. La entrada de caja P10 ocurre por el pago; una devolución es salida, y sus reversos restauran el
   efecto exacto.
5. El ingreso base se reconoce una sola vez cuando una reserva de la raíz alcanza
   `execution_completed`. Hasta entonces es cero, aunque haya venta, obligación o pago.
6. El ingreso se atribuye a la sede de la reserva que alcanzó `execution_completed` y a la fecha
   económica de esa transición.

### 4. Raíz estable y sede histórica

1. `root_reservation_id` identifica el evento a lo largo de reprogramaciones.
2. Todo costo directo real y toda porción de gasto vinculada a una raíz conserva un `venue_id`
   inmutable correspondiente a su hecho económico.
3. El `venue_id` debe pertenecer a una reserva observada en la historia de esa raíz. Una
   reprogramación posterior no reatribuye costos, gastos, ingreso ni snapshots cerrados.
4. Los resultados de vida del evento agrupan por raíz; los resultados por sede agrupan cada hecho
   por su sede histórica. Un mismo evento puede, por ello, aportar hechos a más de una sede.

### 5. Costos directos y baseline

1. Los planes de costo directo son revisiones publicadas append-only con líneas monetarias
   explícitas. No se derivan de catálogo.
2. La última revisión que ganó la serialización antes de `execution_started` se convierte en
   baseline inmutable para la variación del evento. `published_at` conserva la fecha declarada del
   hecho, pero no permite determinar ni retrotraer esa elegibilidad.
3. Publicar una revisión bloquea y vuelve a comprobar la preparación operativa concreta. Una vez
   iniciado el evento no puede insertarse ninguna revisión nueva, aunque declare un `published_at`
   anterior. Si la publicación adquiere primero el lock, confirma la siguiente revisión y luego
   gana la carrera, esa revisión exacta queda incluida; si el inicio gana, toda inserción falla.
4. Este es el único lock externo ordinario requerido por P11: protege la invariante transversal de
   baseline. No establece un orden global de scheduling para las demás escrituras financieras.
5. Después de iniciar ejecución, los importes conocidos son costos reales o correcciones tipadas;
   nunca reemplazan la baseline.
6. Un costo real conserva raíz, sede, categoría, moneda, importe, fecha económica, periodo de
   registro, procedencia y actor. Operaciones puede someter evidencia; solo una decisión financiera
   aprobatoria la materializa como costo real.

### 6. Gastos, recurrencia y asignación

1. `ExpenseOccurrence` es el gasto real común. Su procedencia es `manual` o `recurring`; una regla
   recurrente no afecta resultados hasta materializar una ocurrencia única para su fecha.
2. Cada ocurrencia se clasifica como variable o recurrente y se asigna completamente mediante
   porciones monetarias explícitas a negocio, sede o evento.
3. Una porción de evento exige raíz y sede históricas; una porción de sede exige sede; una porción
   de negocio no inventa sede.
4. Las asignaciones no usan porcentajes o drivers automáticos. Sus importes cuantizados deben sumar
   exactamente el importe de la ocurrencia.
5. Las correcciones de gasto son tipadas y conservan su propia asignación. No existe un reverso
   financiero genérico que pueda convertirse en ledger implícito.

### 7. Caja propia de P11

1. `OperatingCashMovement` registra únicamente una salida vinculada a un costo real o gasto real,
   o una recuperación vinculada a una salida P11 exacta.
2. La salida neta no puede exceder el costo o gasto vigente; la recuperación neta no puede exceder
   la salida vinculada.
3. Una salida contra un gasto con asignaciones declara importes monetarios por scopes exactos de la
   ocurrencia. Deben sumar exactamente el movimiento y cada scope respeta el saldo de su
   asignación; no hay porcentajes, prorrateos ni drivers implícitos.
4. La recuperación conserva las atribuciones de la salida recuperada y toda corrección declara la
   atribución que incrementa o reduce. Los límites se recomprueban bajo un lock determinista del
   gasto y el overview/CSV agregan esa caja por raíz, sede y periodo sin perder la reconciliación
   global.
5. Caja P11 no crea cuentas bancarias, saldos iniciales, transferencias, conciliación ni CRUD de
   movimientos generales.
6. Las correcciones son tipadas contra un movimiento P11 exacto y no admiten objetivos de P10.

### 8. Presupuestos

1. Los presupuestos son revisiones publicadas append-only por periodo y, opcionalmente, sede.
2. Sus líneas son asignaciones monetarias explícitas por categoría. No afectan margen, resultado ni
   caja; solo permiten comparar presupuesto con real.
3. Un periodo cerrado no admite nuevas revisiones presupuestarias.

### 9. Periodos, hechos tardíos y cierres

1. Los periodos operativos iniciales son meses completos, no se solapan, usan la zona de la
   organización y conservan moneda histórica.
2. Un hecho P11 conserva fecha económica y periodo de registro. Si su periodo económico está
   abierto, ambos periodos coinciden.
3. Si el periodo económico ya cerró, el hecho mantiene esa procedencia y se registra en el primer
   periodo posterior abierto como `prior_period_adjustment`. No se disfraza como operación ordinaria.
4. Un cierre es un snapshot append-only e irreversible. El periodo no se reabre, no se actualiza ni
   se recalcula retrospectivamente.
5. El snapshot conserva fórmulas, totales ordinarios, ajustes de periodos anteriores, cutoffs,
   referencias exactas e hashes de las contribuciones P10 realmente visibles y utilizadas por esa
   transacción de cierre. No crea un índice espejo P10.
6. Una fuente P10 pertenece a un cierre solo si su pareja exacta de tipo e identificador consta en
   las referencias de ese snapshot. `registered_at <= closed_at` o un timestamp anterior al cutoff
   no prueba inclusión. Una transacción P10 iniciada antes del cierre pero confirmada después se
   registra en el primer periodo posterior aplicable como ajuste de periodo anterior.
7. Las fuentes P10 se clasifican determinísticamente por identificador, fecha económica y fecha de
   registro, y por pertenencia exacta a las referencias de cierres previos. Solo una futura
   invariante demostrada mediante otro ADR podría autorizar materialización persistente de una
   fuente externa.
8. La rentabilidad de vida del evento incorpora después hechos tardíos con su etiqueta económica;
   el snapshot de un cierre permanece fijo. La reconciliación explica la diferencia.

### 10. Reconocimiento y correcciones

1. `RecognitionAdjustment` solo aplica a una raíz completada y exige dirección, importe positivo,
   moneda, fecha económica, razón tipada, evidencia y actor.
2. No puede representar penalidad, pérdida de anticipo, crédito, deber de devolución, extinción de
   deuda ni otra consecuencia de cancelación abierta por ADR 0019. No nace automáticamente de P10
   o scheduling y nunca modifica venta, obligación, pago, devolución o caja.
3. Sus correcciones enlazan el ajuste exacto; no existe reverso genérico.

### 11. Fórmulas monetarias

Todos los importes usan `Decimal`, `numeric(18,2)`, cuantización `0.01` y `ROUND_HALF_UP`; no hay
`float` ni FX.

```text
ingreso_reconocido_evento
  = total_venta si execution_completed, de lo contrario 0
  + ajustes_reconocimiento_netos

margen_bruto = ingreso_reconocido - costos_directos_reales_netos
margen_contribucion = margen_bruto - gastos_variables_asignados_netos
resultado_operativo = margen_contribucion - gastos_recurrentes_asignados_netos
rentabilidad_porcentaje = resultado_operativo / ingreso_reconocido * 100
                          si ingreso_reconocido > 0; de lo contrario no calculable

flujo_neto = contribuciones_caja_P10 + movimientos_caja_P11
```

En P10: pago `+`, reverso de pago `-`, devolución `-`, reverso de devolución `+`. Aplicación y
ajuste de obligación valen cero para caja. Un reporte de periodo presenta por separado operación
ordinaria, ajustes de periodos anteriores y total presentado.

### 12. Autorización, tenancy, inmutabilidad e idempotencia

1. P11 define capacidades atómicas de lectura, categorías, planificación, reales/evidencia,
   recurrencia, asignación, presupuestos, caja, reconocimiento, cierre y exportación.
2. Propietario, administrador y finanzas administran P11. Operaciones solo somete evidencia con
   `finance:submit_evidence` y una relación operativa real; no aprueba ni lee rentabilidad.
   Comercial no recibe capacidades P11.
3. Toda operación privada completa dentro de `authorized_tenant_scope`. Todas las tablas privadas
   usan `ENABLE` + `FORCE RLS`, FKs tenant-aware y privilegios mínimos.
4. Hechos, revisiones publicadas, decisiones y cierres son append-only; `claridez_app` no recibe
   `DELETE` ni `TRUNCATE`.
5. Los comandos monetarios son idempotentes por organización, tipo, UUID y hash de payload.
6. Los locks internos se adquieren en orden determinista: periodos por inicio/id, agregado fuente
   por tipo/id, gasto y sus scopes para caja atribuida, asignaciones/objetivos y finalmente
   movimiento o corrección. Se usan locks externos solo para la baseline descrita en la sección 5.

### 13. Migración

1. P11 se instala vacío sobre P10 final. No existe backfill de costos, gastos, ingresos reconocidos,
   presupuestos o caja P11 porque P10 no contiene esos hechos.
2. La migración añade puertos y estructuras P11 sin copiar filas de `receivables` ni catálogo.
3. La migración correctiva añade la atribución de caja sin inventar un prorrateo histórico: falla
   cerradamente si encuentra movimientos P11 de gasto preexistentes sin esa procedencia explícita.
4. Debe probarse instalación desde cero y migración desde P10 final, seguidas de RLS, privilegios,
   guardianes, dos tenants, ORM, bulk, SQL directo, concurrencia e idempotencia.

## Aspectos provisionales

- Los nombres físicos de revisiones, líneas y correcciones podrán ajustarse si conservan las
  identidades, tipado y fronteras de este ADR.
- La primera web P11 puede presentar una superficie operativa unificada; P13 decidirá dashboards y
  reportes guardados sin duplicar estas fórmulas.

## Asuntos diferidos

- Penalidades, pérdida de anticipos, créditos y deber jurídico de devolución siguen bajo el cierre
  fail-closed de ADR 0019.
- Proveedores, compras, recursos, inventario y valoración operativa pertenecen a P12.
- Drivers automáticos de asignación, FX, conciliación bancaria, contabilidad, impuestos, nómina,
  facturación electrónica y cuentas bancarias quedan fuera.
- Una materialización persistente de atribución de fuentes externas requerirá invariante concreta y
  ADR posterior; no se incluye en P11.

## Validación observada

El cierre correctivo del 23 de agosto de 2026 sincronizó 88 paquetes Python y 253 npm, sin
vulnerabilidades npm observadas. El reset protegido y la instalación limpia aplicaron
`finance.0001`–`0005`; el rollback hasta P10 final y la reaplicación al head fueron deterministas.
La puerta aprobó 217 pruebas API no integración con 76% de cobertura, 28 frontend y una repetición
completa de 91 integraciones PostgreSQL, además de locks, migraciones sin cambios, RLS/privilegios,
formatos, lint, tipos, OpenAPI sin warnings y builds. La primera pasada de integración terminó
90/91 por un deadlock transitorio en la carrera P8 hold↔block; esa prueba aprobó aislada y las 91
aprobaron después en el mismo orden completo, sin cambios P8.

Las pruebas correctivas cubren SQL retrodatado, ORM/bulk/SQL con `claridez_app`, publicación contra
`execution_started`, pago y devolución P10 sin confirmar durante un cierre, atribuciones de caja de
gasto divididas entre eventos/sedes, salida parcial, recuperación, corrección, filtros y
reconciliación CSV. La evidencia es local, no incluye navegador manual y no presume CI remota,
despliegue ni cutover de un entorno destino.

La base de pruebas migrada confirmó `claridez_app = SELECT, INSERT` y ausencia de
`UPDATE/DELETE/TRUNCATE` sobre finance. Una comprobación adicional de `claridez_local` después de
`tools/local_database.py prepare` observó `(SELECT, INSERT, UPDATE, DELETE, no TRUNCATE)`: el helper
local vuelve a conceder privilegios que la migración había revocado. Los triggers append-only aún
rechazan cambios, pero ese entorno no reproduce privilegio mínimo. El hallazgo no se corrigió por
quedar fuera de los tres defectos focalizados y debe resolverse antes de usar esa base como
evidencia de privilegios efectivos.

## Alternativas consideradas

- **Extender `receivables`:** descartado porque mezclaría cuentas por cobrar con rentabilidad.
- **Usar el snapshot comercial documental:** descartado por PII y detalle innecesario.
- **Reconocer ingreso al vender, obligar o cobrar:** descartado porque confunde compromisos y caja
  con ejecución económica.
- **Crear un ledger financiero general:** descartado porque duplicaría P10 y anticiparía
  contabilidad.
- **Derivar costo de catálogo:** descartado porque el precio de venta no prueba un costo.
- **Reabrir cierres por hechos tardíos:** descartado porque destruye reproducibilidad.
- **Bloquear siempre scheduling o la raíz:** descartado porque el puerto no ofrece esa primitiva y
  P11 tiene invariantes y orden de locks propios.
- **Persistir todas las fuentes P10 en P11:** descartado porque sería un índice/ledger espejo.

## Consecuencias

- Claridez separa cartera, caja e ingreso y puede explicar rentabilidad por evento, sede y periodo.
- La sede histórica y la baseline sobreviven reprogramaciones posteriores.
- Los cierres son reproducibles, aunque la rentabilidad de vida del evento pueda incorporar hechos
  tardíos después; la diferencia queda explícita.
- El modelo append-only y las correcciones tipadas aumentan el número de hechos a cambio de impedir
  edición silenciosa o un reverso genérico ambiguo.

## Evidencia

- [Blueprint maestro](../product/PRODUCT_BLUEPRINT.md)
- [Roadmap de entrega](../product/PRODUCT_DELIVERY_ROADMAP.md)
- [Contrato funcional P11](../product/P11_FINANCE_OPERATIONAL_CONTROL_SPECIFICATION.md)
- [ADR 0009 — Aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0011 — Autorización backend-first](0011-organizations-memberships-and-authorization.md)
- [ADR 0016 — Raíz y reprogramación](0016-scheduling-ownership-and-temporal-integrity.md)
- [ADR 0019 — Autoridad de cuentas por cobrar](0019-receivables-authority-and-financial-movement-integrity.md)
