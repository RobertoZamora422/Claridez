# ADR 0013 — Coordinación e integridad entre comercial y operaciones

- **Estado:** Aceptado
- **Fecha:** 2026-08-01
- **Reemplaza a:** No aplica
- **Reemplazado por:** No aplica

## Contexto

La Iteración 5.2 exige que toda `Reservation` que alcance `confirmed` tenga exactamente una
`EventPreparation`, siete ítems base y una transición `initialized`; una cancelación comercial solo
puede cerrar preparaciones `preparing` o `ready`. La ruta funcional aprobada es una coordinación
explícita y atómica entre `claridez.commercial` y `claridez.operations`, sin señales Django.

Las defensas ordinarias no cubren por sí solas la relación inversa «toda confirmada tiene
preparación». Una FK uno-a-uno impide duplicados y cruces tenant, pero no obliga a que exista la fila
operativa. Además, `QuerySet.update`, operaciones bulk y SQL directo omiten los servicios y podrían
dejar estados parciales.

ADR 0009 exige aplicación tenant-aware más RLS forzado. `authorized_tenant_scope` restaura el GUC
local antes de que la transacción exterior haga commit. Por eso un constraint trigger diferido no
puede confiar en que `claridez.organization_id` conserve el valor del servicio cuando se ejecute.

## Decisiones aceptadas

1. **La ruta soportada es un coordinador de aplicación explícito.** El adaptador HTTP comercial
   llama un coordinador situado por encima de ambos módulos. Dentro de un único
   `authorized_tenant_scope` y una única transacción, el coordinador bloquea en orden
   `Reservation → EventPreparation → PreparationItem`, invoca puertos transaccionales de commercial
   y operations y materializa la respuesta antes de salir del scope. Los modelos y servicios de
   dominio de commercial no consultan tablas operativas de forma dispersa.
2. **El trigger transversal es guardián, no orquestador.** Un constraint trigger PostgreSQL
   `AFTER ROW`, `DEFERRABLE INITIALLY DEFERRED`, sobre `commercial_reservation` comprueba el estado
   final al confirmar o cancelar. No crea preparaciones, ítems ni transiciones y no reemplaza
   autorización, servicios, bloqueos ni el cutover.
3. **El guardián reconstruye de forma acotada el contexto RLS.** La función es invoker, fija
   `search_path`, no usa `SECURITY DEFINER` y revoca ejecución a `PUBLIC`. Al ejecutarse toma
   exclusivamente `NEW.organization_id`, conserva el valor previo del GUC, establece temporalmente
   `claridez.organization_id` con `set_config(..., true)`, valida las tablas operativas bajo RLS y
   restaura el valor previo. Una excepción aborta toda la transacción.
4. **La confirmación se valida al final de la transacción.** Una reserva `confirmed` debe tener una
   preparación no cancelada, baseline completa con las siete claves exactas y una sola transición
   `initialized`. Una reserva `cancelled` con `confirmed_at` no nulo debe tener preparación
   `cancelled`, baseline completa y una transición `commercial_cancellation`. Una cancelada sin
   confirmación, provisional o expirada no puede tener preparación.
5. **Las cancelaciones tardías no pueden hacerse coherentes artificialmente.** Los triggers internos
   de operations prohíben `in_progress/completed → cancelled`; por tanto, un SQL directo que cambie
   la reserva a `cancelled` desde esos estados tampoco puede satisfacer el guardián diferido y falla
   al commit.
6. **Servicios y API conservan errores de dominio.** El coordinador valida antes de escribir y
   devuelve los conflictos definidos por la especificación. Una violación inesperada del guardián
   dentro de la ruta HTTP se normaliza como `409 operation_integrity_conflict`, sin exponer SQL.
7. **Las rutas que omiten servicios no son API de dominio.** Se resuelven así:
   - SQL directo, `QuerySet.update` o `bulk_update` que confirmen/cancelen sin construir el agregado
     coherente fallan al commit con SQLSTATE `23514`;
   - `bulk_create` de reservas ya confirmadas sin agregado también falla al commit;
   - bulk o SQL directo sobre ítems y transiciones siguen sometidos a checks, FK tenant-aware,
     triggers internos, RLS e inmutabilidad;
   - una transacción técnica solo puede confirmar o cancelar por SQL/bulk si deja exactamente el
     mismo estado final coherente que los servicios. Sigue siendo una ruta no soportada y no recibe
     contrato HTTP ni compatibilidad futura.
8. **La dependencia transversal queda localizada.** `claridez.operations` consume la identidad de
   `commercial.Reservation` y su proyección pública; el coordinador depende de puertos públicos de
   ambos módulos. El trigger pertenece a una migración de operations aunque se instala sobre la
   tabla comercial. No se introducen señales ni imports de modelos operativos en el dominio
   comercial.
9. **El orden de migraciones es obligatorio.** Primero se crea el esquema operativo y se ejecutan
   preflight/backfill con el lock y cutover aprobados; después se instalan triggers internos, RLS y
   privilegios. Una migración posterior instala el constraint trigger transversal únicamente tras
   validar el backfill. Al revertir, se elimina primero el trigger sobre commercial y su función,
   luego las defensas/tablas operativas. La reaplicación respeta el mismo orden.
   Durante la validación de la FK compuesta hacia `commercial_reservation`, 0001 desactiva
   temporalmente `FORCE ROW LEVEL SECURITY` en esa tabla y lo restaura de inmediato dentro de la
   misma transacción atómica. RLS permanece habilitado, `claridez_app` no es propietario, el lock de
   cutover sigue retenido y cualquier error revierte también ese cambio; esto permite que el rol
   propietario de migración valide todas las organizaciones sin conceder `BYPASSRLS`.
10. **El cutover sigue siendo obligatorio.** El guardián limita daño por rutas no soportadas, pero no
    autoriza despliegue rolling ni sustituye detener 5.1, verificar sesiones, ejecutar el backfill,
    arrancar solo 5.2 y validar antes de abrir tráfico.

## Aspectos provisionales

Ninguno.

## Asuntos diferidos

- Ninguna corrección administrativa posterior a una ejecución o cancelación tardía se incorpora en
  5.2.
- Un patrón outbox se mantiene diferido hasta que exista un consumidor asíncrono real.

## Validación observada

La implementación superó localmente 34 pruebas de integración sobre PostgreSQL 17. La batería
cubre servicios, SQL directo, `QuerySet.update`, `bulk_create`, `bulk_update`, restauración del GUC,
dos organizaciones, RLS forzado, cancelación tardía, lock de cutover y
reversión/reaplicación. El procedimiento desplegado con cierre y reapertura real de tráfico solo
puede validarse en el entorno destino y continúa siendo obligatorio; no se presenta como ejecutado.

## Alternativas consideradas

- **Solo servicios y cutover:** descartado porque no protege SQL directo ni bulk después del
  despliegue.
- **Trigger que crea o cancela el agregado:** descartado porque duplicaría la orquestación, ocultaría
  efectos de dominio y dificultaría pruebas y errores funcionales.
- **Trigger inmediato:** descartado porque la secuencia aprobada confirma primero la reserva y
  completa el agregado dentro de la misma transacción; una comprobación inmediata observaría un
  estado intermedio válido.
- **Constraint trigger diferido que confía en el GUC residual:** descartado porque el scope restaura
  el contexto antes del commit.
- **`SECURITY DEFINER` o rol con `BYPASSRLS`:** descartado porque amplía privilegios innecesariamente;
  el contexto acotado derivado de la fila permite mantener semántica invoker y RLS.
- **Señales Django, polling u outbox:** descartados porque ocultan la transacción o introducen
  consistencia eventual e infraestructura no requerida.

## Consecuencias

- La aplicación tiene una ruta única, observable y testeable para confirmar y cancelar.
- PostgreSQL impide que una transacción termine con una reserva confirmada sin preparación o con una
  cancelación operativa incoherente, incluso si se omiten servicios.
- El trigger diferido añade acoplamiento de esquema de operations hacia commercial y obliga a un
  orden estricto de migración y reversión.
- La función debe restaurar el GUC cuidadosamente y validarse bajo conexiones reutilizadas; un error
  aborta el commit completo.
- Los errores de constraint pueden aparecer al salir de la transacción, por lo que el coordinador
  debe materializar y normalizar la respuesta dentro del límite transaccional.

## Evidencia

- [Especificación aprobada de la Iteración 5.2](../product/ITERATION_5_2_OPERATIONS_SPECIFICATION.md)
- [ADR 0009 — Estrategia de aislamiento multiempresa](0009-tenant-isolation-strategy.md)
- [ADR 0012 — Integridad de agenda y cotizaciones comerciales](0012-commercial-scheduling-and-monetary-integrity.md)
- [PostgreSQL 17 — CREATE TRIGGER](https://www.postgresql.org/docs/17/sql-createtrigger.html)
- [PostgreSQL 17 — Row Security Policies](https://www.postgresql.org/docs/17/ddl-rowsecurity.html)
- [PostgreSQL 17 — Explicit Locking](https://www.postgresql.org/docs/17/explicit-locking.html)
