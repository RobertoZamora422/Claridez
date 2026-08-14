# ADR 0019 — Autoridad de cuentas por cobrar e integridad de movimientos financieros

- **Estado:** Aceptado
- **Fecha:** 2026-08-14
- **Reemplaza a:** No aplica; amplía ADR 0012, ADR 0016, ADR 0017 y ADR 0018 sin
  sustituir sus autoridades
- **Reemplazado por:** No aplica

## Contexto

Claridez ya conserva cotizaciones aceptadas inmutables, raíces de reserva con confirmación y
reprogramación, preparación operativa y evidencia documental. Sin embargo, la constancia de
anticipo de 5.1 solo afirma que un usuario interno declaró dinero recibido externamente. No existe
todavía una autoridad de cuentas por cobrar, pagos, aplicaciones, saldos, reversos, devoluciones,
recibos o antigüedad de cartera.

P10 debe incorporar esa autoridad sin convertir `EventRequest`, una cotización aceptada, una
reserva sucesora, un contrato, una aceptación documental o un PDF en una segunda fuente económica.
También debe preservar la entrada funcional de confirmación vigente, la atomicidad con
`claridez.operations`, la raíz e historia de P8 y la plataforma privada de archivos de P9.

Los movimientos financieros deben resistir retries, concurrencia, ORM bulk y SQL directo con el rol
de aplicación. La migración desde P9 debe reconocer honestamente la semántica limitada de las
constancias 5.1 y no inventar pagos, vencimientos ni consecuencias económicas.

## Decisiones aceptadas

### 1. Propiedad modular y fronteras

1. `claridez.receivables` será la autoridad exclusiva de:
   - obligaciones por cobrar;
   - calendario operativo de vencimientos;
   - pagos recibidos externamente;
   - aplicaciones de pagos;
   - ajustes, reversos y devoluciones registradas;
   - saldo y estados derivados;
   - antigüedad de cartera;
   - recibos lógicos y estados de cuenta.
2. No se creará `claridez.finance`. Ese nombre anticiparía costos, gastos, cuentas por pagar, flujo y
   rentabilidad, que pertenecen a P11.
3. Se conservan las autoridades existentes:
   - `claridez.commercial`: `EventRequest`, `QuotationVersion`, aceptación y snapshots comerciales;
   - `claridez.scheduling`: reserva, raíz, confirmación, cancelación, reprogramación e historia de
     agenda;
   - `claridez.people`: identidad canónica de la contraparte;
   - `claridez.documents`: archivos, artefactos, hashes, escaneo, almacenamiento y render;
   - `claridez.operations`: preparación y ejecución, sin hechos financieros.
4. Los módulos se integrarán mediante puertos estrechos y DTO o proyecciones inmutables. No se
   compartirán modelos ORM, managers, `QuerySet`, iteradores lazy ni acceso disperso a tablas ajenas.
5. `receivables` será la única autoridad del significado financiero. Una proyección comercial, un
   archivo, un PDF o un registro documental no podrá crear ni modificar un movimiento monetario.

### 2. Fuente canónica de la obligación

1. El hecho generador será la primera confirmación autoritativa de una raíz de reserva. Existirá
   exactamente una obligación por `(organization_id, root_reservation_id)` que haya alcanzado esa
   confirmación.
2. La obligación no nace de:
   - `EventRequest`, que representa intención comercial;
   - mera aceptación de `QuotationVersion`, porque la provisional todavía puede expirar;
   - emisión de un instrumento contractual;
   - aceptación documental;
   - una reserva sucesora por reprogramación.
3. La confirmación consolida el compromiso comercial y operativo, y materializa la relación
   conceptual `Reservation → Receivable` del Blueprint. Una cancelación posterior no borra que la
   raíz fue confirmada.
4. La obligación copiará como snapshot económico la `QuotationVersion` aceptada exacta:
   - organización, solicitud, contraparte, raíz y versión de cotización;
   - moneda;
   - subtotal;
   - descuentos;
   - total;
   - identificador y número de versión;
   - únicamente los términos económicos estructurados que realmente existan en la fuente.
5. El monto original será inmutable. Nunca se reconstruirá desde catálogo vigente, campos libres,
   contratos, PDFs o configuración actual de la organización.

### 3. Coordinación transaccional de la confirmación

1. La entrada HTTP y la experiencia de «confirmar reserva» conservarán su ruta, propósito y
   alternativas de anticipo externo o waiver. La implementación P10 añadirá idempotencia al comando
   sin convertirlo en un CRUD financiero.
2. La orquestación transversal pertenecerá a un coordinador de caso de uso de la capa de aplicación,
   fuera de los módulos de dominio. El nombre físico de esa capa podrá ajustarse, pero el coordinador
   no tendrá tablas ni autoridad de negocio propia.
3. La fachada HTTP llamará al coordinador. Este consumirá puertos estrechos de `commercial`,
   `scheduling`, `operations`, `people`, `documents` y `receivables`. Ninguno de esos dominios
   importará al coordinador.
4. En particular, `claridez.scheduling` no importará `claridez.receivables`. Scheduling expondrá la
   operación de confirmación que le pertenece y seguirá siendo autoridad de su `ScheduleEvent`; el
   coordinador compondrá sus efectos con los de P10.
5. El coordinador abrirá un único `authorized_tenant_scope` y una única transacción exterior,
   validará todas las capabilities requeridas y pasará valores escalares/DTO inmutables a los puertos.
   Ningún acceso lazy sobrevivirá al scope.
6. Una confirmación mediante anticipo ejecutará como una unidad:

   ```text
   registrar ReceivedPayment
     → confirmar Reservation mediante scheduling
     → crear ReceivableObligation
     → aplicar el pago a la obligación
     → completar las consecuencias comerciales y operativas vigentes de P8
   ```

7. Una confirmación mediante waiver ejecutará como una unidad:

   ```text
   confirmar Reservation mediante scheduling
     → crear ReceivableObligation
     → completar las consecuencias comerciales y operativas vigentes de P8
   ```

   El waiver elimina solo la condición de anticipo para confirmar; no crea un pago ni reduce saldo.

8. Cualquier fallo revertirá el pago, la confirmación, la obligación, la aplicación, el evento de
   agenda y la preparación. No habrá un estado confirmado sin obligación, una obligación sin
   confirmación ni un anticipo aplicado dos veces.
9. Confirmar mediante anticipo exigirá conjuntamente `reservation:confirm`,
   `receivables:record_payment` y `receivables:apply_payment`. Por ello, `comercial` no podrá
   registrar ni aplicar indirectamente un pago mediante esta ruta. El waiver conservará además
   `reservation:waive_deposit` y su matriz vigente.
10. Los servicios de scheduling dejarán de ser la capa que conoce todos los efectos externos de la
    confirmación. La migración de esa orquestación preservará los guardianes y resultados de P8.

### 4. Compatibilidad de evidencia 5.1

1. `Reservation.confirmation_kind`, `recognized_deposit_amount`, `deposit_reported_at` y
   `deposit_reference` podrán conservarse como snapshot histórico y de compatibilidad de la evidencia
   que permitió confirmar.
2. Después del cutover P10 esos campos:
   - no serán autoridad financiera;
   - no se usarán para calcular saldo;
   - no se interpretarán como procesamiento o verificación bancaria;
   - no formarán una segunda bitácora monetaria.
3. Si siguen poblándose para compatibilidad, sus valores procederán exclusivamente del
   `ReceivedPayment` canónico creado por el coordinador y conservarán la inmutabilidad PostgreSQL
   vigente.
4. Las sucesoras por reprogramación continuarán referenciando la misma `confirmation_source`; no
   copiarán ni originarán otro pago.

### 5. Guardián confirmación–obligación

1. Una unicidad inmediata impedirá más de una obligación por
   `(organization_id, root_reservation_id)`.
2. Después del backfill, constraint triggers PostgreSQL `DEFERRABLE INITIALLY DEFERRED` comprobarán
   al final de la transacción:
   - toda raíz con una confirmación canónica tiene exactamente una obligación;
   - toda obligación referencia una raíz que alcanzó confirmación;
   - organización, solicitud y `QuotationVersion` coinciden en ambos dominios;
   - la obligación conserva el snapshot de la versión aceptada que confirmó la raíz.
3. La confirmación canónica se demostrará mediante el `ScheduleEvent` de confirmación y la evidencia
   coherente de `confirmation_source`. Una discrepancia entre ambos abortará el commit.
4. Los triggers se instalarán sobre todas las tablas fuente cuya escritura pueda romper la
   invariante. Serán funciones invoker, con `search_path` seguro, ejecución revocada a `PUBLIC` y
   restauración segura del GUC tenant incluso ante error. No usarán `SECURITY DEFINER` para eludir
   RLS.
5. Las raíces nunca confirmadas no tendrán obligación. Cancelar o reprogramar una raíz confirmada no
   elimina su obligación histórica.
6. La unicidad, el guardián y los privilegios se aplicarán también a ORM, operaciones bulk, SQL
   directo, retries y carreras con `claridez_app`.

### 6. Hechos y proyecciones de cuentas por cobrar

Los nombres físicos podrán ajustarse, pero se conservarán estas identidades:

1. **`ReceivableObligation`.** Núcleo inmutable con raíz, contraparte, oportunidad, cotización y
   snapshot económico original.
2. **Revisión de calendario y vencimientos.** Una revisión append-only agrupa cero o más vencimientos
   operativos y registra procedencia, razón, actor y momento.
3. **`ReceivedPayment`.** Declaración inmutable de dinero recibido externamente por la organización.
4. **`PaymentApplication`.** Asignación append-only de parte de un pago a una obligación y,
   opcionalmente, a un vencimiento.
5. **Ajuste.** Movimiento append-only que aumenta o disminuye la obligación por una corrección P10
   explícita.
6. **Reverso.** Contramovimiento completo enlazado con el movimiento exacto que corrige.
7. **`RefundRecord`.** Declaración append-only de una devolución ejecutada externamente por el salón.
8. **Recibo lógico.** Snapshot inmutable de un pago y sus aplicaciones al emitirlo.
9. **Registro de comandos y revisión migratoria.** Evidencia de idempotencia y de fuentes históricas
   que no pudieron convertirse honestamente.

Saldo, estado de satisfacción, mora, antigüedad, cartera y estado de cuenta serán proyecciones. No
existirá una tabla o campo de saldo manual ni un `status` financiero mutable para abierta, parcial,
satisfecha o vencida.

### 7. Modelo monetario y ecuaciones operacionales

1. Todo importe P10 usará `Decimal`; nunca `float`.
2. PostgreSQL usará `numeric(18,2)` para importes monetarios. Los comandos cuantizarán a `0.01` con
   `ROUND_HALF_UP` antes de persistir y PostgreSQL verificará escala e invariantes.
3. Los movimientos almacenarán importes estrictamente positivos. El tipo/dirección expresa el efecto
   económico; no se usarán números negativos arbitrarios. Cero solo será un resultado derivado.
4. Cada obligación y pago conservará moneda ISO 4217 mayúscula. Aplicación, ajuste, reverso y
   devolución exigirán igualdad de moneda con sus fuentes.
5. No habrá conversión FX. Cambiar la moneda organizacional no reescribe historia.
6. Para una obligación:

   ```text
   obligación_ajustada
     = total_original
     + Σ efecto_firmado(ajustes y sus reversos)

   aplicado_neto
     = Σ aplicaciones
     - Σ reversos de aplicaciones
     - Σ porciones devueltas que reabren aplicaciones
     + Σ reversos de esas devoluciones

   saldo_pendiente = obligación_ajustada - aplicado_neto
   ```

7. Un ajuste de aumento tiene efecto positivo, uno de disminución efecto negativo y su reverso el
   efecto exacto opuesto. Para un pago:

   ```text
   pago_efectivo = importe_recibido - reverso_completo_del_pago

   sin_aplicar
     = pago_efectivo
     - aplicado_neto_del_pago
     - devoluciones_netas_del_pago
   ```

   `devoluciones_netas_del_pago` incluye toda devolución activa, tanto la vinculada a una aplicación
   como la que devuelve dinero sin aplicar.

8. Los contramovimientos se suman como hechos; no reescriben ni ocultan el original. Constraints y
   guardianes exigirán `obligación_ajustada >= 0`, `saldo_pendiente >= 0` y `sin_aplicar >= 0`. No se
   aplicará `max(0, …)` para encubrir una inconsistencia.
9. Una devolución de dinero previamente aplicado enlazará las aplicaciones y reabrirá exactamente
   ese importe. Una devolución de dinero sin aplicar reducirá solo el disponible del pago. El mismo
   importe no afectará dos veces el saldo.

### 8. Calendario operativo y antigüedad

1. `receivables` será propietario de un calendario operativo de cobro, separado de los importes y
   términos comerciales autoritativos de `QuotationVersion`.
2. P10 no añadirá a `QuotationVersion` un esquema contractual de cuotas ni reinterpretará notas o
   campos libres como condiciones de pago.
3. Una obligación podrá tener cero o más vencimientos en su revisión vigente. Cada vencimiento
   conservará importe positivo, fecha local, procedencia, revisión, razón, actor y timestamp.
4. El total configurado no podrá exceder la obligación ajustada. La diferencia permanecerá
   explícitamente `sin vencimiento configurado`.
5. Una obligación sin vencimientos sigue debiéndose, pero no está vencida y queda fuera de la mora
   hasta que exista una fecha autoritativa.
6. No se inferirá vencimiento desde fecha del evento, aceptación, confirmación o emisión documental.
7. Revisar el calendario crea otra versión append-only. No modifica fechas históricas ni se presenta
   como cambio contractual automático. Una futura fuente comercial estructurada podrá materializarse
   registrando esa procedencia.
8. Una aplicación dirigida a un vencimiento lo reduce directamente. Para proyectar antigüedad, una
   aplicación solo dirigida a la obligación se atribuirá de forma determinista a vencimientos
   abiertos por `(fecha, id)` y luego al importe sin vencimiento; esa atribución es una proyección
   operacional, no una modificación contractual.
9. La antigüedad usará la fecha local derivada de la zona organizacional, conservará los días exactos
   y mostrará estos buckets iniciales:
   - vigente / no vencido;
   - 1–30 días;
   - 31–60 días;
   - 61–90 días;
   - más de 90 días;
   - sin vencimiento configurado.
10. Los buckets son fijos para P10. Su parametrización queda diferida hasta existir una necesidad
    real.

### 9. Pago, aplicación y sobrepago

1. `ReceivedPayment` registrará como mínimo organización, contraparte, solicitud/raíz cuando
   corresponda, importe, moneda, fecha reportada, método, referencia, observación, procedencia, actor,
   evidencia e idempotencia.
2. Registrar un pago solo afirma recepción externa. Claridez no custodia ni procesa fondos.
3. `PaymentApplication` será un hecho distinto. Un pago podrá aplicarse completa o parcialmente,
   tener varias aplicaciones o conservar importe sin aplicar.
4. Una aplicación no podrá exceder el dinero disponible del pago, el saldo de la obligación ni el
   saldo atribuible al vencimiento cuando lo identifica.
5. Un pago superior al saldo es válido como hecho recibido. El excedente permanece `unapplied`,
   visible y pendiente de decisión. No desaparece, crea crédito, cruza a otro evento, genera
   devolución ni reduce otra deuda automáticamente.

### 10. Ajustes, reversos y devoluciones

1. Un ajuste será exclusivamente una corrección del dominio de cuentas por cobrar. Exigirá dirección
   explícita, importe positivo, razón, actor, timestamp, idempotency key, obligación y
   evidencia/correlación.
2. No se usarán ajustes para costos, gastos, impuestos, asientos contables ni funcionalidades P11.
3. Pago, aplicación, ajuste y devolución consumados se corregirán mediante un reverso completo. El
   reverso conservará objetivo, importe y efecto exactos, razón, actor, tiempo e idempotencia.
4. Una unicidad por objetivo impedirá doble reverso completo. Los reversos concurrentes se
   serializarán. P10 inicial no admite reversos parciales.
5. Un pago no podrá revertirse mientras conserve aplicaciones o devoluciones activas; esos efectos
   deberán contramoverse antes o en la misma transacción.
6. `RefundRecord` significa que el salón declaró haber devuelto dinero externamente. Conservará pago
   u origen, importe, moneda, fecha, método/referencia, razón, actor, evidencia e idempotencia.
7. Una devolución con efecto en el ledger deberá vincular un pago y, cuando reabra saldo, las
   aplicaciones exactas afectadas. No podrá superar el importe económicamente disponible.
8. Una declaración sin origen suficiente podrá conservarse como evidencia pendiente de revisión,
   pero no alterará saldo ni se convertirá en `RefundRecord` canónico hasta poder validar su efecto.
9. Claridez no ejecuta el reembolso bancario. Una cancelación no crea una devolución.

### 11. Cancelación y reprogramación

1. Una cancelación de scheduling conserva obligación, pagos, aplicaciones, ajustes, reversos,
   devoluciones y recibos. Añade contexto derivado de revisión financiera, sin mutar saldo.
2. No produce automáticamente penalidad, devolución, pérdida de anticipo, crédito, ajuste ni
   extinción de deuda. Cualquier efecto exige un hecho financiero explícito y política aprobada.
3. La obligación pertenece a la raíz. Una reserva sucesora no crea obligación, pago ni aplicación.
4. P10 obtendrá la reserva vigente y la cadena mediante `scheduling.public`.
5. Una futura variación comercial exigirá un hecho autoritativo de `commercial`. P10 no deducirá un
   importe nuevo de la reprogramación ni consultará catálogo vigente.

### 12. Migración de constancias 5.1

1. Una confirmación histórica coherente con `confirmation_kind = external_deposit` se migrará a un
   `ReceivedPayment` canónico con esta semántica exacta:

   > pago recibido externamente declarado por un usuario interno de la organización

2. No se presentará como pago procesado por Claridez, verificación bancaria, conciliación ni prueba
   independiente de transferencia.
3. El pago conservará importe, fecha reportada, referencia, actor disponible, raíz y
   `confirmation_source`. Tendrá procedencia `legacy_5_1_confirmation`, evidencia `internal_report`
   y método explícito equivalente a `legacy_unspecified` cuando 5.1 no lo registró.
4. Existirá exactamente un pago migrado por `(organization_id, confirmation_source_id)`, aunque la
   raíz contenga varias sucesoras. Identificadores y claves de backfill serán deterministas.
5. Ese pago se aplicará a la obligación creada para la raíz. Un waiver creará obligación, pero no
   pago.
6. Una raíz confirmada con evidencia de depósito incompleta o incoherente conservará su obligación
   si el snapshot económico es autoritativo, pero no fabricará un pago. La fuente y la razón quedarán
   en un registro explícito de revisión/no conversión.
7. Si falta o diverge la fuente necesaria para crear la obligación, el preflight abortará el
   backfill y exigirá corrección deliberada antes de activar el guardián.
8. No se usarán fechas de evento, aceptación, confirmación o documento como vencimientos históricos.
   Las obligaciones históricas nacerán sin vencimiento configurado.
9. Los campos originales de `commercial_reservation` permanecerán como evidencia histórica. No se
   adoptará esa tabla como ledger P10.

### 13. Recibos y estado de cuenta

1. `receivables` será autoridad del recibo lógico de cobro. Cada recibo congelará pago, aplicaciones
   existentes al emitir, organización, contraparte, obligación/evento, importes, moneda, fecha y
   referencia.
2. El recibo no crea pago, no modifica saldo y no se reescribe por movimientos posteriores. Una
   corrección posterior aparecerá en el estado de cuenta y, si corresponde, en un hecho de anulación
   de recibo, sin alterar el original.
3. La numeración será visible y única por `(organization_id, año, secuencia)`, asignada bajo lock e
   independiente de cualquier numeración fiscal.
4. Toda representación mostrará «recibo/comprobante de cobro de Claridez — no factura». No se
   presentará como factura, documento tributario ni facturación electrónica.
5. El estado de cuenta será una proyección reconstruible de obligación, calendario, pagos,
   aplicaciones, ajustes, reversos, devoluciones y recibos relevantes. Debe explicar matemáticamente
   el saldo y no depender de una segunda tabla mutable.

### 14. Integración con documents

1. `receivables` conservará la semántica financiera; `documents` conservará el ciclo técnico de
   archivos y artefactos.
2. P10 reutilizará mediante puertos estrechos almacenamiento privado, object keys opacas, SHA-256,
   cuarentena, validación, malware, renderer y jobs de ADR 0018.
3. Los modelos actuales `ExternalFile` y `GeneratedArtifact` están ligados a expedientes y versiones
   contractuales. P10 no creará un `ContractualRecord` ficticio para un comprobante financiero ni
   hará nullable esa semántica para mezclar dominios.
4. `documents` podrá incorporar una abstracción interna, tipada y estrecha para archivo privado o
   artefacto generado cuyo propietario semántico sea un dominio autorizado. Esa abstracción
   conservará tenant, propósito, referencia opaca de dominio, hash, estados y guardianes, sin
   importar ORM de `receivables`.
5. `receivables` solicitará almacenamiento de evidencia o render con DTO inmutable. `documents`
   devolverá identidad y estado técnico; no interpretará pagos ni saldos.
6. La autorización para evidencia financiera parte de una capability P10 y propósito financiero.
   No concede capabilities contractuales P9 a Finanzas ni reutiliza `document_artifact:download`
   como sustituto de autorización P10.
7. El recibo lógico seguirá siendo válido si su artefacto está pendiente o falla. El PDF no es
   autoridad financiera.
8. Esta extensión reutiliza la plataforma privada y el protocolo de ADR 0018; no lo contradice ni
   requiere otro ADR. Si la implementación demostrara que necesita cambiar su decisión central,
   deberá detenerse antes de modificar ADR 0018.

### 15. Capabilities y autorización

Se aceptan estas capabilities atómicas:

- `receivables:read`
- `receivables:read_summary`
- `receivables:manage_schedule`
- `receivables:record_payment`
- `receivables:apply_payment`
- `receivables:record_adjustment`
- `receivables:reverse_movement`
- `receivables:record_refund`
- `receivables:issue_receipt`

La matriz será:

| Capability                      | `propietario` | `administrador` | `finanzas` | `comercial` | `operaciones` |
| ------------------------------- | :-----------: | :-------------: | :--------: | :---------: | :-----------: |
| `receivables:read`              |      Sí       |       Sí        |     Sí     |     No      |      No       |
| `receivables:read_summary`      |      Sí       |       Sí        |     Sí     |     Sí      |      No       |
| `receivables:manage_schedule`   |      Sí       |       Sí        |     Sí     |     No      |      No       |
| `receivables:record_payment`    |      Sí       |       Sí        |     Sí     |     No      |      No       |
| `receivables:apply_payment`     |      Sí       |       Sí        |     Sí     |     No      |      No       |
| `receivables:record_adjustment` |      Sí       |       Sí        |     Sí     |     No      |      No       |
| `receivables:reverse_movement`  |      Sí       |       Sí        |     Sí     |     No      |      No       |
| `receivables:record_refund`     |      Sí       |       Sí        |     Sí     |     No      |      No       |
| `receivables:issue_receipt`     |      Sí       |       Sí        |     Sí     |     No      |      No       |

Finanzas recibe todas las capabilities P10, incluidas ajustes, reversos y devoluciones, sin obtener
por ello capabilities P11 o documentales. Comercial solo lee un resumen de total, recibido/aplicado,
saldo y estado derivado dentro de relaciones comerciales reales. Operaciones no obtiene superficie
P10. No se crean asignaciones de usuario nuevas ni se condiciona P10 a MFA futuro.

Toda operación exigirá conjuntamente:

```text
sesión válida
+ CSRF para escrituras HTTP
+ organización y membresía activas
+ authorized_tenant_scope
+ capability P10 requerida
+ relación de dominio real
+ propósito permitido cuando aplique
```

Capabilities `sales:*`, `operation:*` o documentales nunca sustituyen una capability P10. Una
relación limita alcance; no concede autoridad financiera.

### 16. RLS, inmutabilidad y privilegios

1. Toda tabla privada P10 incluirá `organization_id`, claves y unicidades tenant-aware, guardianes
   de tenant y RLS simétrica con `ENABLE` y `FORCE ROW LEVEL SECURITY`.
2. Las validaciones, escrituras, consultas y materialización de respuesta completarán dentro de
   `authorized_tenant_scope`.
3. Obligación original, pagos, aplicaciones, ajustes, reversos, devoluciones, revisiones/vencimientos
   publicados, recibos y evidencia migratoria serán inmutables o append-only.
4. Los movimientos consumados resistirán `.save()`, `QuerySet.update`, `bulk_update`, `.delete()`,
   `QuerySet.delete` y SQL directo con `claridez_app`.
5. `claridez_app` no tendrá `DELETE`, `TRUNCATE` ni capacidad para actualizar hechos financieros.
   Solo encabezados configurables o máquinas técnicas explícitas recibirán el DML mínimo y sus
   transiciones estarán protegidas por PostgreSQL.
6. Constraints, triggers y guardianes serán la defensa final de invariantes monetarias, relaciones
   tenant-aware y append-only; las comprobaciones de Django no serán la única defensa.

### 17. Concurrencia y orden de locks

1. El protocolo global conservará primero los advisory locks de espacio de P8, ordenados por UUID.
   Después bloqueará, cuando correspondan:

   ```text
   espacios de scheduling
     → raíz/reserva
     → obligaciones, ordenadas por UUID de raíz
     → pagos, ordenados por UUID
     → revisiones/vencimientos, ordenados por fecha e ID
     → movimientos objetivo, ordenados por tipo e ID
   ```

2. Una operación que no necesite niveles anteriores comenzará en el primer nivel aplicable, pero no
   invertirá el orden si después requiere otro agregado.
3. El lock de raíz y la unicidad protegerán la creación única de obligación. Aplicaciones bloquearán
   las obligaciones y pagos implicados antes de recalcular disponibles.
4. Ajustes que reduzcan obligación no podrán dejar saldo menor que lo aplicado. Revisar vencimientos
   no podrá dejar un vencimiento por debajo de su aplicación neta salvo que los contramovimientos
   necesarios ocurran en la misma transacción.
5. Reversos bloquearán su movimiento objetivo; devoluciones bloquearán pago, aplicaciones y
   obligaciones afectadas según el orden global.
6. Dos aplicaciones concurrentes no podrán exceder pago, obligación o vencimiento. Dos reversos no
   podrán revertir dos veces un movimiento. Dos devoluciones no podrán exceder el disponible.
7. Las decisiones se comprobarán otra vez bajo lock y mediante constraints/guardianes. No se confiará
   únicamente en `SELECT → comprobar → INSERT` desde la aplicación.

### 18. Idempotencia y posibles duplicados

1. Registrar pago, aplicar, ajustar, reversar, registrar devolución, emitir recibo persistente y el
   flujo coordinado de confirmación requerirán una clave de idempotencia.
2. Un registro de comandos conservará:

   ```text
   organization_id
   + command_type
   + idempotency_key
   + payload_hash
   + result_reference
   ```

3. La misma clave y payload canónico devolverán el resultado ya creado. La misma clave con payload
   distinto devolverá `409 idempotency_conflict`.
4. El endpoint existente de confirmación mantendrá su ruta y payload funcional. El adaptador podrá
   derivar durante el cutover una clave determinista para clientes 5.1/P8 que no envíen una, pero el
   coordinador siempre operará con clave y hash del payload completo. El frontend P10 enviará una
   clave explícita.
5. La idempotencia no sustituye locks, constraints ni guardianes.
6. Dos pagos manuales idénticos con claves distintas no pueden deduplicarse infaliblemente. Si un
   método garantiza una referencia externa única, podrá imponerse unicidad contextual por
   organización, método y referencia normalizada.
7. Cuando esa garantía no exista, el sistema advertirá un posible duplicado y conservará una
   decisión humana auditable; no rechazará automáticamente pagos legítimos.

### 19. API y frontend

1. P10 expondrá bajo `/api/v1` consultas de cartera, obligación, calendario, movimientos, pagos,
   aplicaciones, estado de cuenta y antigüedad.
2. Las escrituras serán comandos explícitos para registrar pago, aplicar, crear/revisar calendario,
   ajustar, reversar, registrar devolución y emitir recibo.
3. No habrá `DELETE` de movimientos ni `PATCH` libre sobre hechos monetarios consumados.
4. Propietario, administrador y Finanzas podrán operar cartera, calendario, pagos, aplicaciones,
   excedentes, ajustes, reversos, devoluciones, recibos, estados de cuenta y antigüedad.
5. Comercial verá únicamente el resumen autorizado. Operaciones no tendrá superficie P10.
6. El frontend mostrará claramente importes sin aplicar, obligaciones sin vencimiento y contextos de
   revisión, sin resolver automáticamente decisiones abiertas.

### 20. Migración y activación

P10 deberá probar tres escenarios: instalación desde cero, migración desde P9 final y migración de
constancias 5.1. El orden obligatorio será:

1. crear estructuras P10 y privilegios iniciales;
2. ejecutar preflight de raíces, confirmaciones, cotizaciones y evidencia 5.1;
3. crear una obligación determinista por raíz históricamente confirmada;
4. migrar pagos 5.1 válidos, aplicar cada uno una sola vez y registrar no conversiones;
5. verificar cardinalidades, snapshots, monedas, importes y procedencia;
6. activar unicidades, guardianes diferidos, RLS final y privilegios mínimos;
7. ejecutar verificadores postmigración y abortar/revertir el cutover si divergen.

No se activará un guardián que impida su propio backfill. No se inventarán vencimientos históricos.
Una obligación histórica sin fecha quedará `sin vencimiento configurado`. El ensayo local no implica
cutover, staging, producción ni despliegue.

### 21. Límites con P11 y servicios financieros externos

P10 no incluye costos, gastos, cuentas por pagar, movimientos generales de caja, presupuestos,
rentabilidad, cierres, libro mayor, impuestos, nómina, facturación electrónica, conciliación bancaria
automática, custodia de fondos, pasarela ni cobro de suscripciones de Claridez. Tampoco ejecuta
reembolsos ni conversión de moneda.

## Aspectos provisionales

- Los nombres físicos de obligación, revisión de calendario, vencimiento, pago, aplicación, ajuste,
  reverso, devolución, recibo, comando y revisión migratoria podrán ajustarse durante la
  implementación si conservan las identidades y responsabilidades aceptadas.
- El nombre físico del coordinador neutral de aplicación podrá ajustarse. No podrá convertirse en un
  dominio con datos propios ni introducir dependencias circulares.
- La abstracción técnica exacta que extienda archivos/artefactos de `documents` se cerrará con el
  código de P9, sin cambiar su autoridad ni fabricar expedientes contractuales.

## Asuntos expresamente abiertos y diferidos

- Penalidades por cancelación y pérdida de anticipos.
- Obligación jurídica de devolver dinero.
- Créditos a favor y aplicación de sobrepagos a otros eventos.
- Consecuencias contractuales de revisar un vencimiento operativo.
- Retención jurídica definitiva de comprobantes y recibos.
- Facturación electrónica y cualquier numeración fiscal.
- Conciliación bancaria automática.
- Ejecución real de reembolsos.
- Conversión de moneda.

Estos asuntos no bloquean la arquitectura base porque P10 falla cerradamente: no automatiza su
efecto mientras no exista una política aprobada.

## Validación exigida para la implementación

La implementación P10 deberá demostrar, como mínimo:

- una obligación exacta por raíz confirmada y ninguna por raíces nunca confirmadas;
- atomicidad completa del flujo de confirmación con anticipo y waiver;
- ausencia de import de `receivables` desde scheduling y de ORM compartido entre dominios;
- snapshots exactos de cotización sin consulta a catálogo vigente;
- migración determinista 5.1, un pago por fuente y no conversión explícita de evidencia incoherente;
- ecuaciones monetarias, redondeo, monedas, aplicaciones parciales y sobrepago sin pérdida;
- buckets y días exactos, incluidas obligaciones sin vencimiento;
- ajustes, reversos completos y devoluciones bajo carreras y retries;
- recibos únicos por organización/año y estados de cuenta reconstruibles;
- autorización conjuntiva y matriz completa de los cinco perfiles;
- dos organizaciones, RLS, ORM, bulk, SQL directo y privilegios de `claridez_app`;
- migraciones desde cero y desde P9 final, preflight, guardianes y recuperación;
- OpenAPI, API, frontend responsive/accesible y gates oficiales aplicables.

La aceptación de este ADR no afirma que P10 esté implementada ni autoriza por sí sola staging,
producción, despliegue o cutover.

## Alternativas consideradas

- **Crear `claridez.finance`:** rechazada porque anticiparía P11 y mezclaría cuentas por cobrar con
  costos, gastos, flujo y rentabilidad.
- **Crear la obligación al aceptar cotización:** rechazada porque la provisional todavía puede
  expirar sin confirmarse.
- **Crear la obligación al emitir o aceptar contrato:** rechazada porque trasladaría autoridad
  económica a P9 y dejaría reservas confirmadas sin documento fuera de la verdad financiera.
- **Crear obligación por cada sucesora:** rechazada porque una reprogramación no es otra venta.
- **Hacer que scheduling importe receivables:** rechazada por dependencia circular y por ampliar la
  autoridad de agenda.
- **Tratar pago y aplicación como una fila:** rechazada porque impediría pagos parciales, múltiples
  obligaciones e importes sin aplicar.
- **Mantener saldo o estado mutable:** rechazada porque podría divergir del ledger.
- **Usar montos negativos para correcciones:** rechazado; el tipo de movimiento expresa la dirección.
- **Aplicar o devolver automáticamente un sobrepago:** rechazado hasta aprobar una política de crédito.
- **Usar fecha del evento como vencimiento:** rechazado por fabricar una condición no existente.
- **Guardar comprobantes en expedientes contractuales ficticios:** rechazado porque mezclaría
  autoridad financiera y documental.
- **Crear un segundo ADR para archivos financieros:** no seleccionado porque ADR 0018 ya define la
  plataforma privada sustituible y P10 solo requiere un consumidor tipado adicional.

## Consecuencias

- Claridez obtiene una autoridad financiera acotada y separada de P11.
- La confirmación gana coordinación y guardianes adicionales, pero conserva una sola transacción y
  la autoridad de scheduling sobre agenda.
- El ledger append-only y las proyecciones derivadas aumentan el número de hechos, a cambio de poder
  explicar y reconstruir cada saldo.
- Las obligaciones sin vencimiento son visibles pero no se presentan falsamente como morosas.
- Un excedente recibido permanece explícito y exige decisión posterior.
- Finanzas obtiene las capacidades propias de P10 sin acceso documental contractual ni privilegios
  financieros futuros por inferencia.
- La plataforma de P9 se reutiliza sin convertir PDFs o archivos en autoridad monetaria.
- La migración 5.1 conserva el nivel real de evidencia y evita duplicar pagos por reprogramación.

## Evidencia

- [Blueprint maestro](../product/PRODUCT_BLUEPRINT.md)
- [Roadmap de entrega](../product/PRODUCT_DELIVERY_ROADMAP.md)
- [Handoff vigente](../PROJECT_HANDOFF.md)
- [Especificación aprobada de 5.1](../product/ITERATION_5_1_COMMERCIAL_FLOW.md)
- [Especificación aprobada de P8](../product/P8_SCHEDULING_AND_ADVANCED_RESERVATIONS_SPECIFICATION.md)
- [ADR 0009 — Aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)
- [ADR 0012 — Integridad comercial](0012-commercial-scheduling-and-monetary-integrity.md)
- [ADR 0013 — Coordinación comercial-operaciones](0013-commercial-operations-coordination-and-integrity.md)
- [ADR 0016 — Propiedad de scheduling](0016-scheduling-ownership-and-temporal-integrity.md)
- [ADR 0017 — Dominio contractual](0017-contractual-domain-and-documentary-evidence.md)
- [ADR 0018 — Plataforma de archivos y procesamiento documental](0018-file-platform-and-document-processing.md)
