# ADR 0021 — Autoridad de resources, abastecimiento e integridad de inventario P12

- **Estado:** Aceptado
- **Fecha:** 2026-08-23
- **Reemplaza a:** No aplica; amplía ADR 0016 exclusivamente para las consecuencias de scheduling
  sobre recursos y amplía ADR 0020 para la procedencia financiera P12; no modifica ADR 0015
- **Reemplazado por:** No aplica

## Contexto

P11 cerró la autoridad financiera operativa sin incorporar proveedores, compras, recursos ni
inventario. P12 debe permitir saber qué contraparte suministra un servicio o bien, qué recursos
existen, dónde están, qué cantidad está disponible y qué se asignó a un evento, sin convertir
Claridez en marketplace, sistema logístico avanzado ni contabilidad formal de inventario.

El dominio debe distinguir compromisos de compra, recepción física, existencias, capacidad
temporal y hechos monetarios. También debe coordinarse con la raíz y reserva vigente de scheduling:
una cancelación, expiración o reprogramación no puede dejar una reserva P12 obsoleta consumiendo
capacidad. Esa integridad debe sobrevivir ORM bulk y SQL directo, no depender de una reparación
posterior de Django.

P12 introduce además una nueva procedencia para costos y gastos P11. Finance debe conservar la
única verdad de costo real, gasto y caja, aunque una línea de recepción P12 sea su procedencia
atómica y exista una FK física tenant-aware desde Finance.

El propietario aprobó el plan consolidado y la formalización de este ADR. Su aceptación fija la
arquitectura, pero no autoriza todavía modelos, migraciones, capabilities ejecutables, servicios,
endpoints, frontend ni otra implementación de P12.

## Decisiones aceptadas

### 1. Autoridad modular y fronteras

1. Se crea conceptualmente `claridez.resources` como propietario de proveedores, contactos de
   proveedor, ofertas suministradas, recursos, unidades operativas, ubicaciones internas por sede,
   existencias, compras, recepciones, movimientos, reservas/asignaciones de recursos,
   mantenimiento, indisponibilidad y faltantes.
2. `claridez.catalog` conserva tipos, servicios, productos, paquetes, precios y condiciones
   comerciales vendibles. Una relación opcional con P12 no convierte un ítem de catálogo en
   existencia física ni permite usar `catalog.unit_label` como unidad operativa.
3. `claridez.organizations` conserva organizaciones, membresías, sedes y autorización. Una
   ubicación P12 pertenece a una sede de la misma organización mediante relación tenant-aware; no
   redefine la identidad ni el estado de la sede.
4. `claridez.scheduling` conserva raíz, reserva vigente, intervalo del evento, montaje, desmontaje,
   buffers, ocupación del espacio e historia temporal. P12 consume su puerto público y no importa
   modelos ORM de scheduling.
5. `claridez.operations` conserva preparación, checklist, responsables, ejecución y transiciones.
   Consume asignaciones, faltantes y estados mediante `resources.public`; no escribe tablas P12 ni
   se convierte en propietario de inventario.
6. `claridez.finance` conserva autoridad exclusiva sobre costo real, gasto, asignación financiera,
   caja, periodos, cierres y correcciones monetarias. P12 no crea una segunda verdad monetaria.
7. Los coordinadores transaccionales intermodulares dependerán de puertos públicos estrechos.
   Importar una entidad o tabla ajena no concede autoridad sobre ella.

### 2. Proveedor, identidad y contactos

1. `Supplier` representa una contraparte de la organización, no una `Person`. Su identidad primaria
   es un UUID tenant-aware e inmutable.
2. Cuando exista identificador fiscal, se normaliza y es único dentro de la organización. Cuando no
   exista, se usa un código interno inmutable. Coincidir solo por nombre no fusiona ni deduplica
   proveedores automáticamente.
3. El perfil del proveedor conserva nombre, estado y los datos operativos mínimos. Términos y
   ofertas suministradas se versionan o conservan con vigencia cuando cambian; no reescriben
   compras, recepciones, asignaciones ni hechos históricos.
4. `SupplierContact` enlaza una `Person` canónica existente, con función y vigencia propias. La
   contraparte y su contacto siguen siendo identidades distintas.
5. P12 no amplía la autoridad de people. Propietario, administrador y comercial conservan
   `person:manage` conforme a ADR 0015. Operaciones y Finanzas solo pueden vincular una `Person`
   existente; crearla o modificarla exige la autoridad P7 vigente. Una ampliación futura requerirá
   otro ADR que modifique ADR 0015.
6. Inactivar un proveedor, contacto, oferta o recurso impide nuevas relaciones operativas según su
   tipo, pero conserva compras, recepciones, movimientos, asignaciones, vínculos financieros e
   historia. No existe borrado funcional de hechos consumados.

### 3. Naturalezas de recurso

1. Todo recurso tiene exactamente una de estas naturalezas:

   - `supplied_service`: capacidad externa medida por cantidad o duración, sin existencia física;
   - `consumable`: cantidad almacenada cuya salida consume existencia;
   - `reusable_pool`: unidades fungibles reutilizables que salen y regresan a capacidad;
   - `serialized_asset`: equipo individual con identidad, estado, ubicación y trazabilidad propios.

2. La naturaleza es inmutable después del primer hecho relevante. Cambiarla exige crear otra
   definición y desactivar la anterior, sin reinterpretar historia.
3. Una oferta de proveedor describe qué puede suministrar una contraparte; no es por sí sola
   inventario, capacidad confirmada, compra, recepción, costo ni gasto.

### 4. Unidades y compatibilidad

1. Las dimensiones canónicas son conteo, masa, volumen, longitud y duración. Inventario físico usa
   conteo, masa, volumen o longitud. Un servicio suministrado puede usar conteo o duración.
2. La capacidad simultánea de un servicio se registra separadamente de la cantidad o duración
   recibida. Una hora de servicio cumplida no representa por sí sola una unidad simultánea
   disponible.
3. Cada recurso declara una dimensión y unidad base canónica. Solo se admiten conversiones mediante
   factores exactos y versionados entre unidades de la misma dimensión; se rechazan conversiones
   entre dimensiones.
4. Dimensión y unidad base quedan inmutables después del primer movimiento, recepción, reserva,
   unidad serializada o cumplimiento relevante.
5. Cantidades y factores usan `Decimal`/`numeric`, nunca `float`. La precisión y escala exactas de
   cantidades se fijarán durante implementación sin reducir estas invariantes.
6. `catalog.unit_label` continúa siendo texto descriptivo de una línea vendible y no participa en
   conversiones, balances ni disponibilidad P12.

### 5. Existencias, ubicaciones y ledger de movimientos

1. Una ubicación P12 es un punto operativo interno de almacenamiento o custodia perteneciente a
   una sede. El saldo se determina por organización, recurso y ubicación en unidad base.
2. `StockMovement` es la autoridad append-only de cantidad física. Una proyección de saldo puede
   mantener el estado vigente para locks y consultas, pero un guardián diferido debe comprobar su
   equivalencia con el ledger; no constituye una segunda historia.
3. Los movimientos cumplen estas invariantes:

   - una entrada suma;
   - una salida resta y no puede dejar saldo negativo;
   - un ajuste exige cantidad positiva, dirección y razón tipada;
   - un traslado contiene dos piernas confirmadas en la misma transacción, salida de origen y
     entrada en destino, con igual recurso y cantidad en unidad base;
   - una devolución es un hecho nuevo y nunca resucita silenciosamente una reserva cerrada;
   - toda corrección es compensatoria, enlaza el hecho corregido y conserva el original.

4. Movimientos confirmados, piernas de traslado y correcciones no admiten `UPDATE` ni `DELETE`. Una
   escritura incompleta, una pierna huérfana o una cantidad desigual falla al commit.
5. P12 registra cantidades y estado operativo; no incorpora FIFO, LIFO, costo promedio, valoración
   contable, depreciación, libro mayor ni asientos.

### 6. Recepción física e inventario

1. `Purchase` y `PurchaseLine` expresan compromisos operativos. `SupplyReceipt` y
   `SupplyReceiptLine` registran la recepción o cumplimiento observado; una recepción confirmada es
   inmutable.
2. Una `SupplyReceiptLine` confirmada con tipo `goods_received` para un recurso inventariable debe
   originar exactamente una entrada `StockMovement` en la misma transacción. Movimiento y línea
   deben coincidir en organización, recurso, cantidad convertida a unidad base y ubicación destino.
3. La entrada conserva `provenance=resources_receipt_line` y una referencia tenant-aware a la línea.
   Una unicidad compuesta impide una segunda entrada para la misma línea. Guardianes diferidos sobre
   recepción y movimiento exigen al commit la correspondencia uno-a-uno y rechazan una recepción
   física sin su entrada, una entrada duplicada o una entrada con datos divergentes.
4. Una línea `service_fulfilled` no genera `StockMovement`. Su cantidad o duración cumplida queda
   como hecho operativo y puede ser procedencia financiera conforme a la sección 11.
5. Para `serialized_asset`, la unidad base es conteo y la cantidad recibida debe ser entera. La
   misma transacción materializa exactamente ese número de unidades individuales, todas enlazadas a
   la línea, con identidades únicas dentro de la organización. El guardián diferido comprueba que el
   conteo de unidades, la entrada física y la cantidad base coincidan.
6. Confirmar recepción, crear la entrada y materializar unidades serializadas usa una sola clave
   idempotente. Repetir clave y payload devuelve el resultado existente; cambiar el payload falla.
7. Una corrección posterior crea recepción o movimiento compensatorio enlazado, según el hecho que
   corrija. Nunca actualiza o elimina la línea confirmada, la entrada ni las unidades históricas.

### 7. Reservas, disponibilidad y cuatro invariantes concurrentes

1. Una reserva/asignación P12 conserva `root_reservation_id` y `current_reservation_id`. Mientras
   derive de scheduling usa exclusivamente su intervalo público canónico `[starts_at, ends_at)`.
   No lee ni copia el `occupied_interval` interno del espacio.
2. Solo una asignación P12 en estado bloqueante y enlazada a una reserva scheduling provisional no
   expirada o confirmada reduce disponibilidad. Un requerimiento no asignado o faltante no inventa
   capacidad.
3. La disponibilidad se protege separadamente:

   - **Consumible:** `available_to_promise = on_hand - reserved_unissued`. Una reserva activa reduce
     esa disponibilidad; la salida enlazada reduce en la misma transacción existencia y reserva
     pendiente. Cancelar, expirar o reprogramar antes de la salida libera la reserva. Después de la
     salida solo una devolución explícita repone existencia.
   - **Pool reutilizable:** reservas, custodias e indisponibilidades solapadas no superan la cantidad
     operativa. La entrega convierte la reserva en custodia sin descontar dos veces. La devolución
     cierra custodia y restaura capacidad salvo mantenimiento o indisponibilidad vigente.
   - **Activo serializado:** una exclusión GiST impide reservas, custodias e indisponibilidades
     solapadas para la misma unidad. Entrega convierte la reserva en custodia; devolución la cierra.
   - **Servicio suministrado:** las reservas solapadas no superan la capacidad configurada durante
     `[starts_at, ends_at)`. Cumplir el servicio no genera movimiento físico; cancelación,
     expiración o reprogramación liberan el intervalo anterior. Sin capacidad declarada se registra
     faltante o requerimiento pendiente, no disponibilidad supuesta.

4. Advisory locks transaccionales y locks de filas se toman por organización y recurso/ubicación en
   orden total de UUID. Las restricciones simples usan constraints; capacidad agregada usa
   proyección, locks y guardianes diferidos; activos serializados usan además exclusión GiST.
5. Una carrera nunca puede confirmar dos consumos del mismo saldo, exceder un pool o servicio ni
   solapar un activo. El perdedor recibe conflicto y no una asignación parcial.

### 8. Integridad PostgreSQL con scheduling

1. `ResourceCapacityAllocation` será la proyección vigente de capacidad P12. Cada fila conserva
   organización, recurso o unidad serializada, cantidad base, raíz, reserva actual, intervalo
   `[starts_at, ends_at)`, naturaleza, origen de la ocupación, revisión e `is_blocking`. No tendrá
   endpoints de escritura propios ni será una segunda bitácora.
2. Cuando el origen sea una reserva scheduling, un guardián diferido comprobará al commit:

   - misma organización, raíz y reserva vigente;
   - intervalo idéntico a `scheduling.public` —los campos persistidos por scheduling que lo
     respaldan—, no a la ocupación del espacio;
   - estado scheduling provisional no expirado o confirmado;
   - equivalencia exacta con la asignación y el último hecho P12 aplicable;
   - ausencia de una fila bloqueante para una reserva cancelada, expirada o `rescheduled`.

3. Los triggers se instalan sobre las escrituras relevantes de dominio/proyección de scheduling y
   resources. Por ello se ejecutan también ante `QuerySet.update`, ORM bulk y SQL directo con el rol
   permitido.
4. Cancelación y expiración tienen una consecuencia determinista: una función PostgreSQL toma los
   locks aprobados, agrega idempotentemente el hecho P12 enlazado al `ScheduleEvent` y vuelve no
   bloqueante cada reserva de recurso aún pendiente en la misma transacción. No libera una salida,
   custodia o cumplimiento ya ejecutados.
5. Reprogramación no puede ser inventada por un trigger porque el conjunto a trasladar es una
   decisión explícita. El coordinador debe persistir selección, liberaciones y sucesoras P12; el
   guardián diferido rechaza la transacción de scheduling si cualquier asignación pendiente de la
   predecesora queda sin exactamente una consecuencia o si una seleccionada no coincide con la
   sucesora.
6. En particular, no puede confirmar una transacción donde scheduling ya dejó de estar vigente y
   una proyección P12 de origen scheduling continúe bloqueando capacidad. Una custodia física,
   existencia consumida o mantenimiento puede seguir reduciendo disponibilidad por su propia
   procedencia, nunca como reserva scheduling obsoleta.
7. La proyección y sus hechos no pueden corregirse mediante borrado. Una divergencia observada falla
   cerradamente y se repara con el comando compensatorio aprobado.

### 9. Reprogramación atómica y alcance frente a P13

1. El conjunto P12 seleccionado para traslado participa en la misma coordinación transaccional de
   ADR 0016. El coordinador neutral consume `scheduling.public`, `operations.public` y
   `resources.public`.
2. Bajo el lock de raíz y los locks de espacio de ADR 0016, seguidos por recursos/ubicaciones en
   orden total, la transacción crea la reserva sucesora, aplica las consecuencias operations
   existentes, registra selección y consecuencias resources, sustituye las proyecciones de
   capacidad y agrega los eventos aplicables.
3. Reserva predecesora y sucesora, preparaciones e ítems de Operations, asignaciones P12
   seleccionadas, liberaciones, faltantes y proyecciones confirman o revierten conjuntamente.
4. Solo pueden trasladarse reservas de recursos aún no consumidas, entregadas, puestas en custodia
   ni cumplidas. Una salida, recepción, custodia, devolución o cumplimiento ya ejecutado permanece
   vinculado a la reserva y sede históricas; la sucesora requiere una asignación independiente.
5. Las asignaciones pendientes no seleccionadas se liberan y permanecen trazables como faltante si
   el comando así lo declara. No se trasladan silenciosamente.
6. P12 decide únicamente sobre `[starts_at, ends_at)`. P13 queda para ventanas específicas de
   recursos y coordinación operativa ampliada de montaje/desmontaje. P13 no sustituirá la autoridad
   de scheduling sobre tiempo, ocupación del espacio, setup, teardown, buffers o historial.

### 10. Mantenimiento e indisponibilidad

1. Mantenimiento e indisponibilidad son hechos temporales explícitos con recurso o unidad, sede o
   ubicación cuando aplique, intervalo, razón, actor, estado y correcciones enlazadas.
2. Un activo serializado indisponible no puede reservarse ni entregarse en un intervalo solapado. En
   pools, la cantidad no operativa reduce capacidad; en servicios, la indisponibilidad reduce la
   capacidad declarada. Un consumible puede quedar en cuarentena sin aumentar cantidad disponible.
3. Finalizar o cancelar una indisponibilidad agrega una transición; no reescribe su intervalo
   histórico. Desactivar un recurso impide nuevas reservas, pero no elimina mantenimiento,
   movimientos, custodias o asignaciones previas.

### 11. Procedencia financiera P12

1. Solo una `SupplyReceiptLine` inmutable de una recepción confirmada con tipo `goods_received` o
   `service_fulfilled` puede ser procedencia P12 de un hecho financiero. `Purchase` y
   `PurchaseLine` son compromisos y nunca materializan por sí solos costo o gasto real.
2. Cada línea puede originar cero o exactamente un `ActualDirectCost` o `ExpenseOccurrence`, nunca
   ambos. Cada destino con procedencia P12 refiere exactamente una línea.
3. Finance será propietario de `FinancialSourceReference`, con organización, `source_kind`,
   `source_id` y exactamente uno de `actual_direct_cost_id` o `expense_occurrence_id`.
4. Durante P12 `source_kind` queda cerrado por CheckConstraint a
   `resources_receipt_line`. No se presenta ni implementa como referencia polimórfica genérica
   mientras su FK física apunte específicamente a `SupplyReceiptLine`.
5. Se imponen unicidad `(organization_id, source_kind, source_id)`, unicidad para cada destino,
   check de exactamente un destino y FKs tenant-aware hacia ambos agregados Finance. La FK compuesta
   `(organization_id, source_id)` hacia `SupplyReceiptLine(organization_id, id)` se instala en SQL.
6. `ActualDirectCost.Provenance` añade `resources_receipt`. Un nuevo
   `finance_cost_provenance_ck` permite únicamente:

   - `manual` con `source_evidence IS NULL`;
   - `operations_evidence` con `source_evidence IS NOT NULL`;
   - `resources_receipt` con `source_evidence IS NULL`.

7. `ExpenseOccurrence.Provenance` añade `resources_receipt`; su campo aumenta de longitud 12 a 24.
   `finance_expense_provenance_ck` permite únicamente:

   - `manual` con `recurring_rule IS NULL`;
   - `recurring` con `expense_type=recurring` y `recurring_rule IS NOT NULL`;
   - `resources_receipt` con `expense_type IN (variable, recurring)` y
     `recurring_rule IS NULL`.

8. La categoría debe corresponder a `variable_expense` o `recurring_expense` según
   `expense_type`. Servicio y guardián PostgreSQL protegen esta relación, incluida SQL directa.
9. Guardianes diferidos comprueban que toda procedencia `resources_receipt` tenga exactamente una
   referencia y que ninguna otra procedencia la tenga. La unicidad de fuente, lock de la línea y
   comando Finance idempotente impiden doble materialización bajo carrera.
10. El coordinador neutral bloquea y obtiene la línea elegible mediante `resources.public` y llama
    el comando correspondiente de `finance.public`. Resources no importa Finance; Finance no
    importa modelos ORM ni servicios de Resources.
11. Importe, moneda, categoría, fecha económica, periodo, raíz/sede histórica y asignaciones viven
    bajo autoridad Finance. Términos o importes esperados de compra son evidencia operativa P12 y
    no participan en resultados hasta materializarse en Finance.
12. Un `ActualDirectCost` exige que la línea esté vinculada al evento y que Finance valide raíz y
    sede histórica. Cuando no corresponda costo directo, la clasificación y asignaciones válidas
    pertenecen a `ExpenseOccurrence`; P12 no decide esa clasificación.
13. P12 nunca crea caja automáticamente. Correcciones de costo o gasto usan exclusivamente
    `DirectCostCorrection` o `ExpenseOccurrenceCorrection`; no vuelven a materializar la fuente ni
    modifican recepción o referencia original.

### 12. Dependencia de esquema y orden de migraciones

1. La dependencia intermodular de dominio permanece acíclica aunque exista una dependencia
   unidireccional de esquema `finance → resources`.
2. El orden aprobado es:

   ```text
   scheduling/organizations/catalog/people/operations vigentes
       → resources.0001_initial

   finance.0005 ───────────────────────────────┐
                                               ├→ finance.0006_resources_receipt_provenance
   resources.0001_initial ─────────────────────┘
   ```

3. `resources.0001_initial` no depende de Finance. Crea P12, incluida `SupplyReceiptLine`, sus
   constraints, RLS, proyecciones y guardianes con scheduling.
4. `finance.0006_resources_receipt_provenance` depende de `finance.0005` y
   `resources.0001_initial`. Añade choices, longitud y constraints, crea
   `FinancialSourceReference` e instala la FK tenant-aware hacia la línea.
5. Finance conserva `source_id` como UUID escalar en su estado ORM; no declara `ForeignKey` ORM ni
   importa modelos/services de Resources. La migración SQL y PostgreSQL protegen la relación
   física.
6. Ninguna migración de Resources depende de `finance.0006`; no hay ciclo de migraciones ni una FK
   inversa desde Resources hacia Finance.
7. P12 se instala vacío. No existe fuente histórica canónica para inventar proveedores,
   existencias, recepciones, movimientos o asignaciones mediante backfill.

### 13. Capacidades atómicas

Las capacidades P12 son explícitas y no jerárquicas:

| Capacidad                      | `propietario` | `administrador` | `comercial` | `operaciones` | `finanzas` |
| ------------------------------ | :-----------: | :-------------: | :---------: | :-----------: | :--------: |
| `resource:read_availability`   |      Sí       |       Sí        |     Sí      |      Sí       |     Sí     |
| `supplier:read`                |      Sí       |       Sí        |     No      |      Sí       |     Sí     |
| `supplier:manage_profile`      |      Sí       |       Sí        |     No      |      Sí       |     No     |
| `supplier:link_contact`        |      Sí       |       Sí        |     No      |      Sí       |     Sí     |
| `supplier:manage_terms`        |      Sí       |       Sí        |     No      |      No       |     Sí     |
| `supplier:manage_offering`     |      Sí       |       Sí        |     No      |      Sí       |     No     |
| `resource:read`                |      Sí       |       Sí        |     No      |      Sí       |     Sí     |
| `resource:manage`              |      Sí       |       Sí        |     No      |      Sí       |     No     |
| `resource:reserve`             |      Sí       |       Sí        |     No      |      Sí       |     No     |
| `resource:maintain`            |      Sí       |       Sí        |     No      |      Sí       |     No     |
| `inventory:record_movement`    |      Sí       |       Sí        |     No      |      Sí       |     No     |
| `purchase:read`                |      Sí       |       Sí        |     No      |      Sí       |     Sí     |
| `purchase:manage`              |      Sí       |       Sí        |     No      |      No       |     Sí     |
| `purchase:receive`             |      Sí       |       Sí        |     No      |      Sí       |     No     |
| `purchase:materialize_finance` |      Sí       |       Sí        |     No      |      No       |     Sí     |

Materializar `ActualDirectCost` exige conjuntamente `purchase:materialize_finance` y
`finance:record_actuals`. Materializar `ExpenseOccurrence` exige conjuntamente
`purchase:materialize_finance` y `finance:allocate_expenses`. Ninguna capacidad implica otra; la
interfaz no sustituye autorización backend.

### 14. Tenancy, locks, idempotencia y correcciones

1. Toda tabla privada P12 incluye `organization_id`, claves y unicidades compuestas tenant-aware,
   `ENABLE` + `FORCE RLS` y privilegios mínimos. Toda validación, consulta, escritura y respuesta se
   materializa dentro de `authorized_tenant_scope`.
2. `claridez_app` no recibe `DELETE` ni `TRUNCATE` sobre tablas P12. Las proyecciones vigentes solo
   admiten la actualización controlada necesaria, protegida por guardianes; ledgers y hechos
   consumados son append-only.
3. Los comandos mutantes usan organización, tipo de comando, UUID de idempotencia y hash canónico
   del payload. Misma clave y payload devuelve el resultado; misma clave con payload distinto
   falla.
4. El orden de locks intermodular conserva primero los locks de raíz/espacio aprobados por ADR 0016,
   después recursos, unidades serializadas y ubicaciones en orden total de UUID. La materialización
   financiera usa después sus locks Finance propios; no introduce un lock global de raíz en P11.
5. Guardianes diferidos protegen equivalencia de ledger/saldo, dos piernas de traslado, recepción y
   entrada, serialización, disponibilidad agregada, proyección scheduling y procedencia financiera.
   Las invariantes se prueban también con ORM bulk y SQL directo usando el rol de aplicación.
6. Correcciones siempre enlazan un hecho exacto y son compensatorias. Activación/inactivación,
   corrección o reprogramación no borran ni reescriben historia.

### 15. Relación expresa con ADR previos

1. Este ADR amplía ADR 0016 exclusivamente para las consecuencias de cancelación, expiración y
   reprogramación de scheduling sobre reservas y capacidad P12. No sustituye ni modifica su
   autoridad temporal, intervalo y ocupación del espacio, montaje, desmontaje, buffers, cadena de
   reservas o historial canónico.
2. Este ADR amplía ADR 0020 para añadir la procedencia financiera `resources_receipt`, la referencia
   física cerrada y su coordinación. Finance sigue siendo la única autoridad de costo real, gasto y
   caja.
3. Este ADR no modifica ADR 0015 ni concede nuevas escrituras sobre `Person`.

## Aspectos provisionales

- Los nombres físicos de tablas, índices, triggers y funciones P12 distintos de los contratos
  expresamente nombrados podrán ajustarse durante implementación si conservan exactamente sus
  propietarios e invariantes.
- La precisión y escala de cantidades físicas se fijarán tras validar los rangos necesarios para
  conteo, masa, volumen, longitud y duración; deben usar `Decimal`/`numeric` y conversiones exactas.
- La primera superficie web puede agrupar proveedores, recursos e inventario sin alterar la matriz
  backend ni crear autoridad de escritura adicional.

## Asuntos diferidos

- Ventanas específicas de recursos, preparación ampliada y coordinación operativa de montaje y
  desmontaje pertenecen a P13. Scheduling conserva su autoridad temporal vigente.
- Marketplace, e-commerce, portal general de proveedores, sincronización bidireccional con
  proveedores, logística avanzada y cadena de suministro completa.
- Nómina, turnos, depreciación, valoración contable de inventario, FIFO/LIFO/costo promedio, libro
  mayor, impuestos, conciliación bancaria y facturación electrónica.
- Conversión de divisas, unidades configurables entre dimensiones y automatización de compras o
  reposición mediante IA.
- Una procedencia financiera genérica o polimórfica. Ampliar `FinancialSourceReference` a otra
  fuente requerirá otra decisión, constraints y FK coherentes con esa fuente.

## Validación pendiente

Antes de aceptar implementación deberán superarse instalación limpia y migración desde los heads
vigentes, `makemigrations --check`, system checks, lint, tipos, OpenAPI, build y pruebas de regresión.
PostgreSQL real deberá demostrar:

- RLS `ENABLE` + `FORCE`, privilegios mínimos y denegación cruzada con al menos dos organizaciones;
- entrada única por recepción, rechazo de duplicado/divergencia, ausencia de movimiento para
  servicio y cuadre exacto de activos serializados;
- entrada, salida sin negativo, ajuste, traslado atómico, devolución y corrección compensatoria;
- carreras separadas de consumible, pool, activo serializado y servicio suministrado;
- cancelación y expiración de scheduling con liberación P12 en la misma transacción mediante
  servicio, ORM bulk y SQL directo;
- reprogramación completa con Operations y Resources, selección parcial explícita, conflicto,
  idempotencia y rollback integral;
- mantenimiento contra reserva/entrega y devolución contra nueva disponibilidad;
- procedencias Finance, constraints de `expense_type`/`recurring_rule`, FK tenant-aware y carrera de
  doble materialización;
- inmutabilidad, guardianes diferidos, orden de locks y ausencia de deadlocks reproducibles.

La validación local no presumirá CI remota, despliegue, cutover ni finalización de P12.

## Alternativas consideradas

- **Extender catálogo con stock y activos:** descartado porque mezcla oferta vendible con cantidad y
  custodia física.
- **Extender Operations con inventario:** descartado porque la ejecución de un evento no es
  autoridad sobre proveedores, compras o existencias reutilizables entre eventos.
- **Registrar compras y recepciones dentro de Finance:** descartado porque Finance clasifica hechos
  monetarios, pero no posee recepción física, ubicación ni capacidad.
- **Liberar recursos mediante un job posterior:** descartado porque permite confirmar scheduling y
  capacidad P12 divergentes y no protege SQL directo o bulk.
- **Usar `occupied_interval` del espacio para recursos:** descartado porque P12 solo necesita el
  intervalo público del evento; las ventanas propias pertenecen a P13.
- **Trasladar automáticamente todos los recursos al reprogramar:** descartado porque disponibilidad
  puede cambiar y los hechos físicos ejecutados no se pueden mover históricamente.
- **Hacer `FinancialSourceReference` polimórfica desde P12:** descartado porque su única FK física
  apunta a `SupplyReceiptLine`; aceptar otros tipos sin FK concreta debilitaría integridad.
- **Editar saldos, movimientos o recepciones confirmadas:** descartado porque destruye procedencia y
  hace indistinguible una corrección del hecho original.
- **Añadir valoración de inventario:** descartado porque excede P12, duplica la autoridad monetaria
  de Finance y anticipa contabilidad formal.

## Consecuencias

- Proveedores, capacidad física y abastecimiento quedan bajo una autoridad modular única y separada
  de catálogo, operación y finanzas.
- Recepción, entrada física y materialización de activos serializados quedan atómicas y defendidas
  por PostgreSQL, a costa de guardianes diferidos y locks adicionales.
- Scheduling y Resources comparten una invariante transaccional sin compartir autoridad. Las rutas
  directas incompletas fallan cerradamente y las consecuencias deterministas se materializan sin un
  job posterior.
- La reprogramación aumenta su coordinación atómica, pero conserva historia comercial, temporal,
  operativa y física sin reinterpretarla.
- Finance obtiene procedencia verificable de recepción sin importar el dominio Resources ni ceder
  autoridad monetaria. La FK de esquema añade un orden de migraciones explícito y unidireccional.
- Los ledgers append-only, proyecciones verificadas y capacidades por naturaleza añaden complejidad
  a cambio de impedir existencias negativas, sobreasignación y correcciones destructivas.
- Este documento formaliza exclusivamente la arquitectura P12. La etapa continúa pendiente de una
  autorización separada de implementación.

## Evidencia

- [Blueprint maestro](../product/PRODUCT_BLUEPRINT.md)
- [Roadmap de entrega](../product/PRODUCT_DELIVERY_ROADMAP.md)
- [Handoff vigente](../PROJECT_HANDOFF.md)
- [ADR 0009 — Aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0011 — Organizaciones, membresías y autorización](0011-organizations-memberships-and-authorization.md)
- [ADR 0014 — Multi-espacio y catálogo](0014-multi-space-business-configuration-and-catalog-boundaries.md)
- [ADR 0015 — People/CRM y autoridad comercial](0015-people-crm-boundaries-and-commercial-authority.md)
- [ADR 0016 — Scheduling e integridad temporal](0016-scheduling-ownership-and-temporal-integrity.md)
- [ADR 0020 — Autoridad financiera operativa](0020-finance-authority-recognition-and-operational-close-integrity.md)
